from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one Phase 7 patch target in {path}, found {count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_gtfs_route_backend() -> None:
    path = ROOT / "api" / "gtfs_route_backend.py"
    replace_once(
        path,
        "from datetime import datetime\n",
        "from datetime import datetime, timedelta\n",
    )
    replace_once(
        path,
        """            transit_departure = departure.replace(\n                hour=((departure.hour * 60 + departure.minute + origin_walk) // 60) % 24,\n                minute=(departure.minute + origin_walk) % 60,\n            )\n""",
        """            transit_departure = departure + timedelta(minutes=origin_walk)\n""",
    )


def patch_tokyo_bus_location() -> None:
    path = ROOT / "api" / "app" / "routes.py"
    old = """        tm = app.state.TM\n        if tm:\n            from app.runtime import refresh_realtime_bus_positions\n\n            await refresh_realtime_bus_positions(\n                tm,\n                max_age_seconds=0 if force_refresh else 45,\n            )\n        if not tm or not tm.latest_bus_positions:\n            _busloc_log({**base, \"ok\": False, \"reason\": \"REALTIME_UNAVAILABLE\"})\n            raise HTTPException(\n                503,\n                detail={\n                    \"code\": \"bus_realtime_unavailable\",\n                    \"message\": \"Realtime bus positions are not available\",\n                },\n            )\n\n        candidates_all = tm.latest_bus_positions\n"""
    new = """        tm = app.state.TM\n        provider = getattr(app.state, \"realtime_provider\", None)\n        if provider is None:\n            _busloc_log({**base, \"ok\": False, \"reason\": \"REALTIME_PROVIDER_UNAVAILABLE\"})\n            raise HTTPException(\n                503,\n                detail={\n                    \"code\": \"bus_realtime_unavailable\",\n                    \"message\": \"Realtime bus positions are not available\",\n                    \"diagnostic\": \"Tokyo RealtimeProvider is not initialized\",\n                },\n            )\n        try:\n            candidates_all = list(\n                await provider.vehicle_positions(force_refresh=force_refresh)\n            )\n        except RuntimeError as error:\n            _busloc_log({\n                **base,\n                \"ok\": False,\n                \"reason\": \"REALTIME_UNAVAILABLE\",\n                \"diagnostic\": str(error),\n            })\n            raise HTTPException(\n                503,\n                detail={\n                    \"code\": \"bus_realtime_unavailable\",\n                    \"message\": \"Realtime bus positions are not available\",\n                    \"diagnostic\": str(error),\n                },\n            ) from error\n        if not candidates_all:\n            _busloc_log({**base, \"ok\": False, \"reason\": \"REALTIME_UNAVAILABLE\"})\n            raise HTTPException(\n                503,\n                detail={\n                    \"code\": \"bus_realtime_unavailable\",\n                    \"message\": \"Realtime bus positions are not available\",\n                },\n            )\n\n"""
    replace_once(path, old, new)


def main() -> None:
    patch_gtfs_route_backend()
    patch_tokyo_bus_location()


if __name__ == "__main__":
    main()
