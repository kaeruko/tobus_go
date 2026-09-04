# GTFS Transit SearchCore

PyO3 implementation of the immutable, integer-indexed GTFS route search used by
Sendai, Yokohama, and Nagoya. Tokyo keeps its existing NetworkX-based engine.

## Local build

From `api/`, with a Python virtual environment and the stable Rust toolchain:

```shell
python -m pip install "maturin>=1.9.4,<2"
python -m maturin develop --release --locked \
  --manifest-path native/transit_search_core/Cargo.toml
```

The extension uses `abi3-py311`, so one wheel supports CPython 3.11 and newer.

## Runtime selection

Set `ROUTE_SEARCH_CORE` before API startup:

- `python` (default): return the Python result.
- `rust`: return the Rust result; startup fails if the extension is unavailable.
- `shadow`: return the Python result and log any structural mismatch with Rust.

Shadow mode runs both engines and is intended only for limited canary traffic.

## Tests and benchmark

```shell
cargo fmt --manifest-path native/transit_search_core/Cargo.toml --check
cargo clippy --locked --manifest-path native/transit_search_core/Cargo.toml --all-targets -- -D warnings
cargo test --locked --manifest-path native/transit_search_core/Cargo.toml
python -m unittest tests.test_route_search_golden tests.test_search_core_factory -v
python -m benchmarks.route_search --engine python
python -m benchmarks.route_search --engine rust
```

For a real feed, also pass `--gtfs-dir`, `--feed-id`, and one of the committed
files under `benchmarks/corpus/` using `--cases`.

## Staged rollout

Deploy the image first while `ROUTE_SEARCH_CORE` is unset or `python`, then move
each city through `shadow` and `rust`. Use Sendai first, then Yokohama, then
Nagoya. The setting script preserves all other Lambda environment variables and
uses the Lambda revision id to reject concurrent updates:

```powershell
.\scripts\set_route_search_core.ps1 -City sendai -LambdaFunction sendaigo-api -Mode shadow -WhatIf
.\scripts\set_route_search_core.ps1 -City sendai -LambdaFunction sendaigo-api -Mode shadow -Confirm:$false
.\scripts\set_route_search_core.ps1 -City sendai -LambdaFunction sendaigo-api -Mode rust -Confirm:$false
```

Rollback is the same operation with `-Mode python`. Repeat only after checking
shadow mismatch logs, route errors, latency, and memory for the current city.
