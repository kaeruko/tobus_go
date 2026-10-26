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

The holiday case is Monday 2026-10-12 (Sports Day), not a Sunday carrying a
holiday-shaped label. The runner requires it to be a Japanese public holiday,
then checks the accepted Metro GTFS `calendar_dates.txt` removes weekday
service `0` and adds weekend/holiday service `1` for that date.

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

Pass the reviewed baseline with `--baseline` to compare
candidate count, order-sensitive digest, concrete run/trip identity, stop
order, departure/arrival times, and expected failures. Timing, pop count, queue size and retained labels
are recorded as measurements but are not treated as deterministic equality
fields.

`review.py` independently checks every Metro ride in the snapshots against the
official GTFS `trips.txt`, `stop_times.txt`, `calendar.txt`, and
`calendar_dates.txt`; it also checks transfer chronology, candidate-limit
prefix ordering, and the topology reason for every zero-candidate row.
`run_pre_metro_toei.py` runs the exact pre-Metro commit and
`compare_pre_metro_toei.py` compares its ordered candidates with the current
ordinary-search rows.

The reviewed output is `baseline_windows_20261025.json.gz`; the independent
rerun is `comparison_windows_20261025.json.gz`. Review and pre-Metro comparison
evidence are committed beside them and summarized in [RESULTS.md](RESULTS.md).

## Phase 3 performance evidence

`phase3_windows_20261025.json.gz` is a fresh comparison-mode run of all 188
fixed searches. It retains each row's candidates and the measured pop, elapsed
time, maximum queue and retained-label counters. `phase3_summary_windows_20261025.json`
contains the overall, objective, estimated-transfer and scope distributions.
The summary uses Type-7 linear interpolation for p50, p95 and p99.

Generate those artifacts from an uncompressed runner result with:

```powershell
python api\benchmarks\tokyo_metro_release_2026_10_25\summarize_phase3.py `
  --input .cache\pr253\phase3_windows_20261025.json `
  --summary api\benchmarks\tokyo_metro_release_2026_10_25\phase3_summary_windows_20261025.json `
  --compressed-run api\benchmarks\tokyo_metro_release_2026_10_25\phase3_windows_20261025.json.gz
```

The summarizer fails unless all 188 rows match the Phase 2 baseline and finish
without an error, a wall-clock measurement above 15 seconds, or a pop count
above 100,000. Elapsed-time percentiles describe this fixed sequential local
run, not production traffic or network-wide p95/p99.
