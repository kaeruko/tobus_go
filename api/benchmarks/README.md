# Historical SearchCore v1 Benchmark

The Python/Rust v1 implementations, selector, and benchmark runner were removed
on 2026-10-16 after all active Dataset cities moved to shared SearchCore v2.
The commands and timings below are historical evidence, not runnable current
instructions or v2 certification. The Sendai corpus and Tokyo results are retained.

The committed corpora under `corpus/` exercise representative batched OD pairs
for Sendai. Run each engine in a separate process so index
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

For every row, route presence, pair count, visited states, queue peak, and
generated labels matched between Python and Rust.

| City | Python index build | Rust index build | Python RSS delta | Rust RSS delta |
| --- | ---: | ---: | ---: | ---: |
| Sendai | 379.843 ms | 108.471 ms | 7,921,664 B | 11,730,944 B |

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
