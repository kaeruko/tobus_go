# Tokyo Metro Phase 4 release-equivalent verification

Verification date: 2026-10-25 (Asia/Tokyo)

Baseline: `495a96599b209cd9dbceec8b4a7669d246fe873c`

## Linux startup and memory

The measurement used WSL2 Ubuntu, Linux
`6.6.87.2-microsoft-standard-WSL2-x86_64`, Python 3.12.3, 16 logical CPUs and
16,326,520,832 bytes of visible memory. Ordinary and estimated modes each ran
in a fresh sequential process. Startup used an external monotonic timer; stage
RSS used `psutil`, search peak RSS used a 10 ms sampler, and Linux `VmHWM` was
also captured.

This is local Linux evidence, not a Lambda measurement. No AWS session or
Lambda was accessed, and Lambda memory compatibility remains unverified.

| Stage | Ordinary time / RSS | Estimated time / RSS |
| --- | ---: | ---: |
| Application imports | 4.079 s / 41.6 MiB | 3.734 s / 40.5 MiB |
| Base pickle | 1.428 s / 596.9 MiB | 1.485 s / 597.1 MiB |
| Toei bus GTFS | 5.493 s / 1,037.7 MiB | 5.406 s / 1,037.8 MiB |
| Tokyo Metro GTFS + transfer graph | 1.366 s / 1,197.0 MiB | 1.341 s / 1,197.1 MiB |
| External process start to ready | 12.674 s | 12.271 s |
| Fixed-corpus search peak | 1,286.6 MiB | 1,286.9 MiB |

Each process ran its 94 Phase 2 rows, for all 188 rows across both transfer
modes. There were zero errors, measured calls over 15 seconds, 100,000-pop
hits, or ordered-candidate mismatches. The ordinary maximum was 27,370 pops
and 5.708 seconds; the estimated maximum was 75,316 pops and 5.407 seconds.
The peak difference between modes was only 344,064 bytes (0.33 MiB).

The WSL host had about 14.0 GiB of headroom at the measured peak. Against a
nominal 2,048 MiB process allowance, the same numeric peak would leave about
761 MiB (37.2%), but Lambda adds runtime/container overhead and couples memory
with CPU. The evidence supports retaining 2,048 MiB as the minimum setting for
any separately authorized Lambda validation; it does not support reducing the
setting or claiming Lambda fit without an actual Lambda measurement.

Raw evidence is in
`api/benchmarks/tokyo_metro_release_2026_10_25/phase4_linux_20261025.json.gz`;
the readable summary is beside it.

## GTFS release input

The official archive and masters passed the release-input verifier:

- version `20261008`, valid `2026-09-19..2027-03-12`;
- archive SHA-256 `c50ab5cc3489bf1ff67985491a4d00d25888655918ef887a6cc4887a007dfd73`;
- 9 routes, 185 stops and 9,706 trips;
- service date 2026-10-23 accepted;
- station/railway masters and reviewed-transfer manifest matched their pins.

Thirteen fail-closed regressions reject archive, master, manifest, counterpart,
and base-artifact pinning errors; invalid ZIP; missing files; station-ID
mismatch; edition mismatch; and an out-of-period date. They also prove that
rejection leaves an existing active-artifact sentinel unchanged.
The operational procedure is [documented separately](tokyo-metro-gtfs-release-runbook.md).

## Android and accessibility

No physical Android device was connected. Human physical-device verification
is therefore incomplete and is not replaced by build or widget-test success.

The available Pixel 7 AVD (Android 16 / API 36, x86_64) built and installed the
Tokyo debug APK with the explicit local endpoint override. A local UI-only
mock endpoint was used for navigation; no production API, Google Drive, AWS,
Lambda, store, or deployment operation was used. Route correctness remained
the independent Linux Phase 2 corpus result, not the mock response.

Hands-on emulator checks passed for:

- the three independent transport controls and representative combinations
  through direct manipulation; all seven combinations and the unselected-state
  contract are covered by automated tests;
- explicit estimated-transfer OFF/ON with no automatic fallback;
- a normal result card without a warning and an estimated result card with the
  orange label and full 15-minute/unverified warning;
- normal and estimated route-detail screens, back navigation, and retained
  search criteria;
- no fare or `0`-yen display on cards or details;
- 320 x 568 logical-pixel layout at 130% text scaling, supplemented by five-
  locale layout regressions with no Flutter overflow exception;
- TalkBack focus traversal across fields, all transport choices, the estimated
  opt-in, search action, normal candidate, and estimated candidate.

TalkBack focus was verified, including the estimated option's grouped semantic
label and both candidate cards. The automation bridge could not reliably issue
TalkBack's activate gesture, so activation by a human using TalkBack remains
unverified. Small-screen scrolling and visual wrapping were inspected in
English; the other languages are covered by widget layout tests, not by five
separate human emulator sessions.

## Languages and regression gates

Japanese, English, Simplified Chinese, Traditional Chinese and Korean tests
assert the three transport labels, ordinary/estimated distinction, full
unverified/15-minute warning, card/detail warning, and absence of `600m` as a
physical distance. The 320 x 568 / 130% test renders both the switch description
and candidate warning in every locale without overflow.

Focused results on this Phase 4 change:

- Python: 51 tests passed (`release_inputs`, Metro GTFS, fixed release corpus,
  and transport scope).
- Flutter: 53 focused tests passed (estimated UI, seven scopes, API request
  compatibility, search-state behavior, fares hidden, and five languages).
- Android: `assembleTokyoDebug` succeeded and installed on API 36 emulator.

The full GitHub Actions result is recorded after this evidence commit is pushed.

## Completion decision

Phase 4 is **not complete**. Local Linux, GTFS, emulator UI, language and
automated accessibility evidence pass, but physical-device human testing and
human TalkBack activation remain incomplete. Lambda was intentionally not run
and is recorded as unverified rather than treated as a Phase 4 failure.

To unblock Phase 4, connect one supported Android physical device and repeat
the three-checkbox/estimated-mode/card/detail/back flow at normal and enlarged
text, then have a human TalkBack user focus and activate all controls and both
candidate types. Record device/API level and observed results; no new feature
or roadmap change is required.
