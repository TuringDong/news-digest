"""Send one clearly labelled cloud-scheduling acceptance message."""
import argparse
from datetime import datetime
from delivery_time import TZ, wait_until
import mailer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--send-at', required=True)
    args = parser.parse_args()
    wait_until(args.send_at)
    now = datetime.now(TZ).isoformat(timespec='seconds')
    subject = '【云端定时验收】日报调度测试'
    text = (f'这是一封云端定时验收邮件，不是重复的日报。\n'
            f'计划发送时间：北京时间 {args.send_at}\n实际提交 SMTP 时间：{now}\n'
            '流程：Cloudflare 定时事件 → GitHub Actions → 等待指定时间 → SMTP。\n'
            '全程在云端执行，不依赖你的电脑开机或 VPN。')
    mailer.send(subject, '<div style="font:16px/1.8 sans-serif;color:#20324d">' + text.replace('\n', '<br>') + '</div>', text)
    print(f'Cloud scheduling acceptance message submitted at {now}', flush=True)


if __name__ == '__main__':
    main()
