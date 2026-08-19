from __future__ import annotations

from http.client import IncompleteRead
import unittest
from unittest.mock import patch

from godmod.vk_api import VkApiClient, VkApiError


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return b'{"response":{"items":[]}}'


class VkApiClientTests(unittest.TestCase):
    def test_call_wraps_timeout_as_retryable_network_error(self) -> None:
        client = VkApiClient("vk-token")

        with patch("godmod.vk_api.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(VkApiError) as ctx:
                client.call("newsfeed.search", {"q": "маникюр"})

        self.assertIn("Network error", str(ctx.exception))
        self.assertTrue(ctx.exception.retryable)

    def test_call_wraps_incomplete_read_as_retryable_network_error(self) -> None:
        client = VkApiClient("vk-token")

        with patch("godmod.vk_api.request.urlopen", side_effect=IncompleteRead(b"{}", 10)):
            with self.assertRaises(VkApiError) as ctx:
                client.call("newsfeed.search", {"q": "маникюр"})

        self.assertIn("Network error", str(ctx.exception))
        self.assertTrue(ctx.exception.retryable)

    def test_call_with_retry_retries_retryable_network_error(self) -> None:
        client = VkApiClient("vk-token")

        with patch(
            "godmod.vk_api.request.urlopen",
            side_effect=[TimeoutError("read timed out"), _FakeResponse()],
        ):
            response = client.call_with_retry("newsfeed.search", {"q": "маникюр"}, retries=1, retry_delay=0)

        self.assertEqual(response, {"items": []})


if __name__ == "__main__":
    unittest.main()
