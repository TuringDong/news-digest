#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render.py — 把 digest.json 渲染成邮件 HTML + 纯文本。样式与本地版保持一致。"""

import html


def esc(s):
    return html.escape(str(s or "")).strip()


def render_html(d):
    date_str = esc(d.get("date", ""))
    meta = esc(d.get("meta", ""))
    sections = d.get("sections") or []
    quick_zh = d.get("quick_zh") or []
    quick_en = d.get("quick_en") or []

    parts = [f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 日报 {date_str}</title></head>
<body style="margin:0;padding:0;background:#f4f6f8;">
<div style="max-width:680px;margin:0 auto;padding:24px 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Helvetica,Arial,sans-serif;color:#1f2933;font-size:15px;line-height:1.65;">

  <div style="background:#0f2b46;border-radius:12px 12px 0 0;padding:22px 24px;color:#fff;">
    <div style="font-size:12px;letter-spacing:2px;opacity:.72;text-transform:uppercase;">Daily Brief · 双语新闻日报</div>
    <div style="font-size:23px;font-weight:700;margin-top:6px;line-height:1.3;">{esc(d.get("headline_zh","AI 与科技要闻"))}</div>
    <div style="font-size:14px;opacity:.85;margin-top:4px;">{esc(d.get("headline_en","AI &amp; Tech Highlights"))}</div>
    <div style="margin-top:14px;padding-top:12px;border-top:1px solid rgba(255,255,255,.18);font-size:12px;opacity:.78;">{date_str} &nbsp;·&nbsp; {meta}</div>
  </div>

  <div style="background:#ffffff;border-radius:0 0 12px 12px;padding:8px 24px 24px;">
"""]

    if not sections:
        parts.append('<p style="color:#8a94a6;">（本期无条目 / no items）</p>')

    for sec in sections:
        parts.append(f"""
    <div style="margin-top:26px;">
      <div style="font-size:13px;font-weight:700;color:#0f2b46;letter-spacing:.5px;padding-bottom:8px;border-bottom:2px solid #e3e8ef;">
        {esc(sec.get("title_zh",""))}<span style="color:#8a94a6;font-weight:500;">&nbsp;/&nbsp;{esc(sec.get("title_en",""))}</span>
      </div>""")

        for it in sec.get("items") or []:
            url = (it.get("url") or "").strip()
            title_zh = esc(it.get("title_zh"))
            source = esc(it.get("source"))
            if url.startswith("http"):
                title_html = f'<a href="{esc(url)}" style="color:#12507b;text-decoration:none;">{title_zh}</a>'
            else:
                title_html = title_zh

            tag = ""
            if it.get("tag"):
                tag = (f'<span style="display:inline-block;background:#eef4fa;color:#12507b;'
                       f'font-size:11px;padding:1px 7px;border-radius:99px;margin-left:8px;'
                       f'font-weight:600;vertical-align:1px;">{esc(it["tag"])}</span>')

            src_line = f'<span style="color:#8a94a6;">· {source}</span>' if source else ""

            parts.append(f"""
      <div style="margin-top:16px;padding:14px 16px;background:#fafbfc;border-left:3px solid #d7e0ea;border-radius:0 8px 8px 0;">
        <div style="font-size:16px;font-weight:600;line-height:1.45;color:#12202e;">{title_html}{tag}</div>
        <div style="font-size:14px;color:#3e4c59;margin-top:6px;">{esc(it.get("body_zh",""))}</div>
        <div style="font-size:13px;color:#7b8794;margin-top:7px;line-height:1.6;">{esc(it.get("title_en",""))} —— {esc(it.get("body_en",""))}</div>
        <div style="font-size:12px;color:#a0aab8;margin-top:6px;">{src_line}</div>
      </div>""")

        parts.append("\n    </div>")

    if quick_zh or quick_en:
        li = []
        for i, q in enumerate(quick_zh):
            en = quick_en[i] if i < len(quick_en) else ""
            li.append(f'<li style="margin:8px 0;">{esc(q)}'
                      f'<div style="color:#7b8794;font-size:13px;">{esc(en)}</div></li>')
        parts.append(f"""
    <div style="margin-top:28px;">
      <div style="font-size:13px;font-weight:700;color:#0f2b46;padding-bottom:8px;border-bottom:2px solid #e3e8ef;">
        一句话速览<span style="color:#8a94a6;font-weight:500;">&nbsp;/&nbsp;In Brief</span>
      </div>
      <ul style="margin:12px 0 0;padding-left:20px;color:#3e4c59;font-size:14px;">
        {''.join(li)}
      </ul>
    </div>""")

    parts.append(f"""
  </div>

  <div style="text-align:center;color:#a0aab8;font-size:11.5px;padding:18px 10px;line-height:1.7;">
    由 DeepSeek Harness 自动生成 · Generated automatically<br>
    内容来自公开报道摘要，关键数据建议点开原文核对 / summaries of public reporting, verify key facts at source<br>
    <span style="opacity:.8;">{date_str}</span>
  </div>
</div></body></html>""")

    return "".join(parts)


def render_text(d):
    lines = ["=" * 58,
             f"AI 与科技日报 / Daily AI & Tech Brief — {d.get('date','')}",
             d.get("meta", ""),
             "=" * 58]
    for sec in d.get("sections") or []:
        lines += ["", f"【{sec.get('title_zh','')} / {sec.get('title_en','')}】"]
        for it in sec.get("items") or []:
            lines += ["",
                      f"- {it.get('title_zh','')}",
                      f"  {it.get('body_zh','')}",
                      f"  EN: {it.get('title_en','')}",
                      f"      {it.get('body_en','')}"]
            if it.get("source"):
                lines.append(f"  [{it.get('source')}] {it.get('url','')}".rstrip())
    if d.get("quick_zh"):
        lines += ["", "【一句话速览 / In Brief】"]
        for i, q in enumerate(d.get("quick_zh") or []):
            en = (d.get("quick_en") or [])[i] if i < len(d.get("quick_en") or []) else ""
            lines.append(f"- {q}" + (f"  ({en})" if en else ""))
    lines += ["", "--", "由 DeepSeek Harness 自动生成 / generated automatically"]
    return "\n".join(lines)
