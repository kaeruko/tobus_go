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

### Transfer-time limitation

The official connection relation and Tokyo Metro's published interchange list
verify that the interchange exists. The available static inputs do not provide
platform/gate-specific minimum transfer durations. The current prototype uses a
coordinate-distance estimate and labels it
`official_connection_coordinate_estimate`; it does not label the duration as
officially reviewed. Production enablement remains blocked until the required
transfer durations and access paths are reviewed from an authoritative source.

## Local performance sample

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

For Tokyo Metro-only Shibuya to Asakusa at 10:00:

| Objective | Warm time | Candidates | Maximum per-search pop | Limit reached |
| --- | ---: | ---: | ---: | --- |
| `time` | 0.838 s | 1 | 166 | no |
| `fewTransfers` | 2.671 s | 5 | 87,280 | no |

The `fewTransfers` case retains only 12,720 pops (12.72%) below the unchanged
100,000-pop limit. This is a high-priority performance risk before production;
the limit must not be raised to hide it. No timeout-rate claim can be made from
this small local sample.

## Production blockers and follow-up

1. Review and pin platform/gate-specific transfer paths and minimum durations.
2. Decide how the existing Tokyo Toei free-pass policy must behave for a route
   containing Tokyo Metro. The present policy is mode-based (`bus`/`rail`) and
   is intentionally unchanged in this work; it is not operator-safe for Metro.
3. Run the complete CI matrix and Android UI/accessibility test from the PR.
4. Build a versioned deployment artifact from freshly downloaded, hashed
   official inputs. Do not commit or redistribute the raw feed.
5. Re-run a broader fixed OD corpus, especially `fewTransfers`, last trains,
   holidays, and multi-transfer paths, before any production deployment.
