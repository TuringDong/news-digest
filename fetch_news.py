#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_news.py — 从多个 RSS 源抓取时间窗口内的新闻，输出 raw.json。

只用标准库，无第三方依赖。任何一个源挂掉都不会影响整体。

用法:
  python fetch_news.py                 # 抓昨天的新闻 -> raw.json
  python fetch_news.py --hours 30      # 自定义窗口（小时）
  python fetch_news.py --out raw.json
"""

import argparse
import email.utils
import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from html import unescape
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

# Windows 控制台默认 GBK，遇到外文标题里的 č、emoji 会 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
UA = "Mozilla/5.0 (compatible; daily-digest/1.0; +https://github.com)"
TIMEOUT = 25

# ---------------------------------------------------------------- 新闻源
# cat: tech = 科技/AI 主线；other = 其他领域大新闻
SOURCES = [
    # --- 科技 / AI（英文）---
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage?points=100", "cat": "tech", "max": 6},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "cat": "tech", "max": 6},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "cat": "tech", "max": 5},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "cat": "tech", "max": 5},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/", "cat": "tech", "max": 4},

    # --- 科技 / AI（中文）---
    {"name": "量子位", "url": "https://www.qbitai.com/feed", "cat": "tech", "max": 5},
    {"name": "IT之家", "url": "https://www.ithome.com/rss/", "cat": "tech", "max": 5},
    {"name": "Google AI 中文检索", "url": "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD%20OR%20%E5%A4%A7%E6%A8%A1%E5%9E%8B%20when:2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "cat": "tech", "max": 8},

    # --- 其他领域（英文）---
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "cat": "other", "max": 6},
    {"name": "The Guardian World", "url": "https://www.theguardian.com/world/rss", "cat": "other", "max": 5},
    {"name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml", "cat": "other", "max": 4},
    # 体育必须单列。之前没有体育源，凯恩夺金球奖这种头条级新闻压根进不了候选池，
    # 模型连看都没看到，自然写不出来。
    {"name": "BBC Sport", "url": "https://feeds.bbci.co.uk/sport/rss.xml", "cat": "other", "max": 5},
    {"name": "The Guardian Sport", "url": "https://www.theguardian.com/sport/rss", "cat": "other", "max": 4},

    # --- 其他领域（中文）---
    {"name": "Google 新闻中文", "url": "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "cat": "other", "max": 8},
    {"name": "Google 体育中文", "url": "https://news.google.com/rss/search?q=%E4%BD%93%E8%82%B2%20OR%20%E9%87%91%E7%90%83%E5%A5%96%20OR%20%E7%90%83%E8%B5%9B%20when:2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "cat": "other", "max": 5},
    {"name": "Google 娱乐中文", "url": "https://news.google.com/rss/search?q=%E5%A8%B1%E4%B9%90%20OR%20%E7%94%B5%E5%BD%B1%20OR%20%E6%BC%94%E5%94%B1%E4%BC%9A%20when:2d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "cat": "other", "max": 3},
    {"name": "Google News World", "url": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en", "cat": "other", "max": 6},
    {"name": "Google AI 检索", "url": "https://news.google.com/rss/search?q=AI%20OR%20%22artificial%20intelligence%22%20when:2d&hl=en-US&gl=US&ceid=US:en", "cat": "tech", "max": 6},
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(text, limit=500):
    if not text:
        return ""
    t = TAG_RE.sub(" ", text)
    t = unescape(t)
    t = WS_RE.sub(" ", t).strip()
    if len(t) > limit:
        t = t[: limit - 1].rstrip() + "…"
    return t


def tidy_summary(s):
    """去掉 HN 之类的「Article URL: … Points: 108」样板噪声，没实质内容就留空。"""
    if not s:
        return ""
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"(Article URL|Comments URL|Points|#\s*Comments)\s*:?", " ", s)
    s = WS_RE.sub(" ", s).strip(" -·|,;")
    return s if len(s) >= 25 else ""


def parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(TZ)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(TZ)
    except Exception:
        return None


def _localname(tag):
    return tag.rsplit("}", 1)[-1].lower()


CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
BARE_AMP_RE = re.compile(r"&(?!(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][\w.-]*);)")


def sanitize_xml(blob):
    """把常见的坏 XML 修成能解析的：控制字符、裸 &、错误编码。"""
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            text = blob.decode(enc, errors="replace")
            break
        except Exception:
            continue
    text = text.replace("\ufeff", "")
    text = CTRL_RE.sub("", text)
    text = BARE_AMP_RE.sub("&amp;", text)
    return text.encode("utf-8", errors="replace")


def _child_text(node, names):
    for child in node:
        if _localname(child.tag) in names:
            if _localname(child.tag) == "link" and child.get("href"):
                return child.get("href")
            if child.text:
                return child.text
    return ""


def parse_feed(blob):
    """同时容忍 RSS 2.0 / RSS 1.0 / Atom。返回 [(title, link, date, summary)]。

    不少中文源会输出非法 XML（裸 & 、控制字符、编码声明与实际不符），
    所以先按原样解析，失败再清洗一遍重试，而不是直接丢弃整个源。
    """
    try:
        root = ET.fromstring(blob)
    except ET.ParseError:
        cleaned = sanitize_xml(blob)
        root = ET.fromstring(cleaned)
    out = []
    entries = [e for e in root.iter() if _localname(e.tag) in ("item", "entry")]
    for e in entries:
        title = clean(_child_text(e, {"title"}), 300)
        link = (_child_text(e, {"link"}) or "").strip()
        if not link:
            for child in e:
                if _localname(child.tag) == "link":
                    link = (child.get("href") or child.text or "").strip()
                    if link:
                        break
        date = parse_date(_child_text(e, {"pubdate", "published", "updated", "date"}))
        summary = clean(
            _child_text(e, {"description", "summary", "content", "encoded"}), 600
        )
        if title and link:
            out.append({"title": title, "link": link, "date": date, "summary": summary})
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=0,
                    help="窗口小时数；0 = 从昨天 00:00 到现在")
    ap.add_argument("--out", default="raw.json")
    ap.add_argument("--min-items", type=int, default=12,
                    help="低于这个数量就放宽时间过滤")
    args = ap.parse_args()

    now = datetime.now(TZ)
    if args.hours:
        start = now - timedelta(hours=args.hours)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    items, stale, failures, stats = [], [], [], []

    for src in SOURCES:
        try:
            blob = fetch(src["url"])
            entries = parse_feed(blob)
            took = 0
            for e in entries[: src["max"] * 2]:
                rec = {
                    "title": e["title"],
                    "link": e["link"],
                    "summary": tidy_summary(e["summary"]),
                    "source": src["name"],
                    "cat": src["cat"],
                    "published": e["date"].isoformat() if e["date"] else None,
                }
                if e["date"] is None:
                    stale.append(rec)
                elif start <= e["date"] <= now + timedelta(hours=1):
                    items.append(rec)
                    took += 1
                if took >= src["max"]:
                    break
            stats.append(f"{src['name']}={took}")
            print(f"  ok   {src['name']:<22} {len(entries):>3} 条 -> 窗口内 {took}", file=sys.stderr)
        except Exception as e:
            failures.append(f"{src['name']}: {type(e).__name__}: {e}")
            print(f"  FAIL {src['name']:<22} {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(0.4)

    # 去重（标题归一化）
    seen, uniq = set(), []
    for it in items:
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    # 新闻太少的兜底：把无日期的最新条目补进来（宁可给模型多几条）
    if len(uniq) < args.min_items and stale:
        for it in stale[: args.min_items - len(uniq)]:
            uniq.append(it)

    payload = {
        "generated_at": now.isoformat(),
        "window": {"start": start.isoformat(), "end": now.isoformat()},
        "counts": {"tech": sum(1 for x in uniq if x["cat"] == "tech"),
                   "other": sum(1 for x in uniq if x["cat"] == "other")},
        "per_source": stats,
        "failures": failures,
        "items": uniq,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n共 {len(uniq)} 条（tech={payload['counts']['tech']}, other={payload['counts']['other']}）"
          f"  失败源 {len(failures)} 个 -> {args.out}", file=sys.stderr)
    if not uniq:
        print("ERROR: 一条都没抓到，检查网络或源地址", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
