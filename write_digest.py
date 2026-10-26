#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
write_digest.py — 把 raw.json 交给 DeepSeek，产出符合排版要求的双语 digest.json。

设计要点：
  * 反幻觉：只允许使用候选条目里的事件和链接，链接必须逐字复制，
    校验时任何不在候选集合里的 url 都会被丢弃。
  * 条数不设配额：由当天的新闻量决定，prompt 里明确禁止凑数。
  * 只用标准库（urllib 调 API）。

用法:
  python write_digest.py --raw raw.json --out digest.json
  python write_digest.py --raw raw.json --out digest.json --show-prompt
环境变量:
  DEEPSEEK_API_KEY   必填
  DEEPSEEK_BASE_URL  默认 https://api.deepseek.com
  DEEPSEEK_MODEL     默认 deepseek-chat
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

# Windows 控制台默认 GBK，遇到 č、emoji 这类字符会 UnicodeEncodeError 中断流程
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SYSTEM_PROMPT = """你是一位资深的科技媒体主编，负责为一位中国读者编写每日双语新闻简报。
你写的稿子会被直接排版成邮件，读者只看这一封信就知道昨天世界上发生了什么。

写作要求：
- 中文自然、干脆、有人味，不堆砌形容词，不写“随着…的发展”“值得注意的是”这类空话。
- 英文是给同一个人看的第二语言版本，要地道、简洁，是重写而不是逐字直译。
- 每条 2-3 句，说清「谁做了什么 / 意味着什么」，带上具体数字、人名、机构。
- 只写候选材料里确实有的事实。材料里没有的数字、时间、人名，一律不许编。
- 拿不准的细节就用限定语（如“据报道”“尚待确认”），宁可保守也不许瞎猜。"""


def build_user_prompt(raw, now):
    items = raw["items"]
    lines = []
    for i, it in enumerate(items, 1):
        when = (it.get("published") or "")[:16].replace("T", " ")
        lines.append(
            f"[{i}] ({it['cat']}/{it['source']}) {when}\n"
            f"    标题: {it['title']}\n"
            f"    摘要: {it['summary'][:320]}\n"
            f"    链接: {it['link']}"
        )
    catalog = "\n".join(lines)

    return f"""今天是 {now.strftime('%Y-%m-%d')}（北京时间），统计窗口是 {raw['window']['start'][:16].replace('T',' ')} 到现在。

下面是昨天到现在的候选新闻（共 {len(items)} 条，tech = 科技/AI，other = 其他领域）：

{catalog}

请从中挑选真正值得上头条的，产出一份双语日报，严格按以下 JSON 结构输出（只输出 JSON，不要任何解释文字、不要 markdown 代码块）：

{{
  "headline_zh": "一句话点出当天最重的两三件事，不超过 40 字",
  "headline_en": "one line, the day's biggest two or three things",
  "sections": [
    {{
      "title_zh": "分区名，中文，如「AI 前沿」",
      "title_en": "section name in English, e.g. 'AI Frontier'",
      "items": [
        {{
          "title_zh": "中文标题，不超过 30 字",
          "title_en": "English headline",
          "body_zh": "2-3 句中文，说清事实与意义",
          "body_en": "2-3 sentences of idiomatic English",
          "source": "来源名，用候选里括号内的 source",
          "url": "候选条目里的链接，必须逐字复制",
          "tag": "一个 2-4 字的中文标签，如 政策/市场/安全/硬件/地缘"
        }}
      ]
    }}
  ],
  "quick_zh": ["次要补充的一句话，最多 3 条"],
  "quick_en": ["same in English"]
}}

硬性规则：
1. 科技/AI 是主线，篇幅必须**明显多于**其他领域，大约 2:1（例如 6 条科技配 3 条其他）。
   其他领域**必须单独成区**，标题用「其他要闻 / Beyond Tech」，规格与科技条目完全一样，不许压进 quick 里。
2. 即使某天政治/地缘大新闻扎堆、看着比科技更刺激，也要守住上面的比例：**砍掉其他领域里次要的那几条**，
   而不是让其他领域反超科技。这是这份日报的定位，不要临场发挥。
3. 条数不设配额：新闻多的日子可以多写，平淡的日子少写几条也行。绝对不要为了凑数或凑满分区而收录平庸的新闻。
4. 但即使再平淡，科技和其他这两个方向也各至少要有 1 条。
5. 分区数量自由，2-5 个都可以，不必固定。
6. url 只能来自上面的候选，逐字复制，不许自己拼（链接很长时务必整段复制，不要截断）。
7. quick_zh/quick_en 只放确实次要的补充，条数一一对应。
"""


