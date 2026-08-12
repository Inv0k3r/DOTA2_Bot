import unittest
from unittest.mock import Mock, patch

import requests

import DOTA2


class OpenDotaRateLimitTest(unittest.TestCase):
    def setUp(self):
        DOTA2._opendota_retry_at = 0

    @patch("DOTA2.time.monotonic", return_value=100)
    @patch("DOTA2.requests.get")
    def test_429_starts_global_cooldown(self, get, _monotonic):
        response = Mock(status_code=429, headers={"Retry-After": "120"})
        error = requests.HTTPError(response=response)
        response.raise_for_status.side_effect = error
        get.return_value = response

        with self.assertRaises(DOTA2.DOTA2HTTPError):
            DOTA2._request_json("https://api.opendota.com/api/test", provider="OpenDota test")

        self.assertGreaterEqual(DOTA2._opendota_retry_at, 100 + 120)

    @patch("DOTA2.time.monotonic", return_value=101)
    @patch("DOTA2.requests.get")
    def test_cooldown_skips_network_request(self, get, _monotonic):
        DOTA2._opendota_retry_at = 200

        with self.assertRaisesRegex(DOTA2.DOTA2HTTPError, "cooldown"):
            DOTA2._request_json("https://api.opendota.com/api/test", provider="OpenDota test")

        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
