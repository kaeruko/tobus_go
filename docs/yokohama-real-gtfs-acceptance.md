## Real GTFS bus/subway acceptance (read-only, not public approval)

Source: `scripts/verify_yokohama_municipal_real_gtfs.py`. This is the
first-stage **two-feed** acceptance probe for #241, separate from the existing
bus-only `smoke_yokohama_real_gtfs.py`. It reads only installed manifests,
coverage, reviewed links and raw GTFS; it never downloads data or writes files.

Prerequisites:
1. Local bus GTFS with its validated pinned bus manifest, and its existing
   bus-specific review coverage; no automatic approval of additional bus routes.
2. ODPT subway GTFS pinned to the reviewed 20251226 edition, with manifest and
   matching file hashes. A login/consumer key may be required **for obtaining
   the data separately**, but the acceptance script itself never accesses one.
3. An *independently reviewed*, version-locked walking-link JSON
   (`YOKOHAMA_REVIEWED_TRANSFERS_PATH` format) with exact namespaced bus-pole
   and subway-station IDs, a measured route distance, a conservative walking
   duration, and official evidence. **An official page merely listing a nearby
   bus stop does not itself prove a specific pole-to-entrance pedestrian path.**
4. Exact origin/destination stop IDs in opposite feeds and a scheduled start
   clock for which that exact link should produce a route. Do not substitute
   same-named stops for IDs.

Example argument shape, with deliberate placeholders (not executable test data):

```text
python scripts/verify_yokohama_municipal_real_gtfs.py
  --bus-gtfs-dir <existing-bus-gtfs-dir>
  --bus-coverage <existing-reviewed-bus-coverage.json>
  --subway-gtfs-dir <existing-subway-gtfs-dir>
  --reviewed-links <verified-transfer-links.json>
  --service-date YYYY-MM-DD --start-time HH:MM
  --origin-stop-id yokohama_bus:<real-origin-id>
  --destination-stop-id yokohama_subway:<real-destination-id>
  --bus-transfer-stop-id yokohama_bus:<reviewed-pole-id>
  --subway-transfer-stop-id yokohama_subway:<reviewed-station-id>
```

The verifier must find and inspect a reviewed transfer for BOTH welfare and
senior passes. It compares every emitted bus and rail trip, GTFS stop sequence,
times, active service, exact walking link, ride order and extra-payment
quotations. Failures stop immediately with diagnostics. No synthetic proximity
transfer or fallback source is enabled.

A PASS is only **same-feed source consistency**, not independent verification of
official timetable accuracy, physical walking safety, accessibility, operator
GTFS redistribution rights, or comprehensive all-city search. Separate
independent acceptance should cross-check the exact physical pole-to-entrance
walk, any stairs/lifts/road crossings, and representative OD timetable against
the operator's own map/timetable.

As of 2026-10-14, the official site confirms that Sakuragicho subway station
lists Sakuragicho-ekimae among nearby municipal-bus stops:
https://navi.hamabus.city.yokohama.lg.jp/koutuu/smart/detail/Station?id=00002909
and the municipal operator provides a directional bus-bay map:
https://navi.hamabus.city.yokohama.lg.jp/koutuu/pc/diagram/BusAboardMap?stCode=00090408
These are useful **manual investigation evidence**, not approval of any exact
GTFS stop ID, measured walking distance or minutes. No production link file
was fabricated from these documents.

ODPT catalog lists the 20251226 subway edition as valid through 2026-12-31;
the source is registration-based and subject to the Basic License and
Specific Terms of Use:
https://ckan.odpt.org/dataset/yokohama_municipal_train


### Before approving any walking link

The existing read-only triage command extracts candidate feed stop IDs without
creating a public transfer link. Run only against installed, licensed GTFS:

```text
python scripts/audit_yokohama_transfer_candidates.py
  --bus-gtfs-dir <existing-bus-gtfs-dir>
  --bus-coverage <existing-reviewed-bus-coverage.json>
  --subway-gtfs-dir <existing-subway-gtfs-dir>
  --service-date YYYY-MM-DD
  --radius-m 300 --limit 40
  --include-bus-pole-fields
```

Its report is a **candidate shortlist**. Source GTFS `platform_code`,
`stop_code` and stop names must not be reinterpreted as a verified official
bay number. Human review must associate the exact bus pole and subway entrance
with the operator map, record feasible pedestrian geometry/estimated time and
any accessibility limits, and pin both feed versions. Only after that review
may a link be written to a local `YOKOHAMA_REVIEWED_TRANSFERS_PATH` file.

The ODPT Public Transportation Open Data Basic License (Article 8) generally
prohibits redistribution of reusable copies of the original feed or reversible
derivative GTFS data, absent permission or applicable specific exceptions.
Do **not** commit the raw GTFS, manifest containing licensed data extracts,
or large GTFS-derived dumps to public GitHub merely to run this check.
Run it on an authorized local installation and share only the small diagnostic
summary consistent with the license. Check applicable Specific Terms of Use.
Official license: https://developer.odpt.org/terms/data_basic_license.html
