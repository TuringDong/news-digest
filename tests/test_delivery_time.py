from datetime import datetime
import unittest
from delivery_time import TZ, seconds_until


class DeliveryTimeTests(unittest.TestCase):
    def test_waits_from_0745_until_0800(self):
        self.assertEqual(seconds_until('08:00', datetime(2026,10,28,7,45,tzinfo=TZ)), 900)

    def test_at_deadline_and_late_retry_send_immediately(self):
        self.assertEqual(seconds_until('08:00', datetime(2026,10,28,8,0,tzinfo=TZ)), 0)
        self.assertEqual(seconds_until('08:00', datetime(2026,10,28,8,5,tzinfo=TZ)), 0)

    def test_empty_is_immediate(self):
        self.assertEqual(seconds_until(''), 0)

    def test_invalid_and_unbounded_wait_are_rejected(self):
        for value in ['8:00','24:00','08:60','x']:
            with self.assertRaises(ValueError):
                seconds_until(value)
        with self.assertRaises(ValueError):
            seconds_until('08:00', datetime(2026,10,28,7,0,tzinfo=TZ))
