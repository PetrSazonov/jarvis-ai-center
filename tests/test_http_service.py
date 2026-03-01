import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from services.http_service import ExternalAPIError, request_json


class HTTPServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_maps_to_external_error(self):
        with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=httpx.TimeoutException("timeout"))):
            with self.assertRaises(ExternalAPIError) as ctx:
                await request_json(service="x", method="GET", url="http://localhost", retries=0)
        self.assertEqual(ctx.exception.kind, "timeout")

    async def test_429_maps_to_rate_limit(self):
        response = Mock()
        response.status_code = 429
        response.json.return_value = {}

        with patch("httpx.AsyncClient.request", new=AsyncMock(return_value=response)):
            with self.assertRaises(ExternalAPIError) as ctx:
                await request_json(service="x", method="GET", url="http://localhost", retries=0)
        self.assertEqual(ctx.exception.kind, "rate_limit")


if __name__ == "__main__":
    unittest.main()
