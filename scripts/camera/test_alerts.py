"""Notification policy tests; no network requests or real messages."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import alerts

class AlertPolicyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.root_patch = patch.object(alerts, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        (self.root / 'ntfy.json').write_text('{}')
        self.now = datetime(2026, 11, 4, 14, 20, tzinfo=alerts.ZONE)
        self.current = self.now.replace(hour=12, minute=49)
        self.old = self.current.replace(day=3)

    def state(self):
        return alerts.read_json(self.root / 'notification-state.json')

    def test_no_new_alert_or_network_before_retry(self):
        with patch.object(alerts, 'published_photo') as fetch, patch.object(alerts, 'send') as send:
            alerts.check(now=self.now.replace(hour=13))
            fetch.assert_not_called()
            send.assert_not_called()

    def test_stale_photo_alert_is_deduplicated_across_days(self):
        with patch.object(alerts, 'published_photo', return_value=self.old), patch.object(alerts, 'send') as send:
            alerts.check(now=self.now)
            alerts.check(now=self.now)
            alerts.check(now=self.now.replace(day=5))
            self.assertEqual(send.call_count, 1)
            self.assertTrue(self.state()['active'])

    def test_recovery_sent_once(self):
        with patch.object(alerts, 'published_photo', return_value=self.old), patch.object(alerts, 'send'):
            alerts.check(now=self.now)
        with patch.object(alerts, 'published_photo', return_value=self.current), patch.object(alerts, 'send') as send:
            alerts.check(now=self.now)
            alerts.check(now=self.now)
            self.assertEqual(send.call_count, 1)
            self.assertTrue(send.call_args.kwargs['recovery'])
            self.assertFalse(self.state()['active'])

    def test_failed_notification_can_be_retried(self):
        with patch.object(alerts, 'published_photo', return_value=self.old), patch.object(alerts, 'send', side_effect=OSError):
            with self.assertRaises(OSError):
                alerts.check(now=self.now)
        with patch.object(alerts, 'published_photo', return_value=self.old), patch.object(alerts, 'send') as send:
            alerts.check(now=self.now)
            send.assert_called_once()

    def test_healthy_photo_does_not_alert_for_unrelated_job_failure(self):
        with patch.object(alerts, 'published_photo', return_value=self.current), patch.object(alerts, 'send') as send:
            alerts.check(stage='download', now=self.now)
            send.assert_not_called()

    def test_failed_public_image_check_alerts(self):
        with patch.object(alerts, 'published_photo', side_effect=OSError), patch.object(alerts, 'send') as send:
            alerts.check(now=self.now)
            send.assert_called_once()

    def test_future_photo_does_not_count_as_healthy(self):
        with patch.object(alerts, 'published_photo', return_value=self.current.replace(day=5)), patch.object(alerts, 'send') as send:
            alerts.check(now=self.now)
            send.assert_called_once()

    def test_parser_ignores_unrelated_dates_and_images(self):
        parser = alerts.LatestPhoto()
        parser.feed('<time datetime="wrong"></time><img src="wrong.jpg">'
                    '<div class="camera-latest"><a><img src="today.jpg"></a>'
                    '<p><time datetime="2026-11-04T12:49:00-07:00">Today</time></p></div>'
                    '<time datetime="also-wrong"></time>')
        self.assertEqual(parser.image, 'today.jpg')
        self.assertEqual(parser.capture, '2026-11-04T12:49:00-07:00')

if __name__ == '__main__':
    unittest.main()
