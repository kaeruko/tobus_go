# Phase 2 initial fixed-corpus result

Measured on 2026-10-25 on the local Windows development host with the accepted
Tokyo Metro GTFS archive `20261008` and the reviewed-transfer manifest SHA-256
`abd91114dc29042c4e4491f421a21555cc1504d90a4cc4dc2ef5262fdb966c5a`.
This is local evidence, not Lambda or production evidence.

The uncompressed JSON SHA-256 is
`e91dfbcdff4c86ba6039fddeee3a74f0f4fd55403c203e487ed7fc3a21e8ae54`;
the deterministically compressed committed artifact SHA-256 is
`3450c1dad45adcfb12303ab2c9f70436aa01bae73e85ff5d955ffe7da22ae4ec`.

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

All Toei-only cases tagged `legacy_toei` had identical ordered-candidate
digests and errors with the estimate option both off and on. Comparison to a
separately frozen pre-Metro baseline is still required before Phase 2 can be
marked complete.

The committed `baseline_windows_20261025.json.gz` preserves the ordered candidate
summaries (including concrete run/trip IDs, stop order, and departure/arrival times), digests, pop
counts, retained-label counts, queue peaks, and measured duration. Runtime
duration and counters are evidence, not deterministic equality fields; reruns
compare candidate content/order and failure conditions exactly.
