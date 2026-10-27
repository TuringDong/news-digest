"""Prepare early, then submit mail at the requested China-local minute."""
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')


def seconds_until(value, now=None):
    if not value:
        return 0
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('发送时间必须为 HH:MM，例如 08:00')
    now = now or datetime.now(TZ)
    hour, minute = map(int, value.split(':'))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    seconds = max(0, (target - now).total_seconds())
    if seconds > 25 * 60:
        raise ValueError('发送时间超过 25 分钟后的等待上限，请在临近发送时启动')
    return seconds


def wait_until(value):
    remaining = seconds_until(value)
    if remaining:
        print(f'稿件已准备好，等待北京时间 {value} 发送（约 {int(remaining)} 秒）。', flush=True)
    while remaining > 0:
        time.sleep(min(30, remaining))
        remaining = seconds_until(value)
