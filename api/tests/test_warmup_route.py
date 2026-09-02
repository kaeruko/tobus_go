import asyncio
import os
import unittest
from unittest.mock import patch

from app.app_factory import create_app


class WarmupRouteTest(unittest.TestCase):
    def test_warmup_route_reports_ready_city(self):
        with patch.dict(os.environ, {"APP_CITY": "sendai"}, clear=False):
            app = create_app("lambda")

        routes = [
            route
            for route in app.routes
            if getattr(route, "path", None) == "/warmup"
        ]
        self.assertEqual(len(routes), 1)
        self.assertIn("GET", routes[0].methods)
        self.assertEqual(
            asyncio.run(routes[0].endpoint()),
            {"status": "ready", "city": "sendai"},
        )


if __name__ == "__main__":
    unittest.main()
