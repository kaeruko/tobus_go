import os
import unittest
from unittest.mock import patch

from app.services.train_realtime import _fetch_bytes


class _FakeResponse:
    status_code = 200
    content = b"payload"


class _FakeAsyncClient:
    created_kwargs = None

    def __init__(self, **kwargs):
        type(self).created_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params):
        return _FakeResponse()


class TrainRealtimeHttpTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_follows_odpt_file_redirects(self):
        with patch.dict(os.environ, {"ODPT_API_TOKEN": "test-token"}, clear=False):
            with patch(
                "app.services.train_realtime.httpx.AsyncClient",
                _FakeAsyncClient,
            ):
                content = await _fetch_bytes(
                    "https://example.test/train.zip",
                    timeout_seconds=30.0,
                )

        self.assertEqual(content, b"payload")
        self.assertEqual(_FakeAsyncClient.created_kwargs["timeout"], 30.0)
        self.assertIs(_FakeAsyncClient.created_kwargs["follow_redirects"], True)


if __name__ == "__main__":
    unittest.main()
