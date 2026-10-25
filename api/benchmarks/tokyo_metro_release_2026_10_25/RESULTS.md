# Phase 2 fixed-corpus result

Measured on 2026-10-25 on the local Windows development host with the accepted
Tokyo Metro GTFS archive `20261008` and the reviewed-transfer manifest SHA-256
`abd91114dc29042c4e4491f421a21555cc1504d90a4cc4dc2ef5262fdb966c5a`.
This is local evidence, not Lambda or production evidence.

The corrected baseline uncompressed SHA-256 is
`1d970fefe18c7dcf962fb53c8111bac591a081c820e511fc0adfeb366d7d1416`;
the deterministically compressed committed artifact SHA-256 is
`2c7502629152ff94bbf131d9398d1db6788a4e02816a5d8feb68691f394f1d05`.

The first run produced 188 independent searches:

- all seven non-empty transport scopes;
- `time` and `fewTransfers`;
- candidate limits 1 through 5 for the main matrix;
- ordinary and explicit estimated-transfer modes;
- weekend, public holiday, last-train, date-crossing, bidirectional reviewed
  transfer, multi-line, unreachable-without-estimates, and walking-access
  probes.

Results:

| Measure | Result |
| --- | ---: |
| Searches | 188 |
| Errors | 0 |
| 100,000-pop or 15-second limit hits | 0 |
| Maximum pop | 75,316 |
| Maximum retained labels | 120,780 |
| Toei-only candidate mismatches when estimate option changed | 0 |

The maximum remains Nakano-sakaue to Myoden, Metro-only `fewTransfers`, with
five requested candidates and estimated transfers enabled. Its candidate-limit
sweep was 1,445 / 5,109 / 18,867 / 46,207 / 75,316 pops for limits 1 through
5. In ordinary mode the same OD is intentionally unreachable because it
requires an unverified automatic connection; all five limits returned zero
candidates without an error or silent fallback.

Shibuya to Asakusa, Metro-only `fewTransfers`, returned five candidates at
27,370 pops in ordinary mode and 56,572 in estimated mode. This difference is
caused by the selected graph, not an exploration-algorithm optimization.

The public-holiday case now uses Monday 2026-10-12 (Sports Day). The
[Cabinet Office holiday calendar](https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv)
classifies that date as a national holiday, and the accepted
Metro GTFS explicitly removes service `0` and adds service `1` in
`calendar_dates.txt`. The runner fails if either the civil-day classification
or those GTFS exceptions change.

## Independent candidate review

`snapshot_review_20261025.json` records a zero-violation review of all 188
rows. It checked 32 candidate-limit prefix groups, 428 Metro ride steps against
raw `trips.txt`/`stop_times.txt` and exact service activation, and 140 boardings
after a transfer walk. Representative checks include weekday and holiday
trips, reviewed transfers in both directions, the last train, 24-hour date
crossing, and the estimated-transfer stress case.

The ten zero-candidate rows are exactly the ordinary-mode Nakano-sakaue to
Myoden stress sweeps (two objectives times five limits). The ordinary scoped
graph has no directed path between the fixed stations. The opt-in graph does,
and all returned stress candidates actually traverse an estimated edge. No
other row lost all candidates.

Candidate rank was checked independently through the limit 1-to-5 prefix
contract: each smaller result is the exact ordered prefix of the limit-5
result for the same case, objective, and transfer mode. The second full run
then reproduced every ordered candidate, concrete trip, clock, stop order and
failure condition exactly. Its compressed SHA-256 is
`d72604c6f0e81f2e325a855da7e53e5c472570455676f9f2655ff477efc4061f`;
the correctness comparison reports zero mismatches. Elapsed time, pop and
retained-label measurements were deliberately excluded from equality.

## Pre-Metro Toei baseline

The exact pre-Metro main commit
`be9c9d35f6babbf88f58c6a4f5013322a17b6c36` was run independently. The old
public paths were used for bus-only and bus+subway. Because the old public API
did not expose subway-only, that scope is explicitly a measurement control:
the same pre-Metro engine and timetable ran on an induced graph containing
only its rail and rail-station nodes.

All 30 rows (three scopes, two objectives, limits 1 through 5) matched the
current ordinary-search candidate content, trip/time/stop details and order.
The compressed baseline SHA-256 is
`a3a8c46d6e156254246715d38e304e3a7f100675f208e49174eb3ad070a4b2d3`;
`pre_metro_toei_comparison_20261025.json` reports zero mismatches. All
Toei-only rows also remain identical with the estimated-transfer option off
and on.

