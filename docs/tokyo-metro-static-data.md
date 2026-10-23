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

### Reviewed rail-interchange contract

The official connection relation and Tokyo Metro's published interchange list
verify that the interchange exists. The available static inputs do not provide
platform/gate-specific minimum transfer durations. Tokyo Metro's published
60-minute rule describes the fare continuation window for listed out-of-gate
transfers; it is not a minimum walk or connection time. Station maps and the
official app can show paths, but the audited sources do not expose a complete,
machine-readable duration table.

Consequently an ODPT relation, same station name, or straight-line coordinate
distance is never enough to add a rail-to-rail walk edge. Runtime accepts an
optional `tokyo_metro_reviewed_transfer/v1` manifest. Every entry must provide
the two ODPT station IDs, reviewed minimum minutes, actual walking distance,
review date, and official HTTPS evidence URLs. Import fails for an unknown
pair, invalid operator, unapproved source, duplicate, or value outside the
existing 600-metre per-walk limit. With no manifest, no Metro/Toei or Metro
inter-line interchange edge is added. This is intentionally fail-closed.

As of this audit there is no accepted production transfer manifest. Therefore
Metro/Toei rail interchange and Metro inter-line interchange remain disabled,
not estimated. The 57 Metro-to-Toei-family ODPT relations found in 54 Metro
station objects include non-subway targets and line-specific station objects;
each subway interchange still needs a path/time review. Bus-to-Metro outdoor
access continues to use the existing coordinate walking model and is not
described as a reviewed platform/gate transfer.

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
search-algorithm speedup. The first three direct candidates were preserved;
later candidate content changed because routes that used unverified transfer
edges were removed. In the full sequential seven-scope benchmark below the
same OD used 19,529 pops; process/tool ordering and allocator effects make the
timings and memory samples non-production measurements.

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
| bus | time | 7.18 s | 1 | 25,660 | 120,780 | 97,614 |
| bus | fewTransfers | 1.11 s | 5 | 1,665 | 2,162 | 500 |
| Toei subway | time | 0.67 s | 1 | 40 | 988 | 948 |
| Toei subway | fewTransfers | 0.50 s | 5 | 4,014 | 4,978 | 964 |
| Metro | time | 0.94 s | 1 | 130 | 2,287 | 2,157 |
| Metro | fewTransfers | 1.30 s | 5 | 19,529 | 20,615 | 1,489 |
| bus + Toei subway | time | 3.88 s | 1 | 8,914 | 66,307 | 61,487 |
| bus + Toei subway | fewTransfers | 1.67 s | 5 | 4,655 | 6,291 | 1,638 |
| bus + Metro | time | 1.35 s | 1 | 260 | 3,633 | 4,470 |
| bus + Metro | fewTransfers | 1.40 s | 5 | 2,137 | 4,329 | 2,194 |
| Toei subway + Metro | time | 1.26 s | 1 | 40 | 988 | 948 |
| Toei subway + Metro | fewTransfers | 1.19 s | 5 | 4,014 | 4,978 | 964 |
| all three | time | 1.87 s | 1 | 758 | 11,211 | 13,844 |
| all three | fewTransfers | 1.83 s | 5 | 2,139 | 4,443 | 2,306 |

The combined subway sample resolves entirely on Toei because cross-operator
transfer paths are deliberately unavailable; it is not evidence that a
Metro/Toei transfer works. With the new static check forced off, every reachable
row had identical candidates, errors, pop counts and label counts. The
unchanged Toei-only regression previously compared against pre-Metro main also
kept routes, clocks, candidate counts and search counts identical.

Saturday and holiday Metro samples returned the same candidate/pop pattern as
their timetable permitted (121 `time`; 19,531 `fewTransfers`). Late-night
probes exercised 1,903 source time values at/after 24:00: the 23:40 probe used
81/494 pops, returned 1/2 candidates, and selected concrete trip
`tokyo_metro:10B2341000` at 23:46–24:19. The 23:20 probe used 88/1,371 pops,
returned 1/5 candidates, and selected `tokyo_metro:10B2335000` at 23:25–23:59.
These are bounded cases, not a claim about production percentiles or all
possible origin/destination pairs.

## Production blockers and follow-up

1. Review and pin platform/gate-specific transfer paths and minimum durations;
   until then real Metro/Toei and Metro inter-line transfers are unavailable.
2. Run a larger fixed OD corpus. The Metro-only `fewTransfers` tail is improved
   but still structurally grows when five distinct boarding histories are
   requested; no safe general A*/dominance improvement has yet been proved.
3. Run the complete CI matrix and Android UI/accessibility test from the PR.
4. Build a versioned deployment artifact from freshly downloaded, hashed
   official inputs. Do not commit or redistribute the raw feed.
5. Re-run a broader fixed OD corpus, especially `fewTransfers`, last trains,
   holidays, and multi-transfer paths, before any production deployment.
