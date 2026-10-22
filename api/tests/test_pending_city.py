import os
import unittest
from unittest.mock import patch

from app.app_factory import create_app


class PendingCityTest(unittest.TestCase):
    def test_sendai_stops_before_runtime_import_even_with_old_opt_in(self):
        for mode in ("local", "lambda"):
            with self.subTest(mode=mode), patch.dict(os.environ, {
                "APP_CITY": "sendai", "SENDAI_REVIEWED_COORDINATES": "1",
            }):
                with self.assertRaisesRegex(RuntimeError, 'APP_CITY="sendai" is pending'):
                    create_app(mode)

    def test_pending_city_value_is_still_exact(self):
        for city in ("Sendai", " sendai", "sendai "):
            with self.subTest(city=city), patch.dict(os.environ, {"APP_CITY": city}):
                with self.assertRaisesRegex(RuntimeError, "Unsupported APP_CITY"):
                    create_app("local")
