"""Explicit localhost development server using the normal city app and /route.

The existing stop-ID API is also available for regression comparison. No source
download, fallback, production listener or external-service stub is installed.
"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("bus-gtfs-dir", "subway-published", "subway-review", "municipal-review"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--expected-service-date", required=True)
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    os.environ.update(APP_CITY="sendai", SENDAI_REVIEWED_COORDINATES="1",
        SENDAI_GTFS_DIR=str(args.bus_gtfs_dir),
        SENDAI_GTFS_EXPECTED_SERVICE_DATE=args.expected_service_date,
        SENDAI_SUBWAY_PUBLISHED=str(args.subway_published),
        SENDAI_SUBWAY_REVIEW=str(args.subway_review),
        SENDAI_MUNICIPAL_REVIEW=str(args.municipal_review))
    from app.app_factory import create_app
    from app.sendai_practical_routes import create_sendai_practical_test_app
    from transit_timetable_choices import NetworkSearchParameters
    app = create_app("development")
    @app.on_event("startup")
    async def add_regression_entry():
        regression = create_sendai_practical_test_app(app.state.sendai_reviewed_network,
            environment="test", parameters=NetworkSearchParameters(max_candidates=1,
                max_boardings=3, max_travel_minutes=180),
            operating_period=app.state.sendai_operating_period)
        app.include_router(regression.router)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
