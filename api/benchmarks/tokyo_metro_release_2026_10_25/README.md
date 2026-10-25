# Tokyo Metro fixed release corpus

This directory is the Phase 2 regression corpus defined by
`docs/tokyo-metro-release-roadmap.md`. It does not contain authenticated ODPT
source files, API credentials, or inferred timetable data.

`corpus.json` freezes the seven transport scopes, both objectives, candidate
limits 1 through 5, and ordinary/estimated-transfer modes. Supplemental cases
cover weekend, public holiday, last train, date crossing, reviewed transfers in
both directions, the prior 75,316-pop case (unreachable without estimated
transfers), and a walking-access probe. Synthetic unit-test references cover missed
connections and direction/closure exceptions without inventing production
station data.

Ordinary and estimated searches are run independently. The runner passes the
opt-in to the graph selector before exact enumeration; it never searches the
larger graph and filters candidates afterward. It also fails if a normal result
contains an estimated edge or if toggling the option changes a Toei-only
candidate.

## Inputs

Use the accepted official Metro archive, version `20261008`, valid 2026-09-19
through 2027-03-12. Its required SHA-256 is recorded in `corpus.json`. The
runner verifies the archive hash and the feed version/dates and refuses to use
a substitute. All other source paths are explicit and required.

Example from the repository root (PowerShell):

```powershell
api\.venv-route\Scripts\python.exe `
  api\benchmarks\tokyo_metro_release_2026_10_25\run.py `
  --app-data C:\path\to\api\data\app_data.pkl `
  --bus-gtfs C:\path\to\api\data\ToeiBus-GTFS `
  --metro-archive C:\path\to\TokyoMetro-Train-GTFS.zip `
  --metro-gtfs C:\path\to\extracted `
  --metro-stations C:\path\to\odpt_Station_TokyoMetro.json `
  --metro-railways C:\path\to\odpt_Railway_TokyoMetro.json `
  --toei-stations C:\path\to\api\data\odpt_Station.json `
  --transfer-manifest api\config\tokyo_metro_reviewed_transfers.json `
  --output .cache\pr253\phase2-observed.json
```

After a reviewed baseline is committed, pass it with `--baseline` to compare
candidate count, order-sensitive digest, concrete run/trip identity, stop
order, departure/arrival times, and expected failures. Timing, pop count, queue size and retained labels
are recorded as measurements but are not treated as deterministic equality
fields.

The initial reviewed-format output is `baseline_windows_20261025.json.gz`; its
measurement summary and current limitations are in [RESULTS.md](RESULTS.md).

Phase 2 remains in progress until the generated baseline has been reviewed,
committed, and the pre-Metro Toei-only reference has been compared. Creating
the corpus and runner alone does not satisfy the release gate.
