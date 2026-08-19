from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib import error

from godmod.twogis_api import TwoGisApiClient


class TwoGisApiClientTests(unittest.TestCase):
    def test_search_items_treats_item_not_found_meta_as_empty_result(self) -> None:
        payload = {
            "meta": {
                "code": 404,
                "error": {
                    "type": "itemNotFound",
                    "message": "Results not found",
                },
            }
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return json.dumps(payload).encode("utf-8")

        client = TwoGisApiClient("demo-key")
        with patch("godmod.twogis_api.request.urlopen", return_value=FakeResponse()):
            response = client.search_items({"q": "кофейня Тарко-Сале"})

        self.assertEqual(response["result"]["items"], [])
        self.assertEqual(response["meta"]["code"], 404)

    def test_search_items_treats_http_404_item_not_found_as_empty_result(self) -> None:
        payload = {
            "meta": {
                "code": 404,
                "error": {
                    "type": "itemNotFound",
                    "message": "Results not found",
                },
            }
        }
        body = json.dumps(payload).encode("utf-8")
        http_error = error.HTTPError(
            url="https://catalog.api.2gis.com/3.0/items",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(body),
        )

        client = TwoGisApiClient("demo-key")
        with patch("godmod.twogis_api.request.urlopen", side_effect=http_error):
            response = client.search_items({"q": "кофейня Тарко-Сале"})

        self.assertEqual(response["result"]["items"], [])
        self.assertEqual(response["meta"]["code"], 404)


if __name__ == "__main__":
    unittest.main()
