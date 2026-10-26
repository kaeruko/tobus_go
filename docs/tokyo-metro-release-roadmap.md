# Tokyo Metro release roadmap

Roadmap baseline: PR #253 commit `da22163dcc6048bc4793293b6300ee4476732e73`

Phase 1 implementation baseline: `a97193658fe185b8f2cf7cd50c4f27cb7f3ddef8`

Status date: 2026-10-26 (Asia/Tokyo)

## Goal and change control

The only release goal of PR #253 is to add Tokyo Metro to the existing Tokyo
route search and make it publishable with timetable, concrete-trip, transfer,
and search-performance evidence. The three independent transport checkboxes,
all seven non-empty scopes, hidden Tokyo fares, existing API compatibility,
objectives, walking constraints, 15-second limit, 100,000-pop limit, and
five-candidate ordering remain fixed requirements.

The five phases and their completion conditions below are frozen. New findings
may update evidence, results, status, open items, and the next action, but must
not add, remove, or redefine a phase or completion condition. A proposed
roadmap change must first state its reason, impact, and alternatives and obtain
explicit approval. "It could be improved further" is not sufficient.

The following are out of scope. They may be copied to a separate Issue proposal
but are not researched or implemented in this PR:

- station exit numbers or best-exit guidance;
- indoor station navigation;
- a new indoor-data foundation based on OpenStreetMap or Google Places;
- new fare calculation or ticket-entitlement logic;
- changes to existing features unrelated to adding Tokyo Metro.

## Phase 1 — Freeze the public transfer policy

**State:** Complete.

**Completion conditions:**

- compare the risk, user-facing description, constraints, and coverage of the
  89 automatic, four reviewed, and 28 unsupported connections;
- preserve the distinction between verified and estimated values;
- choose, with explicit approval, how estimated transfers will be treated in
  the public product;
- record the approved policy without representing an estimated transfer as an
  officially verified or guaranteed transfer.

**Evidence:**

- [Tokyo Metro transfer review](tokyo-metro-transfer-review.md)
- [Static-data acceptance audit](tokyo-metro-static-data.md)
- [Station-data evidence and geometry audit](tokyo-station-interior-data.md)
- Runtime evidence fields and regression tests in commit
  `da22163dcc6048bc4793293b6300ee4476732e73`
- API graph-gating regressions in `api/tests/test_transport_scope.py`
- Five-language option/result/detail UI regressions in
  `test/estimated_transfer_ui_test.dart`

**Decision inventory:**

The 123 raw ODPT relations currently resolve as follows. The duplicate raw
relation maps to an already represented physical pair; it is not another walk
edge.

| Class | Raw relations | Runtime treatment | What is actually established |
| --- | ---: | --- | --- |
| Reviewed walk connections | 4 | Enabled with reviewed overrides | Official connection plus reviewed path, distance and scheduling allowance; direction/hours only when separately evidenced |
| Automatic estimated connections | 89 | Excluded from ordinary search; included only after the explicit estimated-transfer opt-in, with 15 minutes and 600 m of walk-resource accounting | Official connection relation only; path, physical distance, time, direction and hours remain unverified |
| Same physical graph node | 1 | Connected without a walk edge | GTFS canonicalization identifies one physical node; this is not evidence for a general station walk time |
| Duplicate raw relation | 1 | Reuses the canonical physical relation | No additional physical connection |
| Unsupported connections | 28 | Disabled | Official relation exists, but the common same-station rule cannot represent it safely |
| **Total** | **123** | **Six non-estimated relations available normally; 89 additional relations available only by opt-in; 28 disabled** | Topology coverage is not verified transfer-time coverage |

The opt-in searchable raw-relation coverage is 95/123 (77.2%). Ordinary search
does not use the 89 automatic connections. Only four walk connections have
reviewed path/distance/time evidence. The 89 automatic connections must never
be counted as verified merely because they are available after opt-in. The 15
minutes are an application scheduling estimate and 600 m is a conservative
resource debit, not a measured distance.

**Approved public policy (2026-10-25): Choice C.**

