# Tokyo Metro release roadmap

Baseline: PR #253 commit `da22163dcc6048bc4793293b6300ee4476732e73`

Status date: 2026-10-24 (Asia/Tokyo)

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

**State:** In progress — decision evidence is complete; explicit product risk
acceptance is still required.

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

**Decision inventory:**

The 123 raw ODPT relations currently resolve as follows. The duplicate raw
relation maps to an already represented physical pair; it is not another walk
edge.

| Class | Raw relations | Runtime treatment | What is actually established |
| --- | ---: | --- | --- |
| Reviewed walk connections | 4 | Enabled with reviewed overrides | Official connection plus reviewed path, distance and scheduling allowance; direction/hours only when separately evidenced |
| Automatic estimated connections | 89 | Enabled with 15 minutes and 600 m of walk-resource accounting | Official connection relation only; path, physical distance, time, direction and hours remain unverified |
| Same physical graph node | 1 | Connected without a walk edge | GTFS canonicalization identifies one physical node; this is not evidence for a general station walk time |
| Duplicate raw relation | 1 | Reuses the canonical physical relation | No additional physical connection |
| Unsupported connections | 28 | Disabled | Official relation exists, but the common same-station rule cannot represent it safely |
| **Total** | **123** | **95 raw relations searchable, 28 disabled** | Topology coverage is not verified transfer-time coverage |

The current searchable raw-relation coverage is 95/123 (77.2%). Only four
walk connections have reviewed path/distance/time evidence. The 89 automatic
connections must never be counted as verified merely because they are
searchable. The 15 minutes are an application scheduling estimate and 600 m is
a conservative resource debit, not a measured distance.

**Public-policy choices requiring approval:**

| Choice | Coverage | Main benefit | Main risk | Required user-facing treatment |
| --- | --- | --- | --- | --- |
| A. Reviewed-only | Four reviewed walks plus the same-node case; the remaining automatic and unsupported relations are disabled | Lowest risk of scheduling an unverified interchange | Most ordinary Metro/Toei transfers disappear, making the feature materially incomplete | State that transfer coverage is limited; do not imply full Metro coverage |
| B. Publish the current 89 estimates | 95/123 raw relations searchable | Broadest current network without station-by-station measurements | 15 minutes can still be too short for a real path, while also being too long and hiding a legal train; unknown direction/hours can admit an unavailable path; 600 m can consume the walking budget without being physical distance | Mark affected interchange times as app estimates, not official or guaranteed; warn that individual/accessibility routes may differ |
| C. Hybrid product gate | Keep reviewed connections public and expose the 89 estimates only under an explicitly approved, clearly labelled product policy | Separates known and estimated evidence while retaining an upgrade path | Adds a product-state distinction and still requires an explicit decision about when estimated results are shown | Use the same estimate disclaimer whenever an automatic edge appears; never silently fall back from verified to estimated |

Choice C is a policy alternative, not an implemented new feature. This
roadmap does not choose among A–C. In particular, current runtime availability
does not constitute approval of Choice B.

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

**Open item:** Product owner approval of A, B, or C and the exact Japanese,
English, Chinese, and Korean estimate wording. No choice is inferred here.

**Next action:** Obtain that explicit decision, record it in this section, and
then mark Phase 1 complete without changing its completion conditions.

## Phase 2 — Build the fixed OD regression corpus

**State:** Not started.

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

**Evidence:** None yet. Existing representative and stress measurements in
[Tokyo Metro transfer review](tokyo-metro-transfer-review.md) are inputs, not
a completed fixed corpus.

**Open items:** Select stable OD fixtures from the accepted official feed and
define deterministic expected results without committing authenticated raw
data or secrets.

**Next action:** After Phase 1 approval, define the corpus manifest and
baseline snapshots, then add parameterized regression tests.

## Phase 3 — Decide search performance

**State:** Not started.

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

**Evidence:** Current reference measurements are 56,572 pops for Shibuya to
Asakusa and 75,316 for Nakano-sakaue to Myoden in Metro-only
`fewTransfers`, both returning five candidates without reaching the cap. These
are two probes, not the required distribution.

**Open items:** Phase 2 corpus and repeatable peak-label/timing capture.

**Next action:** Run and summarize the fixed corpus after Phase 2 completes;
do not begin algorithm changes beforehand.

## Phase 4 — Complete release-equivalent verification

**State:** Not started.

**Completion conditions:**

- measure Linux startup time, loaded memory, and search peak memory;
- record the official GTFS acquisition method, version, validity dates, archive
  hash, update/fail-fast procedure, and attribution requirements;
- complete Android hands-on interaction and accessibility checks;
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

**Open items:** Linux measurement harness/result, Android interaction record,
accessibility record, four-language screenshots/checklist, and GTFS operational
runbook validation.

**Next action:** Execute the local Linux and Android release checklist after
Phases 2 and 3 provide the fixed cases. Request separate authorization before
any non-production Lambda action.

## Phase 5 — Make the publication decision

**State:** Blocked by Phases 1–4.

**Completion conditions:**

- all preceding phases are complete with linked evidence;
- every remaining limitation is stated with its user impact and required
  resolution;
- CI and release-equivalent verification pass on the final PR head;
- the product owner explicitly accepts the transfer policy and residual risk.

The PR remains Draft until these conditions are met. This roadmap does not
authorize merging, production deployment, AWS changes, Google Drive changes,
or store operations.

**Evidence:** None; publication is not approved.

**Open items:** All incomplete items in Phases 1–4.

**Next action:** Re-evaluate only after Phases 1–4 are complete. If any item is
still incomplete, report only why it blocks publication and the work required
to resolve it.

## Separate Issue candidates (not PR #253 work)

These entries preserve previously identified ideas without expanding this PR:

- station exit numbers and best-exit guidance;
- indoor station navigation and a reusable station-interior graph;
- evaluation of OSM or Google Places as an indoor-data source;
- any new fare or ticket-entitlement model.

No research or implementation for these candidates is part of this roadmap.