def call_api(api_key, base_url, model, messages, retries=3):
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 6000,
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        })
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"], data
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            last = f"HTTP {e.code}: {detail}"
            if e.code in (401, 403, 402):
                raise RuntimeError(f"API 拒绝（key 无效/余额不足）: {last}")
            if e.code < 500:
                raise RuntimeError(last)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(4 * attempt + random.random() * 2)
    raise RuntimeError(f"API 重试 {retries} 次仍失败: {last}")


def parse_json_block(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def resolve_url(url, allowed):
    """把模型给的链接对回候选集。

    模型抄超长链接（尤其 Google News 那种一长串 base64）时常截断几个字符，
    直接逐字比对会误杀真新闻。所以按「精确 -> 前缀 -> 文章 id」三级回退。
    只有确实对不上（等于自造）才返回 None。
    """
    url = (url or "").strip()
    if url in allowed:
        return url
    if len(url) < 25:
        return None
    cands = [k for k in allowed if k.startswith(url[:70]) or url.startswith(k[:70])]
    if len(cands) == 1:
        return cands[0]
    m = re.search(r"/articles/([A-Za-z0-9_\-]{12,})", url)
    if m:
        frag = m.group(1)[:28]
        c2 = [k for k in allowed if frag in k]
        if len(c2) == 1:
            return c2[0]
    return None


def rebalance(sections, allowed, warn):
    """守住「科技为主」：其他领域条目不得超过科技条目的六成左右。

    模型遇到政治大新闻扎堆的日子会写嗨，把其他领域堆得比科技还多。
    这里按模型自己给的优先级（越靠前越重要）从尾部裁掉多余的，宁可少而准。
    """
    def cat(it):
        return (allowed.get(it.get("url", "")) or {}).get("cat", "")

    tech = sum(1 for s in sections for it in s["items"] if cat(it) == "tech")
    other = sum(1 for s in sections for it in s["items"] if cat(it) == "other")
    limit = max(1, tech // 2 + 1)
    if other <= limit or tech == 0:
        return sections, 0

    budget = limit
    trimmed = 0
    kept = []
    for sec in sections:
        items = []
        for it in sec["items"]:
            if cat(it) == "other":
                if budget > 0:
                    budget -= 1
                    items.append(it)
                else:
                    trimmed += 1
            else:
                items.append(it)
        if items:
            kept.append(dict(sec, items=items))
    if trimmed:
        warn(f"其他领域 {other} 条 > 科技 {tech} 条，按优先级裁掉尾部 {trimmed} 条以守住科技为主")
    return kept, trimmed


def validate(data, raw, warn):
    """校验并就地清洗；返回 (data, dropped)。"""
    allowed = {it["link"]: it for it in raw["items"]}
    if not isinstance(data.get("sections"), list) or not data["sections"]:
        raise ValueError("模型返回里没有 sections")

    dropped = 0
    clean_sections = []
    for sec in data["sections"]:
        if not isinstance(sec, dict):
            continue
        items = []
        for it in sec.get("items") or []:
            url = resolve_url(it.get("url"), allowed)
            if not url:
                dropped += 1
                warn(f"丢弃无出处条目: {str(it.get('title_zh'))[:40]} url={str(it.get('url'))[:60]}")
                continue
            it["url"] = url
            for f in ("title_zh", "title_en", "body_zh", "body_en"):
                it[f] = (it.get(f) or "").strip()
            if not all(it[f] for f in ("title_zh", "title_en", "body_zh")):
                dropped += 1
                warn(f"字段不全，丢弃: {it.get('title_zh') or url}")
                continue
            if not it["body_en"]:
                it["body_en"] = it["title_en"]
            it["source"] = (it.get("source") or allowed[url]["source"]).strip()
            it["tag"] = (it.get("tag") or "").strip()[:6]
            items.append(it)
        if items:
            clean_sections.append({
                "title_zh": (sec.get("title_zh") or "要闻").strip(),
                "title_en": (sec.get("title_en") or "Headlines").strip(),
                "items": items,
            })

    if not clean_sections:
        raise ValueError("清洗后没有任何有效条目（可能链接全部为模型自造）")

    clean_sections, _ = rebalance(clean_sections, allowed, warn)

    total = sum(len(s["items"]) for s in clean_sections)
    def _cat(it):
        return (allowed.get(it.get("url", "")) or {}).get("cat", "")
    tech = sum(1 for s in clean_sections for it in s["items"] if _cat(it) == "tech")
    other = sum(1 for s in clean_sections for it in s["items"] if _cat(it) == "other")
    if other == 0:
        warn("警告：这期没有「其他领域」条目，可能违反编辑方针")
    if tech == 0:
        warn("警告：这期没有科技条目，跑偏了")

    qz = [str(x).strip() for x in (data.get("quick_zh") or []) if str(x).strip()]
    qe = [str(x).strip() for x in (data.get("quick_en") or []) if str(x).strip()]
    n = min(len(qz), len(qe))
    data = {
        "headline_zh": (data.get("headline_zh") or "").strip(),
        "headline_en": (data.get("headline_en") or "").strip(),
        "sections": clean_sections,
        "quick_zh": qz[:n][:3],
        "quick_en": qe[:n][:3],
    }
    warn(f"校验通过：{len(clean_sections)} 个分区 / {total} 条"
         f"（tech={tech} other={other}），丢弃 {dropped} 条")
    return data, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw.json")
    ap.add_argument("--out", default="digest.json")
    ap.add_argument("--show-prompt", action="store_true")
    ap.add_argument("--keep-response", default="", help="把模型原始返回存到该文件，便于排查")
    args = ap.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    raw = json.load(open(args.raw, encoding="utf-8"))
    now = datetime.now(TZ)
    user_prompt = build_user_prompt(raw, now)

    if args.show_prompt:
        print(user_prompt)
        print(f"\n--- prompt 长度 {len(user_prompt)} 字符，候选 {len(raw['items'])} 条 ---",
              file=sys.stderr)
        return 0

    if not api_key:
        print("ERROR: 缺少环境变量 DEEPSEEK_API_KEY", file=sys.stderr)
        return 2

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    print(f"调用 {model} …（候选 {len(raw['items'])} 条，prompt {len(user_prompt)} 字）", file=sys.stderr)
    try:
        content, _ = call_api(api_key, base_url, model, messages)
    except RuntimeError as e:
        msg = str(e)
        print(f"ERROR: {msg}", file=sys.stderr)
        if "401" in msg or "403" in msg or "invalid" in msg.lower():
            print("提示：API key 必须是从平台控制台创建、形如 sk-xxxxxxxx 的密钥；"
                  "UUID 形式的字符串通常不是 API key。", file=sys.stderr)
        elif "402" in msg or "balance" in msg.lower():
            print("提示：账户余额不足，去控制台充值。", file=sys.stderr)
        return 2
    if args.keep_response:
        open(args.keep_response, "w", encoding="utf-8").write(content)

    data = parse_json_block(content)
    data, dropped = validate(data, raw, lambda m: print(m, file=sys.stderr))

    date_str = now.strftime("%Y-%m-%d")
    out = {
        "date": date_str,
        "subject": f"AI 与科技日报 {date_str} · Daily AI & Tech Brief",
        "meta": f"统计窗口 {raw['window']['start'][:16].replace('T',' ')} → "
                f"{raw['window']['end'][:16].replace('T',' ')} (UTC+8)",
    }
    out.update(data)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已写出 {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
