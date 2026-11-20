import unittest
from unittest.mock import patch
import requests

from apexprime.notify import TelegramNotifier


class NotifyTests(unittest.TestCase):
    def test_without_credentials_is_noop(self):
        self.assertFalse(TelegramNotifier("", "").send("hello"))

    @patch("apexprime.notify.requests.post", side_effect=requests.Timeout("timeout"))
    def test_network_failure_does_not_raise_or_leak_token(self, mocked_post):
        notifier = TelegramNotifier("secret-token", "-100123")
        self.assertFalse(notifier.send("hello"))
        mocked_post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
