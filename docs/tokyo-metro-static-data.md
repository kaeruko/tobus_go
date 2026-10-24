# Tokyo Metro static-data integration audit

Audit date: 2026-10-23 (Asia/Tokyo)

This document records the exact external inputs and the limitations of the
Tokyo Metro integration. Raw ODPT data is deliberately not committed.

## Source and licence

- Catalog: <https://ckan.odpt.org/dataset/train-tokyometro>
- GTFS resource: <https://ckan.odpt.org/dataset/train-tokyometro/resource/d4f11962-1c5a-4316-9a16-7fb229c227ea>
- Basic License: <https://developer.odpt.org/terms/data_basic_license.html>
- Basic-data guideline: <https://developer.odpt.org/terms/data_basic_use_guideline.html>
- Official interchange list: <https://www.tokyometro.jp/ticket/guide/transfertime/index.html>
- Tokyo Metro/Toei through-ticket notes: <https://www.tokyometro.jp/ticket/types/connection/index.html>
- Official station-map example: <https://www.tokyometro.jp/station/otemachi/yardmap/index_print.html>
- Official station-navigation guide: <https://www.tokyometro.jp/mobiledevice/smartphone/my/howto08.html>

The Basic License permits use in third-party applications, including commercial
applications. An ODPT developer registration and consumer key are required for
the authenticated download. The key must not be logged or shipped in the app.
The reusable source data must not be redistributed without separate permission,
so the ZIP and ODPT JSON masters remain deployment inputs rather than repository
assets. The application displays the ODPT attribution/disclaimer and the data
version, effective period, and retrieval time. The published guideline requires
an update within one week of an applicable data-update notice.

## Accepted snapshot

| Item | Value |
| --- | --- |
| GTFS `feed_version` | `20261008` |
| Effective period | `2026-09-19` through `2027-03-12` |
| ZIP SHA-256 | `c50ab5cc3489bf1ff67985491a4d00d25888655918ef887a6cc4887a007dfd73` |
| ODPT station JSON SHA-256 | `542182aea888d559ca37433ed862248658ffb7ae08a9b7be5641b59eafd129ec` |
| ODPT railway JSON SHA-256 | `90b16083b4acfd73d4ad4dc840f6702e57799279d05d1e6781961c8ab3b97f6c` |
| Routes / stops / trips | 9 / 185 / 9,706 |
| `stop_times` rows | 176,385 |
| `calendar_dates` exceptions | 20 |
| Times at hour 24 or later | 1,903 |

The feed has one Tokyo Metro agency and subway route type only. Weekday service
and Saturday/holiday service are separate, with exact `calendar_dates`
exceptions. Service-day minutes are retained beyond 24:00 without wrapping.
Timed `pickup_type=1` and `drop_off_type=1` restrictions in this snapshot occur
only at the first or last timed call and are represented by excluding the
unboardable/un-alightable boundary segment. A future interior restriction fails
the import instead of being ignored.

GTFS translations provide Japanese and English. Korean, Simplified Chinese, and
Traditional Chinese station names come from the official ODPT station master.
The feed contains only Tokyo Metro stops and segments. A headsign may name a
through-service destination, but no other operator's segment is added to the
graph or made searchable.

## Runtime design

- Explicit transport IDs are `toei_bus`, `toei_subway`, and `tokyo_metro`.
- An absent `transport_scope` retains the old `bus_only` mapping.
- An explicit empty, duplicate, unknown, or conflicting scope fails validation.
- Each request uses an induced graph containing only selected physical and line
  nodes. The query-local timetable adds only the exact Metro services active on
  the requested date. Unselected Metro data is not enumerated by the search.
- The reviewed timetable-transition module is unchanged and still passes its
  AST-based static-time proof.
- Metro ride output is pinned back to the exact GTFS trip, route, service,
  ordered stop occurrences, and clocks selected by the search.
- No fare policy, ticket coverage rule, fare calculation, search objective,
  walking limit, pop limit, or timeout was changed.

Rail interchange edges require an official ODPT `connectingStation` relation;
same names and proximity alone never create them. Bus-to-Metro access uses the
existing pedestrian-distance model and the official stop/station coordinates.

### Common rail-interchange contract

The official connection relation and Tokyo Metro's published interchange list
verify that the interchange exists. The available static inputs do not provide
platform/gate-specific minimum transfer durations. Tokyo Metro's published
60-minute rule describes the fare continuation window for listed out-of-gate
transfers; it is not a minimum walk or connection time. Station maps and the
official app can show paths, but the audited sources do not expose a complete,
machine-readable duration table.

