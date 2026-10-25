# Tokyo Metro Phase 5 publication decision packet

Prepared: 2026-10-25; final audit: 2026-10-26 (Asia/Tokyo)

PR: Draft #253

Evidence baseline: `e80fab6a8f753cd2a275c4870fcdcc63f0668cb2`

Audited technical head: `cf9527eadc19692c5432544373f2c18597039c53`

## Decision status

Phases 1 through 4 are complete. This packet prepares, but does not make, the
Phase 5 publication decision. The PR remains Draft. No merge, deployment, AWS,
Lambda, Google Drive, or store operation is authorized by this document.

The publication decision requires the product owner to explicitly accept or
reject the residual risks below. Choice C for estimated transfers defines how
the feature behaves; its earlier approval was not approval to publish.

The final audit recommendation is **conditional Go**. The implementation and
the frozen technical gates are suitable to proceed to a publication decision,
but publication is not yet approved. The two outstanding Phase 5 decisions are
the product owner's explicit disposition of every residual-risk class below
and assignment of an owner and review date for the GTFS refresh procedure.
These are existing Phase 5 conditions, not new release requirements.

## Final-head audit

- At the audit point, PR #253 was Draft, open, mergeable, and clean against the
  current `origin/main` (`be9c9d35f6babbf88f58c6a4f5013322a17b6c36`). The audited
  technical head was 14 commits ahead and zero commits behind that base.
- GitHub Actions run `40192458451` passed all eight jobs for final head
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
| CI | Complete for final head | GitHub Actions run `40192458451` passed all eight jobs for `cf9527e`; the preceding evidence run `40188956156` also passed 8/8 for `e80fab6a`. |

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

- [x] confirm the final Draft PR head still passes all eight CI jobs;
- [x] confirm no Phase 1–4 evidence or fixed limit changed after this packet;
- explicitly accept or reject each residual-risk class above;
- confirm GTFS refresh ownership before the current feed expires;
- record whether the PR may leave Draft;
- keep merge, deployment, AWS, Google Drive, and store actions separately
  unauthorized until their own approval.

Until those decisions are recorded, Phase 5 remains in progress and public
release is not approved.

## Product-owner decision record

Record the decision without changing the frozen roadmap conditions:

| Decision | Status |
| --- | --- |
| 89 opt-in estimated-transfer risks | Pending explicit accept/reject |
| Four reviewed-walk direction/hour limitations | Pending explicit accept/reject |
| 28 disabled relations and incomplete coverage | Pending explicit accept/reject |
| Fixed-corpus-only performance evidence | Pending explicit accept/reject |
| No Lambda measurement for this build | Pending explicit accept/reject |
| No physical-device or TalkBack double-tap check | Pending explicit accept/reject |
| GTFS staleness/update risk | Pending explicit accept/reject |
| GTFS refresh owner and next review date | Unassigned |
| Permission to leave Draft | Not granted |

If all seven risk classes are accepted, a refresh owner/date is recorded, and
the final head remains green, this packet supports a **Go** decision and Draft
removal. Rejecting a risk does not silently create a workaround: the associated
feature must remain unpublished or the specifically requested evidence/fix must
be completed before reconsideration. Merge, deployment, AWS, Google Drive, and
store operations remain separate approvals in either case.
