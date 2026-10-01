# Tokyo route investigation — 2026-10-02

This directory contains a read-only performance experiment. Application source
files are unchanged. The experimental functions are compiled from copies of
the installed source and replaced only in the benchmark process.

From the repository root, use the existing route virtual environment:

```powershell
api/.venv-route/Scripts/python.exe -X utf8 api/benchmarks/tokyo_investigation_2026_10_02/investigate.py --stage baseline
api/.venv-route/Scripts/python.exe -X utf8 api/benchmarks/tokyo_investigation_2026_10_02/investigate.py --stage fast
api/.venv-route/Scripts/python.exe -X utf8 api/benchmarks/tokyo_investigation_2026_10_02/investigate.py --stage adapter
```

The script reads `api/data/app_data.pkl` and `api/data/ToeiBus-GTFS`. It makes no
external requests. `source_manifest.json` identifies the input files. The
measurement excludes data loading, HTTP transport, and production log output.
The fixed service date is Friday, 2026-10-02, at 10:00 JST. Realtime is disabled.

## Evidence

- `baseline.json`: graph size, local data-load times, six initial core searches,
  full route payloads, and captured diagnostics. The coordinate-to-graph
  preparation and `TokyoRouteEngine` adapter are outside these core timings.
- `profile_*.txt/json`: instrumented profiles; these are useful for locating
  costs, not for reporting user latency because profiling adds overhead.
- `fast_variants.json`: two OD pairs plus a bus-only Tokyo Station → Toyosu
  case, all three preferences, three measured iterations in rotating order
  following one reference warmup. All 135 comparisons preserve the complete
  Python candidate payload, including paths, candidate order, and times.
- `adapter_variants.json`: `TokyoRouteEngine.search` plus shared serialization,
  including coordinate preparation, output validation, and explicit GC. All 27
  comparisons preserve the response except intentionally randomized step UUIDs.
- `gc_probe.json`: independent parent-agent GC probe after loading the graph.
- `*_without_gtfs.*`: preliminary diagnostic runs before loading the GTFS
  repository. These contain invalidated bus routes and must not be used as the
  representative baseline.

## Variants

- `edge`: iterate adjacent `(node, edge)` pairs and pass the known edge into
  `advance_time`, avoiding a repeated graph lookup.
- `precheck`: reject over-limit walking edges before evaluating their time. For
  cost/fewTransfers, reject edges whose resulting scalar score cannot improve
  `g_score` before evaluating their timetable. Existing queue ordering and
  scoring remain intact.
- `heuristic_env`: cache the cost heuristic per search, and freeze the
  `DEBUG_BUS` environment setting for the experiment.
- `combined`: all of the above.
- `combined_no_forced_gc`: adapter-only diagnostic that skips explicit
  `gc.collect`; repeated-request memory behavior has not been validated.

The optional `experiment` stage tests a static train index. It was deliberately
not prioritized or run: train timetable lookup accounted for about 0.5% of the
observed fewTransfers profile, while repeated bus timetable evaluation and
graph access dominated.

## Interpretation limits

These are local Windows CPython 3.12 measurements, with three repetitions and
small route coverage. They are not Lambda measurements or tail-latency results.
The static input feed version is 20260828_030922. No network delays or realtime
updates were simulated. Confirmation of an implementation change should include
service-day/weekend coverage, realtime delay behavior, production measurements,
and repeated-request memory/peak-memory checks if explicit GC is changed.
