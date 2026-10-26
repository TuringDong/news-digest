#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mailer.py — 从环境变量读 SMTP 配置并发送邮件（QQ / 163 / Gmail 均适用）。

环境变量:
  SMTP_HOST   默认 smtp.qq.com
  SMTP_PORT   默认 465（SSL）；587 会自动走 STARTTLS
  SMTP_USER   发件邮箱
  SMTP_PASS   授权码（不是登录密码！）
  MAIL_TO     收件人，多个用逗号分隔
  FROM_NAME   发件人显示名，默认「AI 新闻日报」
"""

import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


class MailError(RuntimeError):
    pass


def read_config():
    cfg = {
        "host": os.environ.get("SMTP_HOST", "smtp.qq.com").strip(),
        "port": int(os.environ.get("SMTP_PORT", "465")),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "pass": os.environ.get("SMTP_PASS", "").strip().replace(" ", ""),
        "from_name": os.environ.get("FROM_NAME", "AI 新闻日报").strip(),
    }
    to_raw = os.environ.get("MAIL_TO", "").strip()
    cfg["to"] = [t.strip() for t in to_raw.replace(";", ",").split(",") if t.strip()]
    missing = [k for k in ("user", "pass") if not cfg[k]]
    if missing:
        raise MailError(f"缺少环境变量: {', '.join('SMTP_' + m.upper() for m in missing)}")
    if not cfg["to"]:
        raise MailError("缺少环境变量 MAIL_TO（收件人）")
    return cfg


def build(cfg, subject, html_body, text_body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["from_name"], cfg["user"]))
    msg["To"] = ", ".join(cfg["to"])
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg["user"].split("@")[-1])
    msg.set_content(text_body, subtype="plain", charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")
    return msg


def verify():
    """只验证 SMTP 配置能否登录，不发信。用于排查配置问题。"""
    cfg = read_config()
    ctx = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30, context=ctx) as s:
            s.login(cfg["user"], cfg["pass"])
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(cfg["user"], cfg["pass"])
    return cfg["user"], cfg["to"]


def send(subject, html_body, text_body, attempts=3):
    cfg = read_config()
    msg = build(cfg, subject, html_body, text_body)
    last = None
    for i in range(1, attempts + 1):
        try:
            ctx = ssl.create_default_context()
            if cfg["port"] == 465:
                with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=45, context=ctx) as s:
                    s.login(cfg["user"], cfg["pass"])
                    s.send_message(msg, from_addr=cfg["user"], to_addrs=cfg["to"])
            else:
                with smtplib.SMTP(cfg["host"], cfg["port"], timeout=45) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.ehlo()
                    s.login(cfg["user"], cfg["pass"])
                    s.send_message(msg, from_addr=cfg["user"], to_addrs=cfg["to"])
            return cfg["to"]
        except smtplib.SMTPAuthenticationError as e:
            raise MailError(f"认证失败（授权码错误或 SMTP 未开启）: {e}")
        except (smtplib.SMTPException, OSError) as e:
            last = f"{type(e).__name__}: {e}"
            if i < attempts:
                time.sleep(3 * i)
    raise MailError(f"发送失败（重试 {attempts} 次）: {last}")
