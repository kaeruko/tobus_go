# Tokyo Metro Phase 5 publication decision packet

Prepared: 2026-10-25; final audit: 2026-10-26 (Asia/Tokyo)

PR: #253; Draft removal approved for code review on 2026-10-26

Evidence baseline: `e80fab6a8f753cd2a275c4870fcdcc63f0668cb2`

Audited technical head: `cf9527eadc19692c5432544373f2c18597039c53`

## Decision status

Phases 1 through 4 are complete. On 2026-10-26, the product owner accepted all
seven residual-risk classes below with their existing containment and known
unknowns, assigned the GTFS refresh role and date, and approved removing Draft
status so PR #253 can enter code review. Phase 5 is therefore **complete** with
a **Go for code review** decision.

This decision is not a claim that Lambda performance or unverified transfers
have been proven in production. It does not authorize merge, deployment, AWS,
Lambda, Google Drive, or store operations. Each of those remains a separate
action requiring its own approval.

## Final-head audit

- At the audit point, PR #253 was Draft, open, mergeable, and clean against the
  current `origin/main` (`be9c9d35f6babbf88f58c6a4f5013322a17b6c36`). The audited
  technical head was 14 commits ahead and zero commits behind that base.
- GitHub Actions run `40192458451` passed all eight jobs for the prior audit head
  `cf9527eadc19692c5432544373f2c18597039c53`, including Android/Flutter,
  Windows release AAB, iOS isolation, Python API, both shared-core jobs,
  Windows probe, and repository safety.
- Only the Phase 4/5 documentation changed after release-evidence commit
  `e80fab6a8f753cd2a275c4870fcdcc63f0668cb2`. Application code, fixed inputs,
  snapshots, limits, and test evidence are identical to that green evidence
  head.
- The final diff is whitespace-clean. The changed diff contains no tracked
  `.env`, credential archive, authenticated GTFS ZIP, or value matching the
  targeted secret-assignment scan. The raw authenticated source remains
  outside Git.
- GitHub reports no unresolved review threads. This audit does not substitute
  for any human code-review policy the repository owner may apply at merge
  time.
- The conditional-Go audit record at
  `d2150ab2bc18351bc1b1bbfbb6329264e0972dce` also passed all eight jobs in
  GitHub Actions run `40213999518` before the product-owner decision was
  recorded.
- The commit that records this audit changes only this decision packet and the
  fixed roadmap. Its GitHub checks are the authoritative final-head CI gate;
  recording a later CI run ID must not create an endless documentation-only
  commit cycle.

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
| CI | Complete through the decision baseline | GitHub Actions run `40213999518` passed all eight jobs for `d2150ab`; the preceding evidence and audit runs also passed 8/8. The documentation-only decision-record commit is checked on the PR without creating another commit solely to record its run ID. |

## Residual risks accepted in the product decision

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

- [x] confirm the final pre-decision PR head passes all eight CI jobs;
- [x] confirm no Phase 1–4 evidence or fixed limit changed after this packet;
- [x] explicitly accept all seven residual-risk classes above;
- [x] assign `都営でGO運営担当` as GTFS refresh owner, with the next review
  scheduled for 2026-11-30;
- [x] approve removing Draft status for code review;
- [x] keep merge, deployment, AWS, Google Drive, and store actions separately
  unauthorized until their own approval.

All frozen Phase 5 decision conditions are recorded. CI for the
documentation-only decision commit is verified on the PR before this work is
reported complete.

## Product-owner decision record

Record the decision without changing the frozen roadmap conditions:

| Decision | Status |
| --- | --- |
| 89 opt-in estimated-transfer risks | Accepted as residual risk on 2026-10-26 |
| Four reviewed-walk direction/hour limitations | Accepted as residual risk on 2026-10-26 |
| 28 disabled relations and incomplete coverage | Accepted as residual risk on 2026-10-26 |
| Fixed-corpus-only performance evidence | Accepted as residual risk on 2026-10-26 |
| No Lambda measurement for this build | Accepted as residual risk on 2026-10-26 |
| No physical-device or TalkBack double-tap check | Accepted as residual risk on 2026-10-26 |
| GTFS staleness/update risk | Accepted with the assigned refresh control on 2026-10-26 |
| GTFS refresh owner and next review date | `都営でGO運営担当`; 2026-11-30 |
| Permission to leave Draft | Granted for code review on 2026-10-26 |

The product owner made this decision with the existing mitigations and
unverified facts understood. Draft removal means only that the PR may proceed
to code review. Merge, deployment, AWS, Lambda, Google Drive, and store
operations remain unauthorized, and this decision does not guarantee Lambda
performance or the correctness of an unverified transfer.
