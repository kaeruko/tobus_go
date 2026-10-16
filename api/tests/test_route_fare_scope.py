import unittest

from route_engine import RouteInputError
from route_fare_scope import search_with_fare_scope


class _Engine:
    def __init__(self):
        self.requests = []

    def search(self, request):
        self.requests.append(request)
        return "result"


class RouteFareScopeTest(unittest.TestCase):
    def test_normal_preserves_existing_engine_and_request(self):
        engine = _Engine()
        request = object()
        self.assertEqual(search_with_fare_scope(engine, request, "normal"), "result")
        self.assertEqual(engine.requests, [request])

    def test_explicit_policy_uses_city_adapter_scope(self):
        base, scoped = _Engine(), _Engine()
        selected = []

        def select(policy):
            selected.append(policy)
            return scoped

        base.for_fare_policy = select
        request = object()
        search_with_fare_scope(base, request, "sendai_fureai_pass")
        self.assertEqual(selected, ["sendai_fureai_pass"])
        self.assertEqual(scoped.requests, [request])
        self.assertEqual(base.requests, [])

    def test_unsupported_scope_does_not_run_normal_search(self):
        engine = _Engine()
        with self.assertRaisesRegex(RouteInputError, "unsupported"):
            search_with_fare_scope(engine, object(), "unknown")
        self.assertEqual(engine.requests, [])

    def test_original_failure_is_propagated_without_another_engine(self):
        engine = _Engine()
        original = RuntimeError("bad installed feed")

        def select(policy):
            raise original

        engine.for_fare_policy = select
        with self.assertRaises(RuntimeError) as caught:
            search_with_fare_scope(engine, object(), "sendai_fureai_pass")
        self.assertIs(caught.exception, original)
        self.assertEqual(engine.requests, [])


if __name__ == "__main__":
    unittest.main()
