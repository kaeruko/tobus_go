# Tokyo Metro Phase 5 publication decision packet

Prepared: 2026-10-25 (Asia/Tokyo)

PR: Draft #253

Evidence baseline: `e80fab6a8f753cd2a275c4870fcdcc63f0668cb2`

## Decision status

Phases 1 through 4 are complete. This packet prepares, but does not make, the
Phase 5 publication decision. The PR remains Draft. No merge, deployment, AWS,
Lambda, Google Drive, or store operation is authorized by this document.

The publication decision requires the product owner to explicitly accept or
reject the residual risks below. Choice C for estimated transfers defines how
the feature behaves; its earlier approval was not approval to publish.

## Completed evidence

| Gate | Result | Evidence |
| --- | --- | --- |
| Transfer policy | Complete | Ordinary search excludes all 89 automatic estimates. Estimated search is explicit, never an automatic fallback, and labels only candidates that traverse an estimated edge. |
| Coverage inventory | Complete | 123 raw relations: 4 reviewed walks, 89 opt-in estimates, 1 same physical node, 1 duplicate relation, and 28 disabled. Opt-in searchable coverage is 95/123 (77.2%); this is not verified-time coverage. |
| Correctness corpus | Complete | All 188 rows match fixed ordered candidates, concrete trips, clocks, service days, stop order, and expected failures. Raw GTFS review covered 428 Metro ride steps and 140 transfer boardings with zero violations. |
| Existing Toei behavior | Complete | 30 independent pre-Metro bus-only, subway-only control, and combined rows match; legacy API compatibility remains covered. |
| Performance | Complete for the fixed corpus | No error, measured call over 15 seconds, or 100,000-pop hit. Maximum is 75,316 pops and 120,780 retained labels. No search algorithm or limit changed. |
| Linux startup and memory | Complete | Fresh-process startup is 12.271–12.674 seconds; full-data RSS is about 1,197 MiB and search peak is 1,286.9 MiB. This is local Linux, not Lambda. |
| GTFS operations | Complete | Feed `20261008`, valid 2026-09-19 through 2027-03-12, archive SHA-256 pinned; fail-closed verifier and replacement-safe runbook pass. |
| UI, language, and accessibility | Complete under approved Phase 4 policy | Android 16/API 36 emulator GUI, five-language layout, all seven scopes, semantics, and TalkBack focus pass; fares and physical `600m` are not displayed. |
| CI | Complete for evidence commit | GitHub Actions run `40188956156` passed all eight jobs for `e80fab6a`. The final PR head must also remain green before any Draft-state decision. |

## Residual risks requiring an explicit publication decision

| Risk | User impact | Existing containment | Decision or later work |
| --- | --- | --- | --- |
| The 89 opt-in transfer paths, physical distances, directions, hours, and actual times are unverified; 15 minutes is an app estimate. | A displayed connection can be infeasible, or a legal train can be omitted because the estimate is too conservative. | Disabled in ordinary search; explicit opt-in; candidate and detail warning; no silent fallback; exact downstream train time still enforced against the estimate. | Explicitly accept for publication under Choice C, or keep the opt-in feature unpublished. |
| The four reviewed walks are not all independently verified for every direction and opening hour. | A route can depend on a direction/time restriction not represented by current evidence. | They are not described as certified or guaranteed; exact reviewed distance/time data is preserved where available. | Accept the limitation or require narrower exception data before publication. |
| Twenty-eight official relations remain disabled. | Some legitimate Metro/Toei journeys return no route or a less useful route. | Fail closed; no invented path or time. | Accept incomplete coverage or defer publication pending a separately approved common rule/evidence source. |
| Fixed-corpus performance is not a network-wide or production-traffic guarantee. | An unseen OD/date combination may reach 15 seconds or 100,000 pops. | Limits remain unchanged; fixed worst case is 75,316 pops; no unsafe pruning was added. | Accept monitored rollout risk, or separately authorize broader sampling/non-production Lambda measurement. |
| Lambda memory and latency have not been measured for this Metro build. | Local Linux headroom may not reproduce in the Lambda runtime, affecting cold start, memory, or timeout behavior. | Local peak is recorded without claiming Lambda fit; no AWS access occurred. | Accept that uncertainty for the publication decision or separately authorize a non-production Lambda test. |
| No physical Android device was tested, and TalkBack double-tap activation was not reliably exercised. | Device-specific rendering/input or activation behavior could differ from the emulator and semantic-focus evidence. | Actual emulator GUI, Android build, semantics, enlarged-text layout, and TalkBack focus were verified; the omission is explicitly disclosed. | The product owner removed this from the Phase 4 gate. Explicitly accept the remaining accessibility/device risk for publication or request a later physical check. |
| The accepted GTFS expires after 2027-03-12 and topology can change sooner. | Stale data can omit or misstate service. | Pinned hash/version/period, service-date rejection, staged validation, and no relabelling of old data as new. | Publication operations must assign an owner and date for the documented refresh procedure. |

## Phase 5 decision checklist

- confirm the final Draft PR head still passes all eight CI jobs;
- confirm no Phase 1–4 evidence or fixed limit changed after this packet;
- explicitly accept or reject each residual-risk class above;
- confirm GTFS refresh ownership before the current feed expires;
- record whether the PR may leave Draft;
- keep merge, deployment, AWS, Google Drive, and store actions separately
  unauthorized until their own approval.

Until those decisions are recorded, Phase 5 remains in progress and public
release is not approved.