Runtime accepts `tokyo_metro_transfer_policy/v2`. ODPT
`connectingStation` remains mandatory, so neither a common complex, same
displayed name nor proximity creates a clique. The common rule additionally
requires equal normalized ODPT station slugs. This identifies a same-station
relation without making a claim about platform geometry. Different-station
relations require a reviewed override because the available machine-readable
input cannot prove that their walked path meets the existing 600-metre limit.

The common same-station rule schedules 15 minutes. This is an application
allowance, not an operator minimum: it is the full 600-metre walking resource
at the existing 80 m/min floor (7.5 minutes), rounded up with a further 7-minute
circulation/vertical-movement buffer. Because no physical path was measured,
the response reports zero known physical metres, marks the time as estimated,
and separately debits the full 600-metre search resource. Known official
opening windows can be attached as exceptions; the complete walk must fit in a
window. Unknown restrictions are not invented and remain a release caveat.

Four existing reviewed values override the common model and preserve their
official evidence, physical distances and exact allowances. The legacy
`tokyo_metro_reviewed_transfer/v1` parser remains available for compatibility,
but does not enable the automatic rule. Both schemas fail fast for an unknown
official pair, invalid operator, invalid source, duplicate, malformed window,
or a duration shorter than its distance/resource floor.

For the accepted snapshot, the raw 123 relations classify as 89 unique
automatic same-station walk pairs, 4 reviewed walk pairs, 1 same physical node,
1 canonical duplicate and 28 unsupported different-station relations. Thus 95
raw relations are searchable and 28 remain disabled. Bus-to-Metro outdoor
access continues to use the existing coordinate walking model and is not
described as a reviewed platform/gate transfer. See
`docs/tokyo-metro-transfer-review.md` for the full accounting and limitations.

### Fare/UI boundary

The three checkboxes mean only “transport the user can use free of charge”. The
app does not select a ticket and does not promise that a user is eligible. Tokyo
route cards and details do not display a fare or `0` yen. Other cities retain
their existing fare UI.

The existing Tokyo Toei-pass policy remains for API compatibility, but requests
that combine it with `tokyo_metro` fail validation and candidate-level
evaluation also rejects explicit Metro operator/route/trip identifiers. No new
fare policy, ticket type, or fare calculator was introduced.

## Local performance audit

Windows local process, one representative coordinate OD, 2026-10-23. These are
limited development measurements, not Lambda or production percentiles.

| Search | Before | Metro build, same Toei-only scope | Pop result |
| --- | ---: | ---: | --- |
| `time` | 3.232 s | 2.931 s warm | identical: max 8,686; total 13,686 |
| `fewTransfers` | 0.987 s | 1.133 s warm | identical: max 5,992; total 24,290 |

Ignoring generated step UUIDs, the Toei-only routes, clocks, candidates, and
search counts were unchanged. Graph size changed from 18,984 nodes / 63,970
edges to 19,354 nodes / 66,648 edges. Static import added about 156.4 MiB RSS in
this Windows process.

### The 87,280-pop case

The original Draft implementation, Metro-only Shibuya (Ginza) to Asakusa at
10:00 on 2026-10-23, produced:

| Objective | Normal time | Candidates | Maximum per-search pop | Limit reached |
| --- | ---: | ---: | ---: | --- |
| `time` | 0.838 s | 1 | 166 | no |
| `fewTransfers` | 2.671 s | 5 | 87,280 | no |

`fewTransfers` is lexicographic: number of boardings is primary, followed by
the existing secondary components. The API contract asks for up to five
distinct candidates. Candidate quotas of 1, 2, 3, 4, and 5 required 1,397,
5,160, 11,245, 36,065, and 87,280 pops respectively. At five candidates the
search held 91,896 frontier labels and 4,679 queued items. Popped-label counts
by boardings were 3 / 2,700 / 24,995 / 51,031 / 5,625 / 2,926 for zero through
five boardings. Later candidates repeatedly boarded concrete Ginza-line trips,
so concrete-run state, boarding count, clock and walk resources prevented the
ordinary dominance relation from collapsing them. The expensive tail is thus
candidate enumeration under a boarding-first objective, amplified by
unreviewed interchange edges; it is not a slow shortest single itinerary.

An instrumented `tracemalloc` reproduction took 11.259 seconds and peaked at
147.0 MiB of traced allocations. Instrumentation time is not compared with the
normal time above.

After removing all unreviewed rail-interchange estimates, the same isolated
input and interpreter produced 19,004 pops, 20,027 frontier labels, five
candidates, 4.588 instrumented seconds, and 122.0 MiB traced peak. This 78.2%
pop reduction is primarily a correctness fix to the graph, not a general
search-algorithm speedup. After adding the four reviewed transfers, the exact
same input used 27,370 pops, five candidates, and 1.26 seconds in the full
sequential benchmark. That is 68.6% below the original 87,280-pop Draft case
and leaves 72.63% of the fixed per-search pop budget. Process/tool ordering and
allocator effects make the timings and memory samples non-production
measurements.