| Choice | Coverage | Main benefit | Main risk | Required user-facing treatment |
| --- | --- | --- | --- | --- |
| A. Reviewed-only | Four reviewed walks plus the same-node case; the remaining automatic and unsupported relations are disabled | Lowest risk of scheduling an unverified interchange | Most ordinary Metro/Toei transfers disappear, making the feature materially incomplete | State that transfer coverage is limited; do not imply full Metro coverage |
| B. Publish the current 89 estimates | 95/123 raw relations searchable | Broadest current network without station-by-station measurements | 15 minutes can still be too short for a real path, while also being too long and hiding a legal train; unknown direction/hours can admit an unavailable path; 600 m can consume the walking budget without being physical distance | Mark affected interchange times as app estimates, not official or guaranteed; warn that individual/accessibility routes may differ |
| C. Hybrid product gate | Keep reviewed connections public and expose the 89 estimates only under an explicitly approved, clearly labelled product policy | Separates known and estimated evidence while retaining an upgrade path | Adds a product-state distinction and still requires an explicit decision about when estimated results are shown | Use the same estimate disclaimer whenever an automatic edge appears; never silently fall back from verified to estimated |

The product owner explicitly approved Choice C. Ordinary searches use the four
reviewed walk connections, the same-physical-node relation, and other existing
connections already allowed by the route engine; they exclude all 89 automatic
estimated connections. The result screen provides a separate explicit control
to include estimated transfers. It is not a fourth transport type, is never
enabled automatically, and an empty ordinary result never triggers an
estimated retry. The setting is sent into graph selection before exact top-N
enumeration, rather than filtering an estimated result list afterward.

A candidate that actually traverses an automatic edge carries a distinct
estimated-transfer marker and displays the approved warning in Japanese,
English, Simplified Chinese, Traditional Chinese, and Korean. The warning says
that only the official station connection is known, while path, distance,
time, and hours are unverified; it states that the app assumes 15 minutes and
asks the user to check official station guidance. The 600 m planning resource
is never displayed as physical walking distance.

This approval covers the conditions for exposing estimated routes. It is not
approval to publish, does not accept every remaining transfer risk, and does
not make the four reviewed connections fully direction/hour verified. No route
is described as officially certified or safety-guaranteed.

**Risks that the decision must explicitly accept or avoid:**

- false-positive feasibility when an actual directed path takes more than the
  estimated allowance or is closed at that time;
- false-negative candidates when 15 minutes or the 600 m resource debit is
  more conservative than the real connection;
- asymmetric gates, out-of-gate routes, first/last-train access, construction,
  crowding, and accessibility paths not represented by `connectingStation`;
- changes in operator topology while an older ODPT/GTFS snapshot remains
  loaded;
- users interpreting a displayed estimate as an operator guarantee.

The common safety constraints remain unchanged under every choice: exact GTFS
trip and service-day checks, existing board/alight allowance, continuous and
total walking limits, objectives, candidate ordering, 15 seconds, and 100,000
pops. Unknown values are not converted into measured distance or official
minimum time.

**Open item:** None for this phase. Direction/hour limitations remain release
risks evaluated by the later fixed phases; they do not reopen Phase 1.

**Next action:** Keep the approved policy fixed while Phase 2 verifies ordinary
and opt-in searches independently.

## Phase 2 — Build the fixed OD regression corpus

**State:** Complete.

**Completion conditions:**

- commit a reproducible fixed corpus covering all seven transport scopes,
  `time` and `fewTransfers`, and candidate limits 1 through 5;
- cover weekday, weekend, public holiday, last train, date crossing, walking
  limits, direction-dependent transfer, unreachable searches, and multi-line
  transfers;
- assert candidate content, concrete trip IDs, departure/arrival times,
  ordering, and expected failure conditions;
- compare Toei-only results with the pre-Metro baseline and preserve legacy API
  behavior.

**Evidence:**

- [Fixed corpus definition and runner](../api/benchmarks/tokyo_metro_release_2026_10_25/README.md)
- [Initial 188-search result](../api/benchmarks/tokyo_metro_release_2026_10_25/RESULTS.md)
- `baseline_windows_20261025.json.gz` in the same evidence directory contains
  ordered candidate/trip/time snapshots and performance counters.
- `comparison_windows_20261025.json.gz` is an independent comparison-mode
  rerun with zero correctness mismatches.
- `snapshot_review_20261025.json` records raw-GTFS and transfer-chronology
  review of representative and aggregate candidates.
- `pre_metro_toei_baseline_20261025.json.gz` and
  `pre_metro_toei_comparison_20261025.json` record the independent pre-Metro
  Toei baseline and the zero-mismatch 30-row comparison.

