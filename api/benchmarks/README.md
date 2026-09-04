# Route Search Benchmark

The committed corpora under `corpus/` exercise representative batched OD pairs
for Sendai, Yokohama, and Nagoya. Run each engine in a separate process so index
construction and RSS measurements do not share allocator state.

```powershell
python -m benchmarks.route_search `
  --engine python `
  --gtfs-dir data/sendai/2026-08-22 `
  --feed-id sendai_bus `
  --cases benchmarks/corpus/sendai_2026-08-22.json

python -m benchmarks.route_search `
  --engine rust `
  --gtfs-dir data/sendai/2026-08-22 `
  --feed-id sendai_bus `
  --cases benchmarks/corpus/sendai_2026-08-22.json
```

## Local baseline: 2026-09-04

Windows 11, AMD Ryzen 7 9700X, 31.2 GiB RAM, CPython 3.12.10, Rust release
build. Each row uses one warmup followed by five measured searches. The p95 for
five runs is the slowest measured run; production rollout still requires Lambda
telemetry.

| City | Preference | Python p50 | Python p95 | Rust p50 | Rust p95 | p95 speedup |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Sendai | FASTEST | 2781.593 ms | 2931.501 ms | 920.898 ms | 923.358 ms | 3.17x |
| Sendai | FEWEST_TRANSFERS | 2774.450 ms | 2986.164 ms | 931.726 ms | 943.741 ms | 3.16x |
| Yokohama | FASTEST | 3051.971 ms | 3184.692 ms | 1097.447 ms | 1126.408 ms | 2.83x |
| Yokohama | FEWEST_TRANSFERS | 3085.430 ms | 3291.036 ms | 1103.381 ms | 1139.996 ms | 2.89x |
| Nagoya | FASTEST | 7942.213 ms | 8148.439 ms | 2651.553 ms | 2760.022 ms | 2.95x |
| Nagoya | FEWEST_TRANSFERS | 7682.798 ms | 8003.831 ms | 2539.088 ms | 2619.123 ms | 3.06x |

For every row, route presence, pair count, visited states, queue peak, and
generated labels matched between Python and Rust.

| City | Python index build | Rust index build | Python RSS delta | Rust RSS delta |
| --- | ---: | ---: | ---: | ---: |
| Sendai | 379.843 ms | 108.471 ms | 7,921,664 B | 11,730,944 B |
| Yokohama | 991.956 ms | 430.366 ms | 25,821,184 B | 31,645,696 B |
| Nagoya | 919.694 ms | 339.417 ms | 22,097,920 B | 27,648,000 B |

RSS deltas are process snapshots and include allocator effects. Use Lambda cold
start duration, peak memory, error rate, and shadow mismatch logs as the rollout
gate for each city.

## Sendai Lambda rollout: 2026-09-04

The `linux/amd64` image tagged `20260904T121758Z` was deployed to the Sendai
Lambda in `us-west-2` with 2048 MB memory. A representative Iwakiri Station to
Kotsukyoku Tohoku University Hospital route at 08:15 produced the same one-ride,
zero-transfer, 09:12 arrival in all modes.

| Mode | FASTEST HTTP time | FEWEST_TRANSFERS HTTP time |
| --- | ---: | ---: |
| Python | 10.239 s | not separately recorded |
| Shadow | 11.535 s | 11.527 s |
| Rust | 1.809 s | 1.775 s |

The shadow canary reported zero mismatches and zero error logs. Rust Lambda
execution duration was about 1.317 seconds for both preferences, compared with
about 11.02 seconds in shadow mode. Maximum reported memory was 350 MB; the Rust
cold start reported 803 ms init duration. `ROUTE_SEARCH_CORE=rust` remained
enabled after the checks, with configuration-only rollback to `python` ready.