The committed `baseline_windows_20261025.json.gz` preserves the ordered candidate
summaries (including concrete run/trip IDs, stop order, and departure/arrival times), digests, pop
counts, retained-label counts, queue peaks, and measured duration. Runtime
duration and counters are separate measurement evidence, not deterministic
equality fields. Phase 2's correctness and legacy-compatibility gates are now
complete; no Phase 3 algorithm change was made.

## Phase 3 fixed-corpus performance gate

The same 188 searches were rerun sequentially in one warm CPython 3.12.10
process on the local Windows 11 AMD64 development host (16 logical CPUs).
`time.perf_counter` covered `TokyoRouteEngine.search_legacy` only. A full
`gc.collect` ran immediately before each search; initial pickle/GTFS loading
and graph construction were excluded. Consequently, elapsed time is local-host
evidence, while pop, queue and retained-label values are engine counters for
the fixed inputs.

All 188 rows matched the Phase 2 candidates, concrete trips, stop order,
departure/arrival times, candidate order and expected failures. There were no
search errors, measured calls over 15 seconds, or 100,000-pop limit hits.
Type-7 linear interpolation is used for the fixed-sample percentiles below.
These percentiles describe the corpus distribution, not production demand or
all possible origin/destination pairs.

| Metric | Median | p95 | p99 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Pop | 1,244.5 | 26,701.3 | 56,387.6 | 75,316 |
| Elapsed seconds | 1.126 | 4.393 | 5.140 | 5.327 |
| Maximum queue | 1,053 | 84,969.6 | 97,614 | 97,614 |
| Retained labels | 3,113 | 105,754.9 | 120,780 | 120,780 |
| Candidate count | 1 | 5 | 5 | 5 |

Objective and estimated-transfer partitions remained distinct:

| Partition | Rows | Pop median / p95 / p99 / max | Seconds median / p95 / p99 / max | Labels median / p95 / p99 / max |
| --- | ---: | --- | --- | --- |
| `time` | 94 | 130 / 25,660 / 25,660 / 25,660 | 1.174 / 5.014 / 5.200 / 5.327 | 2,300 / 120,780 / 120,780 / 120,780 |
| `fewTransfers` | 94 | 2,052 / 43,497.1 / 57,884.1 / 75,316 | 1.107 / 1.856 / 2.051 / 2.432 | 3,316 / 45,533.5 / 60,231.2 / 77,851 |
| Estimated OFF | 94 | 856.5 / 25,660 / 27,269.6 / 27,370 | 1.107 / 3.910 / 5.200 / 5.327 | 2,396 / 85,372.5 / 120,780 / 120,780 |
| Estimated ON | 94 | 1,487.5 / 43,497.1 / 57,884.1 / 75,316 | 1.149 / 4.085 / 5.003 / 5.040 | 3,508 / 92,876.1 / 120,780 / 120,780 |

The complete summary additionally records queue and candidate-count
percentiles for each partition, each objective/estimated-mode combination and
all seven scopes. Scope maxima were:

| Scope | Max pop | Max seconds | Max queue | Max retained labels |
| --- | ---: | ---: | ---: | ---: |
| Toei bus | 25,660 | 5.327 | 97,614 | 120,780 |
| Toei subway | 4,014 | 0.675 | 964 | 4,978 |
| Tokyo Metro | 75,316 | 2.432 | 3,139 | 77,851 |
| Toei bus + subway | 8,914 | 3.726 | 61,487 | 66,307 |
| Toei bus + Metro | 2,137 | 1.409 | 4,477 | 4,329 |
| Toei subway + Metro | 4,014 | 1.340 | 966 | 4,980 |
| All three | 2,139 | 2.010 | 13,859 | 11,221 |

The required references reproduced exactly:

- Shibuya to Asakusa, Metro-only `fewTransfers`, five candidates: 27,370 pops
  ordinary and 56,572 with estimated transfers;
- Nakano-sakaue to Myoden, Metro-only `fewTransfers`, five candidates with
  estimates: 75,316 pops;
- fixed-corpus maximum retained labels: 120,780 (the existing Toei bus-only
  `time` case, not the Metro stress case).

The compressed raw run SHA-256 is
`aa240be1f610a80da0ed97e8ab6406983f42d4aa9d2312f2f6bf5ffae31ed6b2`.
The summary SHA-256 is
`763da47a7993afe0deef35c5aa423e40dbc79dbbf1e8eb7da7a9bd3a2f8026e1`.
The uncompressed raw SHA-256, input hashes and exact per-row measurements are
recorded inside the summary.

The fixed performance gate therefore passes without an exploration-algorithm
change. This does not establish production p95/p99 or prove that every
possible network query stays below either limit; those residual risks remain
for the Phase 5 publication decision after Phase 4 release-equivalent evidence.
