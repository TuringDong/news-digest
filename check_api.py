#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_api.py — 30 秒确认 API key 能不能用、账户还有没有钱。

先跑这个，再跑全流程，能把「key 错了」和「稿子写得不好」两类问题分开。

用法:
  set DEEPSEEK_API_KEY=sk-xxxx        (PowerShell: $env:DEEPSEEK_API_KEY="sk-xxxx")
  python check_api.py

可选环境变量:
  DEEPSEEK_BASE_URL   默认 https://api.deepseek.com（换成其他 OpenAI 兼容平台也行）
  DEEPSEEK_MODEL      默认 deepseek-chat
"""

import json
import os
import sys
import urllib.error
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def req(url, key, method="GET", payload=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    })
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    if not key:
        print("✗ 没有设置 DEEPSEEK_API_KEY", file=sys.stderr)
        return 2
    print(f"key 前缀: {key[:6]}…  长度: {len(key)}  结尾: …{key[-4:]}")
    if len(key) < 30:
        print("⚠ 这个 key 明显偏短。DeepSeek 的 key 通常 35 位左右，形如 sk-xxxxxxxx…")

    # 1) 查余额（deepseek 专有接口，换别家平台可能没有，失败不算致命）
    print("\n[1/2] 查询余额 …")
    try:
        info = req(f"{base}/user/balance", key)
        if info.get("is_available") is False:
            print("  ✗ 账户不可用（余额为 0？）")
        for b in info.get("balance_infos") or []:
            print(f"  ✓ 余额 {b.get('total_balance')} {b.get('currency')}"
                  f"（赠金 {b.get('granted_balance')} / 充值 {b.get('topped_up_balance')}）")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        print(f"  ✗ HTTP {e.code}: {detail}")
        if e.code in (401, 403):
            print("  → key 无效。注意要 sk- 开头的那串，不是账号 ID / 应用 ID。")
            return 2
    except Exception as e:
        print(f"  - 忽略（该接口不可用: {type(e).__name__}）")

    # 2) 实际发一次最小请求
    print(f"\n[2/2] 用 {model} 发一次最小请求 …")
    try:
        out = req(f"{base}/chat/completions", key, "POST", {
            "model": model,
            "messages": [{"role": "user", "content": "只回复两个字：可用"}],
            "max_tokens": 8,
        })
        reply = out["choices"][0]["message"]["content"].strip()
        used = (out.get("usage") or {}).get("total_tokens")
        print(f"  ✓ 模型回复: {reply!r}  (tokens={used})")
        print("\n结论：key 可用，可以跑全流程了。")
        return 0
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        print(f"  ✗ HTTP {e.code}: {detail}")
        if e.code == 402:
            print("  → 余额不足，去控制台充值。")
        elif e.code == 404:
            print(f"  → 模型名 {model!r} 在当前平台不存在，检查 DEEPSEEK_MODEL。")
        return 2
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
