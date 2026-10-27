import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
import mailer
import notify_failure


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.now = datetime.now(run.TZ)

    def tearDown(self):
        self.temp.cleanup()

    def test_only_valid_receipt_suppresses_delivery(self):
        marker = self.base / 'receipt.sent'
        self.assertFalse(run.sent_today(marker, self.now))
        cases = [('', False), ('test\n', False), ('garbage', False),
                 (self.now.replace(tzinfo=None).isoformat(), False),
                 ((self.now - timedelta(days=1)).isoformat(), False),
                 ((self.now + timedelta(hours=1)).isoformat(), False),
                 (self.now.isoformat(), True)]
        for value, expected in cases:
            with self.subTest(value=value):
                marker.write_text(value, encoding='utf-8')
                self.assertEqual(run.sent_today(marker, self.now), expected)

    def test_send_replaces_test_marker_and_next_run_skips(self):
        outbox = self.base / 'outbox'
        outbox.mkdir()
        marker = outbox / f'{self.now:%Y-%m-%d}.sent'
        marker.write_text('test', encoding='utf-8')
        draft = self.base / 'draft.json'
        draft.write_text(json.dumps({'sections': []}), encoding='utf-8')
        with patch.object(run, 'BASE', self.base), patch.object(run.os, 'chdir'), \
             patch.object(sys, 'argv', ['run.py', '--digest', str(draft)]), \
             patch('render.render_html', return_value='<p>test</p>'), \
             patch('render.render_text', return_value='test'), \
             patch.object(mailer, 'send', return_value=['test@example.invalid']) as send:
            self.assertEqual(run.main(), 0)
            self.assertTrue(run.sent_today(marker, datetime.now(run.TZ)))
            self.assertEqual(run.main(), 0)
            send.assert_called_once()

    def test_failed_send_does_not_create_receipt(self):
        draft = self.base / 'draft.json'
        draft.write_text(json.dumps({'sections': []}), encoding='utf-8')
        with patch.object(run, 'BASE', self.base), patch.object(run.os, 'chdir'), \
             patch.object(sys, 'argv', ['run.py', '--digest', str(draft)]), \
             patch('render.render_html', return_value='<p>test</p>'), \
             patch('render.render_text', return_value='test'), \
             patch.object(mailer, 'send', side_effect=mailer.MailError('test failure')):
            self.assertEqual(run.main(), 5)
            self.assertFalse(list((self.base / 'outbox').glob('*.sent')))

    def test_dry_run_never_sends_or_creates_receipt(self):
        draft = self.base / 'draft.json'
        draft.write_text(json.dumps({'sections': []}), encoding='utf-8')
        with patch.object(run, 'BASE', self.base), patch.object(run.os, 'chdir'), \
             patch.object(sys, 'argv', ['run.py', '--digest', str(draft), '--dry-run']), \
             patch('render.render_html', return_value='<p>test</p>'), \
             patch('render.render_text', return_value='test'), \
             patch.object(mailer, 'send') as send:
            self.assertEqual(run.main(), 0)
            send.assert_not_called()
            self.assertFalse(list((self.base / 'outbox').glob('*.sent')))

    def test_archive_failure_alert_does_not_claim_mail_was_unsent(self):
        subject, html, text = notify_failure.build(
            {'ok': True, 'stage': '完成'}, None, False)
        self.assertIn('工作流异常', subject)
        self.assertIn('邮件可能已提交 SMTP', text)
        self.assertNotIn('今天的日报没发出去', html)


if __name__ == '__main__':
    unittest.main()