### Safe pruning implemented

Before invoking the exact search, the adapter now checks reachability in the
directed, timetable-free scoped graph. That graph is a relaxation: it omits
run clocks, service days, walk totals and elapsed-time limits. Every legal exact
itinerary necessarily projects to a path in this graph. Therefore absence of a
static path proves there can be no legal exact result; presence is not treated
as proof and still runs the exact search. Tests cover both directions of that
claim and verify that the exact search is skipped only for the proven
disconnected case.

For an unreviewed cross-operator sample this changed `time` from 32,522 pops and
3.38 seconds to zero pops and 0.20 seconds, and `fewTransfers` from the 100,001
pop error at 3.25 seconds to zero pops and 0.20 seconds. Candidate sets remained
empty. All reachable benchmark candidates and pop counts were unchanged.

An apparently stronger optimization—dropping later concrete trips that had the
same remaining stop sequence and no-earlier arrivals—was rejected. Although it
reduced the Metro sample to hundreds of pops, it changed candidates four and
five and the concrete-trip ordering. The counterexample shows that a
single-path dominance proof is insufficient for the existing five-candidate
enumeration/tie contract. No A* bound, label dominance, or heuristic pruning
without a proof was adopted.

### Seven-scope sample after the correction

Windows local process, official static data, no realtime/network/HTTP,
`PYTHONHASHSEED=0`, 2026-10-23 10:00 representative OD per scope. Times include
query-local preparation. RSS deltas are allocator/cache-sensitive and are not
per-query peaks. Limits remain 15 seconds and 100,000 pops per exact search.

| Scope | Mode | Time | Candidates | Max pop | Peak labels | Peak queue |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| bus | time | 4.93 s | 1 | 25,660 | 120,780 | 97,614 |
| bus | fewTransfers | 0.68 s | 5 | 1,665 | 2,162 | 500 |
| Toei subway | time | 0.44 s | 1 | 40 | 988 | 948 |
| Toei subway | fewTransfers | 0.48 s | 5 | 4,014 | 4,978 | 964 |
| Metro | time | 0.76 s | 1 | 130 | 2,289 | 2,159 |
| Metro | fewTransfers | 1.26 s | 5 | 27,370 | 28,734 | 2,117 |
| bus + Toei subway | time | 3.09 s | 1 | 8,914 | 66,307 | 61,487 |
| bus + Toei subway | fewTransfers | 1.39 s | 5 | 4,655 | 6,291 | 1,638 |
| bus + Metro | time | 1.21 s | 1 | 260 | 3,634 | 4,471 |
| bus + Metro | fewTransfers | 1.25 s | 5 | 2,137 | 4,329 | 2,194 |
| Toei subway + Metro | time | 1.37 s | 1 | 40 | 988 | 948 |
| Toei subway + Metro | fewTransfers | 1.21 s | 5 | 4,014 | 4,978 | 964 |
| all three | time | 1.74 s | 1 | 758 | 11,213 | 13,846 |
| all three | fewTransfers | 1.73 s | 5 | 2,139 | 4,443 | 2,306 |

The original combined-subway representative still resolves entirely on Toei;
separate reviewed-transfer probes are recorded in
`docs/tokyo-metro-transfer-review.md`. With the static check forced off, every
reachable row had identical candidates, errors, pop counts and label counts.
The unchanged Toei-only regression previously compared against pre-Metro main
also kept routes, clocks, candidate counts and search counts identical.

Saturday and holiday Metro samples returned the same candidate/pop pattern as
their timetable permitted (121 `time`; 27,262 `fewTransfers`). Late-night
probes exercised 1,903 source time values at/after 24:00: the 23:40 probe used
81/629 pops, returned 1/2 candidates, and selected concrete trip
`tokyo_metro:10B2341000` at 23:46–24:19. The 23:20 probe used 88/1,371 pops,
returned 1/5 candidates; the current reviewed-transfer run used 1,803
`fewTransfers` pops and selected `tokyo_metro:10B2335000` at 23:25–23:59.
These are bounded cases, not a claim about production percentiles or all
possible origin/destination pairs.

### Process memory

A fresh Windows process measured 39.7 MiB after imports, 597.4 MiB after the
compiled base graph, 1,168.1 MiB after loading the existing Toei bus GTFS
repository, 1,328.3 MiB after importing Metro, and a 1,359.8 MiB peak during
the five-candidate Metro `fewTransfers` search. Metro itself added about
160.1 MiB RSS in this process; most of the total was already present before
Metro import.

