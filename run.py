#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run.py — 一条龙：抓新闻 -> 让模型写稿 -> 渲染 -> 发邮件。

用法:
  python run.py                       # 完整流程（本地/云端都用这个）
  python run.py --dry-run             # 只生成不发信，产物留在 outbox/
  python run.py --digest d.json       # 跳过抓取和写作，直接渲染+发送某个现成稿件
  python run.py --no-fetch            # 复用已有的 raw.json 重新写稿

退出码: 0 成功 / 2 缺配置 / 3 抓取失败 / 4 写作失败 / 5 发信失败
"""

import argparse
import json
import os
import subprocess
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


def step(msg):
    print(f"\n=== {msg} ===", file=sys.stderr, flush=True)


def mark(stage, **extra):
    """记录当前进行到哪一步，供失败告警读取。任何异常都不许影响主流程。"""
    try:
        payload = {"stage": stage, "at": datetime.now(TZ).isoformat()}
        payload.update(extra)
        (BASE / "status.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def run_script(name, extra=None):
    cmd = [sys.executable, str(BASE / name)] + (extra or [])
    proc = subprocess.run(cmd, cwd=str(BASE))
    return proc.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--digest", default="")
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()

    os.chdir(BASE)
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    outbox = BASE / "outbox"
    outbox.mkdir(exist_ok=True)
    raw_path = BASE / "raw.json"
    digest_path = BASE / "digest.json"

    if args.digest:
        step(f"使用现成稿件 {args.digest}")
        digest_path = Path(args.digest)
        if not digest_path.is_absolute():
            digest_path = BASE / digest_path
        if not digest_path.exists():
            print(f"ERROR: 找不到 {digest_path}", file=sys.stderr)
            return 4
        d = json.load(open(digest_path, encoding="utf-8"))
    else:
        if not args.no_fetch:
            step("1/3 抓取新闻源")
            mark("1/3 抓取新闻源")
            rc = run_script("fetch_news.py", ["--out", str(raw_path)])
            if rc != 0:
                mark("1/3 抓取新闻源（失败）", failed_stage="fetch")
                print("ERROR: 抓取失败，没有任何新闻可写", file=sys.stderr)
                return 3
        else:
            if not raw_path.exists():
                print("ERROR: --no-fetch 但 raw.json 不存在", file=sys.stderr)
                return 3

        step("2/3 交给模型写稿")
        mark("2/3 模型写稿")
        rc = run_script("write_digest.py", [
            "--raw", str(raw_path),
            "--out", str(digest_path),
            "--keep-response", str(BASE / "last_response.txt"),
        ])
        if rc != 0:
            mark("2/3 模型写稿（失败）", failed_stage="write")
            print("ERROR: 写稿失败（检查 DEEPSEEK_API_KEY / 余额 / 网络）", file=sys.stderr)
            return 4
        d = json.load(open(digest_path, encoding="utf-8"))

    d.setdefault("date", date_str)
    import render
    html_body = render.render_html(d)
    text_body = render.render_text(d)

    html_copy = outbox / f"{d.get('date') or date_str}.html"
    html_copy.write_text(html_body, encoding="utf-8")
    (outbox / f"{d.get('date') or date_str}.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    total = sum(len(s.get("items") or []) for s in d.get("sections") or [])
    sections = len(d.get("sections") or [])
    subject = d.get("subject") or f"AI 与科技日报 {date_str} · Daily AI & Tech Brief"

    print(f"\n稿件：{sections} 个分区 / {total} 条", file=sys.stderr)
    for s in d["sections"]:
        print(f"  - {s['title_zh']} ({len(s['items'])} 条)", file=sys.stderr)

    step("3/3 发送邮件")
    mark("3/3 发送邮件")
    if args.dry_run:
        mark("完成（dry-run，未发送）", ok=True)
        print(f"[dry-run] 未发送。预览: {html_copy}", file=sys.stderr)
        print(f"[dry-run] 标题: {subject}", file=sys.stderr)
        return 0

    import mailer
    try:
        to = mailer.send(subject, html_body, text_body)
    except mailer.MailError as e:
        mark("3/3 发送邮件（失败）", failed_stage="send", error=str(e)[:300])
        print(f"ERROR: {e}", file=sys.stderr)
        return 5
    mark("完成", ok=True, sent_to=to, subject=subject)
    print(f"已发送 -> {', '.join(to)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
