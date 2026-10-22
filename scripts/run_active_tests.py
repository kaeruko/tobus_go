"""Run Tokyo/shared tests without collecting the pending Sendai suites."""
from __future__ import annotations

import argparse
import importlib
import importlib.abc
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PENDING_PYTHON = {"test_city_gtfs_bundle.py", "test_city_runtime_warm_start.py"}
PENDING_FLUTTER = {
    "route_only_active_trip_page_test.dart",
    "route_only_detail_page_test.dart",
}


def selected_tests(kind: str) -> list[Path]:
    if kind not in ("python", "flutter"):
        raise ValueError(f"Unsupported test kind: {kind!r}")
    if kind == "python":
        return sorted(
            path for path in (ROOT / "api" / "tests").glob("test_*.py")
            if not path.name.startswith("test_sendai")
            and path.name not in PENDING_PYTHON
        )
    return sorted(
        path for path in (ROOT / "test").rglob("*_test.dart")
        if not path.name.startswith("sendai")
        and path.name not in PENDING_FLUTTER
    )


class PendingCityImportGuard(importlib.abc.MetaPathFinder):
    """A shared test must never pull the pending implementation back into CI."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname.rsplit(".", 1)[-1].startswith(("sendai", "test_sendai")):
            raise ImportError(
                f"Pending Sendai module imported by active tests: {fullname}. "
                "See docs/sendai-pending.md."
            )
        return None


def run_python(paths: list[Path]) -> int:
    os.chdir(ROOT / "api")
    sys.path[:0] = [str(ROOT / "api"), str(ROOT / "api" / "tests")]
    sys.meta_path.insert(0, PendingCityImportGuard())
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for path in paths:
        # Import explicitly so an import error stops collection with its
        # original traceback rather than continuing with other test modules.
        module = importlib.import_module(f"tests.{path.stem}")
        suite.addTests(loader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("python", "flutter"))
    parser.add_argument("--list", action="store_true", help="List without importing or running tests")
    args = parser.parse_args()
    paths = selected_tests(args.kind)
    if not paths:
        raise RuntimeError(f"No active {args.kind} tests found under {ROOT}")
    if args.list:
        print("\n".join(str(path.relative_to(ROOT)) for path in paths))
        return 0
    if args.kind == "python":
        return run_python(paths)
    subprocess.run(
        ["flutter", "test", "--fail-fast", *[str(path.relative_to(ROOT)) for path in paths]],
        cwd=ROOT,
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