The corrected run and independent comparison run each completed all 188 calls without a search error, timeout, or pop
limit hit. Maximum pop was 75,316 and maximum retained labels was 120,780.
The real public-holiday case is 2026-10-12 (Sports Day); civil holiday status
and the GTFS removal of service 0/addition of service 1 are both asserted.
Every ordered candidate, concrete trip, clock, stop order, and expected failure
matched on rerun. A separate review checked 428 Metro ride steps against raw
GTFS and 140 transfer boardings with no violation. The ten zero-candidate rows
are proven static disconnections in ordinary mode and become reachable only
through marked estimated edges.

The current ordinary results also match 30 independently generated rows from
the exact pre-Metro commit for bus-only, subway-only, and bus+subway. The first
and third use legacy public API modes; subway-only is explicitly an induced
rail-only measurement control because the old API did not expose that scope.
Toei-only results also do not change when the estimated option is toggled.

**Open items:** None for this phase. Raw authenticated data and secrets remain
excluded.

**Next action:** Execute the existing Phase 3 measurement gate with this fixed
corpus. No Phase 3 algorithm work has started; only consider it if the fixed
measurement gate fails.

## Phase 3 — Decide search performance

**State:** Complete.

**Completion conditions:**

- run the Phase 2 corpus under the unchanged 100,000-pop and 15-second limits;
- report the distribution and maximum of pops, elapsed time, candidate count,
  completion/failure, and retained labels, including the 75,316-pop
  Nakano-sakaue to Myoden case;
- establish whether every required case completes with the correct ordered
  candidates;
- only if the fixed corpus fails, assess and implement a mathematically safe
  lower bound, dominance rule, or pruning rule with proof and counterexample
  tests.

Changing candidate order, objectives, search limits, or walking constraints is
not a performance fix and cannot satisfy this phase.

**Evidence:**