The query-local Metro timetable now shares immutable, exact-date-filtered
source records instead of copying every active segment dictionary. Against a
fresh-process reproduction of the previous copy behavior, the candidate JSON
and ordering were identical and peak working set fell by about 35.3 MiB
(1,394.5 to 1,359.2 MiB in the paired run). This is a representation change,
not pruning: active services are still selected from GTFS `calendar` and
`calendar_dates` before the records reach the unchanged timetable transition.

The repository does not pin the existing Tokyo Lambda memory size. A read-only
configuration query on 2026-10-23 could not complete because the local AWS
session had expired. A 2,048 MiB allocation would nominally leave about
688 MiB above this local peak, but OS/container differences, cold-start
overlap, and Lambda `Max Memory Used` have not been measured for this artifact.
Therefore production compatibility is not yet established and must be checked
with a dedicated non-production Lambda before release; reducing duplicate base
graph/Toei GTFS residency is the largest observed memory opportunity.

## Common-model performance update (2026-10-24)

The v2 common model was measured with the same feed, service date, limits and
representative seven scopes. All 18 base/priority calls completed without a
100,000-pop or 15-second search error. The three scopes that exclude Metro
(bus, Toei subway, and bus + Toei subway) retained identical candidate hashes,
candidate counts and pop counts in both objectives.

| Scope | `time` pop / s / candidates | `fewTransfers` pop / s / candidates |
| --- | --- | --- |
| Toei bus | 25,660 / 5.544 / 1 | 1,665 / 0.633 / 5 |
| Toei subway | 40 / 0.419 / 1 | 4,014 / 0.575 / 5 |
| Tokyo Metro | 130 / 0.752 / 1 | 56,572 / 2.044 / 5 |
| bus + Toei subway | 8,914 / 3.322 / 1 | 4,655 / 1.229 / 5 |
| bus + Metro | 260 / 1.169 / 1 | 2,137 / 1.255 / 5 |
| Toei subway + Metro | 40 / 1.169 / 1 | 4,014 / 1.229 / 5 |
| all three | 758 / 1.768 / 1 | 2,139 / 1.639 / 5 |

The fixed Metro Shibuya-to-Asakusa `fewTransfers` query rose from 27,370
pops with four reviewed edges to 56,572 with the common network. Candidate
limits 1 through 5 required 1,397, 5,158, 11,064, 28,836 and 56,572 pops. The
previous development-only all-connection stress result of 85,942 pops for
Nakano-sakaue to Nishi-funabashi became 45,939 under the common model. A
24-query Metro corridor sweep found a higher common-model case,
Nakano-sakaue to Myoden, at 75,316 pops and 77,851 retained labels. No sample
hit the cap, but the worst sample leaves only 24.684% and does not establish a
production limit-hit rate.

The exact 15-minute automatic transfer is enforced before boarding a concrete
trip. Unit tests reject a departure that precedes the completed transfer, a
walk that would extend beyond a known closing window, an unofficial/nonmatching
station relation, and an unsupported different-station link. Existing reviewed
route probes preserve the first result's exact trips and clocks. Newly enabled
same-station routes may legitimately supersede an older path.

Local WSL measurements (not Lambda measurements) were 39.8 MiB after imports,
596.3 MiB after the base pickle, 1,037.0 MiB after Toei bus GTFS, 1,196.2 MiB
after Metro, 1,242.8 MiB final RSS, and 1,280.8 MiB process peak. The four-edge
reviewed run peaked at 1,280.6 MiB, so the additional transfer edges were below
meaningful process-level resolution. The earlier approximately 126.6 MiB string
sharing reduction remains present. A dedicated Lambda artifact measurement is
still required before release.

Tokyo's actual `MAX_TRAVEL_MIN` is 240 minutes. The 180-minute value mentioned
in an earlier audit note belongs to Sendai search parameters and was not a
Tokyo runtime limit. Neither value nor the 100,000-pop/15-second limits was
changed here.

## Production blockers and follow-up

1. Resolve or explicitly exclude the 28 different-station relations whose
   walked paths, directionality or opening restrictions cannot be proven by
   the common input. Audit known time/direction restrictions for the 89
   automatic walk pairs; absence of an exception is not proof of 24-hour use.
2. Run a larger fixed OD corpus. The Metro-only `fewTransfers` tail is improved
   but still structurally grows when five distinct boarding histories are
   requested; no safe general A*/dominance improvement has yet been proved.
3. Run the complete CI matrix and Android UI/accessibility test from the PR.
4. Build a versioned deployment artifact from freshly downloaded, hashed
   official inputs. Do not commit or redistribute the raw feed.
5. Re-run a broader fixed OD corpus, especially `fewTransfers`, last trains,
   holidays, and multi-transfer paths, before any production deployment.
