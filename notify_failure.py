#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_failure.py — 日报没发出去时，用同一个邮箱给你发一封告警信。

工作流里配在 `if: failure()` 步骤上。它会读 status.json 判断卡在哪一步，
再结合 raw.json / last_response.txt 给出具体原因和处置建议。

用法:
  python notify_failure.py            # 真发告警
  python notify_failure.py --dry-run  # 只渲染不打发送，用于验证文案
环境变量:
  SMTP_* / MAIL_TO 同 mailer.py
  RUN_URL   可选，本次运行的日志链接（工作流里自动传入）
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Shanghai")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def load_json(name):
    """容忍 BOM 和脏数据：告警脚本本身绝不能再因为读不到文件而崩掉。"""
    try:
        return json.loads((BASE / name).read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def diagnose(status, raw, has_response):
    """根据已知线索推断原因，返回 (一句话结论, 建议列表)。"""
    stage = (status or {}).get("stage", "")
    failed = (status or {}).get("failed_stage", "")

    if failed == "archive" or (status or {}).get("ok"):
        return ("日报处理完成，但后续归档或工作流步骤失败",
                ["检查运行日志中的归档步骤和 outbox 下的发送凭据",
                 "邮件可能已提交 SMTP，请先检查邮箱，避免盲目重发"])

    if not status:
        return ("脚本可能在启动阶段就崩了，没有留下进度记录",
                ["展开本次运行的日志，看第一条报错",
                 "常见原因：依赖缺失、Python 版本不对、仓库文件不全"])

    if failed == "fetch" or stage.startswith("1/3"):
        if raw and raw.get("failures"):
            return (f"抓取阶段失败，{len(raw['failures'])} 个 RSS 源出错",
                    ["多半是某个新闻源改了地址或被墙，去看日志里的 FAIL 行",
                     "其他源正常的话，把出错的源从 fetch_news.py 的 SOURCES 里删掉即可"])
        if raw and raw.get("items"):
            return ("抓取阶段失败，本次没拿到新闻（现有的 raw.json 是上一次留下的旧文件，不能当证据）",
                    ["检查 fetch_news.py 里的源地址是否还能访问",
                     "GitHub 服务器偶尔会被某些站点限流，重跑一次试试"])
        return ("抓取阶段失败，没有拿到任何新闻",
                ["检查 fetch_news.py 里的源地址是否还能访问",
                 "GitHub 服务器偶尔会被某些站点限流，重跑一次试试"])

    if failed == "write" or stage.startswith("2/3"):
        err = (status or {}).get("error", "")
        tips = ["检查 DEEPSEEK_API_KEY 是否有效、有没有多余空格",
                "去 platform.deepseek.com 看余额，不足 1 元时接口会返回 402"]
        if "402" in err or "余额" in err:
            return ("DeepSeek 余额不足，无法生成稿件", ["充值后手动重跑一次即可"])
        if "401" in err or "invalid" in err.lower():
            return ("DeepSeek API key 无效或已失效", ["重新创建一个 key，更新仓库 Secret"])
        return ("模型写稿阶段失败", tips)

    if failed == "send" or stage.startswith("3/3"):
        return ("稿件已生成，但邮件发送失败",
                ["检查 SMTP_PASS 是不是填了登录密码（要 16 位授权码）",
                 "QQ 邮箱：设置 → 账号 → 确认 SMTP 服务仍是开启状态",
                 "邮件其实可能已经生成，日志里有 [dry-run] 预览路径"])

    return (f"失败在「{stage}」这一步", ["展开运行日志定位具体命令"])


def build(status, raw, has_response):
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    headline, tips = diagnose(status, raw, has_response)

    failed = (status or {}).get("failed_stage", "")
    evidence = []
    if failed == "fetch":
        evidence.append("本次抓取没有产出新的 raw.json")
    elif raw:
        evidence.append(f"抓取到 {len(raw.get('items') or [])} 条候选"
                        f"（科技 {raw.get('counts',{}).get('tech','?')} / "
                        f"其他 {raw.get('counts',{}).get('other','?')}）")
        if raw.get("failures"):
            evidence.append(f"失败的源：{'、'.join(f.split(':')[0] for f in raw['failures'])}")
        else:
            evidence.append("所有新闻源正常")
    else:
        evidence.append("没有抓到任何新闻（raw.json 不存在）")
    evidence.append("模型已有返回内容" if has_response else "模型没有返回内容")
    stage = (status or {}).get("stage", "无记录")
    evidence.append(f"最后到达的步骤：{stage}")

    run_url = os.environ.get("RUN_URL", "").strip()
    subject = f"⚠️ AI 日报工作流异常 · {date_str}"

    text = (f"今天的日报工作流发生异常，请根据下方证据判断发送状态。\n\n"
            f"原因：{headline}\n\n"
            f"排查线索：\n" + "\n".join(f"  · {e}" for e in evidence) +
            f"\n\n建议：\n" + "\n".join(f"  {i+1}. {t}" for i, t in enumerate(tips)) +
            (f"\n\n运行日志：{run_url}" if run_url else "") +
            f"\n\n—— 这封是自动告警，不需要回复。")

    tips_html = "".join(f'<li style="margin:6px 0;">{t}</li>' for t in tips)
    ev_html = "".join(f'<li style="margin:4px 0;">{e}</li>' for e in evidence)
    link = (f'<p style="margin-top:18px;"><a href="{run_url}" '
            f'style="color:#12507b;">→ 查看这次运行的完整日志</a></p>') if run_url else ""

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;">
<div style="max-width:600px;margin:0 auto;padding:24px 16px;font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;color:#1f2933;font-size:15px;line-height:1.65;">
  <div style="background:#8c2f2f;border-radius:12px 12px 0 0;padding:20px 24px;color:#fff;">
    <div style="font-size:12px;letter-spacing:2px;opacity:.75;">ALERT · 自动告警</div>
    <div style="font-size:20px;font-weight:700;margin-top:6px;">日报工作流发生异常</div>
    <div style="font-size:13px;opacity:.85;margin-top:4px;">{date_str} 的运行异常</div>
  </div>
  <div style="background:#fff;border-radius:0 0 12px 12px;padding:20px 24px 24px;">
    <div style="font-size:13px;font-weight:700;color:#8c2f2f;padding-bottom:8px;border-bottom:2px solid #f0e0e0;">直接原因</div>
    <p style="margin:12px 0 0;font-size:16px;">{headline}</p>

    <div style="margin-top:22px;font-size:13px;font-weight:700;color:#0f2b46;padding-bottom:8px;border-bottom:2px solid #e3e8ef;">排查线索</div>
    <ul style="margin:10px 0 0;padding-left:20px;color:#3e4c59;font-size:14px;">{ev_html}</ul>

    <div style="margin-top:22px;font-size:13px;font-weight:700;color:#0f2b46;padding-bottom:8px;border-bottom:2px solid #e3e8ef;">建议怎么做</div>
    <ol style="margin:10px 0 0;padding-left:20px;color:#3e4c59;font-size:14px;">{tips_html}</ol>

    {link}
    <p style="margin-top:22px;color:#a0aab8;font-size:12px;">这封是自动告警，不需要回复。补发一期可以手动触发工作流。</p>
  </div>
</div></body></html>"""
    return subject, html, text


def main():
    dry = "--dry-run" in sys.argv
    status = load_json("status.json")
    raw = load_json("raw.json")
    has_response = (BASE / "last_response.txt").exists()

    subject, html, text = build(status, raw, has_response)
    if "--test" in sys.argv:
        subject = "［测试］" + subject

    if dry:
        print("=== 标题 ===")
        print(subject)
        print("\n=== 纯文本正文 ===")
        print(text)
        print(f"\n(html {len(html)} 字节，未发送)")
        return 0

    import mailer
    try:
        to = mailer.send(subject, html, text)
    except mailer.MailError as e:
        print(f"告警邮件也没发出去: {e}", file=sys.stderr)
        return 1
    print(f"告警已发送 -> {', '.join(to)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