- [Phase 3 fixed-corpus results](../api/benchmarks/tokyo_metro_release_2026_10_25/RESULTS.md#phase-3-fixed-corpus-performance-gate)
- `phase3_windows_20261025.json.gz` in the same evidence directory contains
  all 188 per-search candidate snapshots and performance counters.
- `phase3_summary_windows_20261025.json` records overall, objective,
  estimated-transfer, combined and seven-scope distributions plus the exact
  measurement environment and method.
- `api/tests/test_tokyo_metro_release_corpus.py` verifies the unchanged limits,
  required reference values and exact Phase 2/Phase 3 candidate equality.

All 188 fixed searches completed without an error, a measured call over 15
seconds or a 100,000-pop limit hit. Candidate/trip/time/order mismatches against
Phase 2 were zero. Maximum pop remained 75,316 and maximum retained labels
remained 120,780. Shibuya to Asakusa reproduced 27,370 ordinary and 56,572
estimated pops; Nakano-sakaue to Myoden reproduced 75,316 estimated pops.
No search-algorithm change was required or made.

The elapsed-time p95/p99 values are distributions over this fixed local corpus,
not production traffic percentiles or a network-wide guarantee. Possible
unseen origin/destination inputs reaching a limit remain a Phase 5 publication
risk after release-equivalent Phase 4 evidence.

**Open items:** None for this phase.

**Next action:** Proceed to the already-defined Phase 4 local Linux, Android,
accessibility, language and GTFS operational checks. Do not access AWS or run a
non-production Lambda without separate explicit authorization.

## Phase 4 — Complete release-equivalent verification

**State:** Complete.

**Completion conditions:**

- measure Linux startup time, loaded memory, and search peak memory;
- record the official GTFS acquisition method, version, validity dates, archive
  hash, update/fail-fast procedure, and attribution requirements;
- complete Android emulator hands-on interaction and accessibility checks under
  the product-owner-approved release-equivalent evidence policy;
- verify Japanese, English, Chinese, and Korean UI and the three-checkbox
  behavior;
- preserve timetable, exact-trip, transfer, fare-hidden, API-compatibility,
  and scope-isolation behavior in release-equivalent builds.

A non-production Lambda test is not authorized by this roadmap. It may be run
only after separate explicit approval; until then this phase uses local Linux
evidence and records Lambda as not executed rather than silently accessing AWS.

**Evidence:**

- Accepted GTFS currently recorded as version `20261008`, valid
  2026-09-19 through 2027-03-12, archive SHA-256
  `c50ab5cc3489bf1ff67985491a4d00d25888655918ef887a6cc4887a007dfd73`.
- Current Windows process measurements and CI build results are documented in
  [Tokyo Metro transfer review](tokyo-metro-transfer-review.md); they do not
  replace Linux or Android hands-on evidence.
- [Phase 4 release-equivalent verification](tokyo-metro-phase4.md)
- [Static GTFS release runbook](tokyo-metro-gtfs-release-runbook.md)
- Linux raw and summarized evidence in
  `api/benchmarks/tokyo_metro_release_2026_10_25/phase4_linux_20261025.json.gz`
  and `phase4_linux_summary_20261025.json`
- Accepted release-input verification in
  `api/benchmarks/tokyo_metro_release_2026_10_25/phase4_gtfs_verification_20261025.json`

Linux measurement, GTFS validation/runbook, Android emulator interaction, five-
language automated layout, accessibility semantics, and TalkBack focus
traversal are complete. The local Linux peak was 1,286.9 MiB and all 188
searches exactly matched Phase 2; this is not Lambda evidence. The AVD verified
normal/estimated cards and details without fare display. GitHub Actions run
`40188956156` passed all eight jobs for evidence commit `e80fab6a`.

**Product-owner evidence decision (approved 2026-10-25):** Physical Android
hardware is not mandatory for Phase 4. The emulator's actual GUI interaction,
Flutter regressions, accessibility semantics, and observed TalkBack focus are
accepted as the Android release-equivalent evidence. The reason is the product
owner's explicit choice that these existing checks are sufficient for this
phase; no additional feature or technical finding expanded the scope. The
impact is limited to evidence interpretation: device-specific behavior and
TalkBack double-tap activation remain unverified and must be stated as residual
risks, but they do not block Phase 4. This approval does not assert that those
checks occurred and does not itself approve publication.

**Open items:** None for this phase. Lambda fit, physical-device behavior, and
TalkBack activation remain explicitly unverified Phase 5 inputs, not completed
checks. Lambda was neither authorized nor required by Phase 4.

**Next action:** Use the fixed Phase 1–4 evidence and explicit residual-risk
inventory for Phase 5. Do not access Lambda without separate authorization.

## Phase 5 — Make the publication decision

**State:** Complete.

**Completion conditions:**

- all preceding phases are complete with linked evidence;
- every remaining limitation is stated with its user impact and required
  resolution;
- CI and release-equivalent verification pass on the final PR head;
- the product owner explicitly accepts the transfer policy and residual risk.

The PR remained Draft until these conditions were met. Draft removal for code
review is now approved, but this roadmap does not authorize merging, production
deployment, AWS changes, Google Drive changes, or store operations.

**Evidence:** [Phase 5 publication decision packet](tokyo-metro-phase5-publication-decision.md).
The 2026-10-26 final audit found PR #253 clean and mergeable against the current
`origin/main`; audit baseline `d2150ab2bc18351bc1b1bbfbb6329264e0972dce`
passed all eight CI jobs in run `40213999518`, with no application/evidence
change after the Phase 4 evidence head.

On 2026-10-26 the product owner explicitly accepted all seven documented
residual-risk classes, assigned the GTFS refresh role to `都営でGO運営担当` with
the next review on 2026-11-30, and approved Draft removal for code review. The
owner stated that this is not proof of production Lambda performance or
unverified-transfer correctness. The decision-record commit is documentation
only and its PR CI is checked before completion is reported.

**Open items:** None for the frozen Phase 5 completion conditions. The accepted
risks remain real limitations, and the scheduled GTFS review remains an
operational obligation. Merge, deployment, AWS, Lambda, Google Drive, and store
actions remain separately unauthorized.

**Next action:** Proceed with code review. Do not merge, deploy, access AWS or
Lambda, change Google Drive, or perform store operations without separate
explicit approval.

## Separate Issue candidates (not PR #253 work)

These entries preserve previously identified ideas without expanding this PR:

- station exit numbers and best-exit guidance;
- indoor station navigation and a reusable station-interior graph;
- evaluation of OSM or Google Places as an indoor-data source;
- any new fare or ticket-entitlement model.

No research or implementation for these candidates is part of this roadmap.
