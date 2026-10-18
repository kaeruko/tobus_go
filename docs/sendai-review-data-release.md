# Sendai reviewed-source release staging (no AWS changes)

This procedure prepares a **local** reviewed bundle for the already implemented
Sendai municipal bus + subway / `sendai_fureai_pass` route scope. It does not
approve new routes or dates, upload data, deploy Lambda, or submit either app.

## Sources and current review boundary

The official Sendai municipal bus GTFS-JP source is published through ODPT:

- City/operator announcement:
  https://www.kotsu.city.sendai.jp/bus_news/gtfs-jp_gtfs_data/
- Official ODPT catalog:
  https://ckan.odpt.org/dataset/sendai_municipal_bus_realtime_information
- Authenticated `date=current` endpoint used by the existing fetcher:
  `https://api.odpt.org/api/v4/files/odpt/SendaiMunicipal/bus_realtime_information.zip?date=current`

The ODPT consumer key must be supplied through `ODPT_API_TOKEN` in the
operator's local environment, never committed or pasted into chat/logs.
The historical reviewed municipal scope is bounded at **2026-11-30**;
special/unreviewed service days remain excluded. Nothing here approves
2026-12-01 or later. As of 2026-10-18 a new official ZIP and SHA covering
December have **not been independently verified** in this work. Do not infer
that an updated resource is absent; verify with ODPT credentials and sources.

## 1. Fetch an expressly chosen new official source

Use a new version directory. The fetcher checks the entire ZIP, exact manifest
and an active GTFS service on the requested service date. `date=current` is not
an implicit freshness or post-November approval.

```powershell
# ODPT_API_TOKEN must already be set privately in this PowerShell process.
python scripts/fetch_sendai_gtfs.py `
  --output C:\data\sendai\new-approved-source `
  --expected-service-date 2026-12-01
```

For more control, supply an exact official `--source-url` and a previously
verified `--expected-sha256`. **Do not** fall back to the October/November
ZIP if the December feed is not available or valid.

A valid source ZIP is only the first gate. Independently review the full
municipal bus trip patterns, in-city free coverage, exact stop/sequence
witnesses, transfers, actual subway published clocks, operating-day exclusions,
and evidence. Regenerate/approve a new municipal review bound to the **new**
GTFS SHA. Do not just extend the JSON end date or copy an old review under
a new version. Keep test fixtures distinct from approved deployment inputs.

## 2. Stage the approved GTFS and three reviewed sources together

After completing an independent review, run the offline preparer using its
approved evidence files. The example paths below are placeholders.

```powershell
python scripts/prepare_sendai_reviewed_bundle.py `
  --bus-gtfs-dir C:\data\sendai\new-approved-source `
  --municipal-review C:\reviews\approved-municipal.json `
  --subway-published C:\reviews\approved-subway-published.json `
  --subway-review C:\reviews\approved-subway-review.json `
  --expected-service-date 2026-12-01 `
  --target-query-date 2026-12-01 `
  --output-dir C:\data\sendai\release-staged
```

The preparer:

1. Re-loads and validates the original GTFS ZIP, all raw file hashes and its
   exact expected service date.
2. Builds the *same* reviewed municipal/subway network and verifies the
   operating period includes the explicitly requested query date. An unreviewed
   date fails, even if it appears in a generic GTFS calendar.
3. Copies the validated GTFS input and exactly the supplied reviewed JSONs
   into a new, non-overwriting directory.
4. Writes `sendai_review_manifest.json` binding the official GTFS source
   SHA-256, reviewed query bounds and each review JSON byte's SHA-256.
5. Verifies the binding again. It does not upload any bytes.

The resulting directory retains the existing `sendai_gtfs_manifest.json`
and `sendai_gtfs_source.zip` and adds these exact file names:

- `sendai_municipal_review.json`
- `sendai_subway_published.json`
- `sendai_subway_review.json`
- `sendai_review_manifest.json`

Keep the source files outside the repository and do not commit credentials,
live GTFS archives, or oversized deployment artifacts.

## 3. Isolated Lambda wiring / verification boundary

The existing city-owned S3 GTFS ZIP contains the *whole staged directory*.
The existing `materialize_city_gtfs_bundle` validates its outer SHA before
extraction. On `APP_CITY=sendai` with
`SENDAI_REVIEWED_COORDINATES=1`, Lambda additionally loads only the three
fixed reviewed JSONs in that same extracted bundle, checks their SHA/version
binding, and then builds the existing reviewed network. Loose
`SENDAI_MUNICIPAL_REVIEW`/`SENDAI_SUBWAY_PUBLISHED`/
`SENDAI_SUBWAY_REVIEW` environment paths are **not** a Lambda fallback.

For a **separately authorized** Sendai deployment, the city-owned Lambda
configuration and S3 object must agree on:

- `SENDAI_GTFS_BUNDLE_S3_BUCKET`, `SENDAI_GTFS_BUNDLE_S3_KEY`
- `SENDAI_GTFS_BUNDLE_SHA256` (outer S3 ZIP)
- `SENDAI_GTFS_DIR` (fresh private extraction directory)
- `SENDAI_GTFS_EXPECTED_SERVICE_DATE` (exact source manifest date)
- `SENDAI_REVIEWED_COORDINATES=1` (explicit operator selection)
- `APP_CITY=sendai` and the independent Sendai API/Places key

The existing `bootstrap_city_api.ps1` packages any approved GTFS directory,
but **does not turn on the reviewed feature**. `deploy_api.ps1` deploys code
only and does not silently rotate an S3 feed or Lambda variables. Therefore
do not treat either command as a complete reviewed-source migration.
First inspect isolated city infrastructure, review S3 upload/version and
Lambda configuration together, and obtain explicit authorization for the
AWS change. Never re-use the Tokyo bucket, Lambda, secret, or public URL.

For a local, no-AWS test:

```powershell
cd api
python -m unittest tests.test_sendai_review_bundle `
  tests.test_city_gtfs_bundle tests.test_city_runtime_warm_start -v
```

Then independently run existing reviewed real-data/oracle tests against the
exact newly approved feed and the current production-mode Lambda path.
Only an actual approved city Lambda deployment plus a real `/healthz`,
`/route`, live Places and Android/iOS test can establish external end-to-end
release readiness. No Google fixture proves the live upstream contract.

## Failure modes intentionally not bypassed

- Missing or changed reviewed JSON, cross-version bus data, invalid finite
  service dates, unapproved municipal/free scope, or different source hashes:
  **fail**, do not fall back.
- No official GTFS for December: **do not** extend November service.
- Normal fare search: unchanged bus-only backend; no invented subway fare.
- No qualifying ふれあい乗車証 held/selected or missing explicit transfer-model
  consent: no free-pass scope.
- Unsupported Miyagi Kotsu, physical walking route verification, and special
  timetables: not silently assumed supported.
