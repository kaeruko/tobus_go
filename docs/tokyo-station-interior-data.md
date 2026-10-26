# Tokyo station-interior and entrance data audit

Status: 2026-10-24, PR #253 Draft. This audit does not authorize production
release of the 89 estimated transfers.

## Decision

No audited machine-readable source is sufficient to build a complete,
redistributable Tokyo Metro/Toei indoor graph today. The PR therefore does not
scrape operator diagrams, persist Google Maps content, import OpenStreetMap, or
invent missing edges. It does add a truthful evidence contract and removes an
invalid geometric assumption from the common transfer model.

The accepted Metro GTFS is feed version `20261008`, valid 2026-09-19 through
2027-03-12 (archive SHA-256
`c50ab5cc3489bf1ff67985491a4d00d25888655918ef887a6cc4887a007dfd73`). Its
185 `stops.txt` records all have `location_type=0`; every `parent_station`,
`level_id` and `platform_code` is empty. It contains no `transfers.txt`,
`pathways.txt` or `levels.txt`.

## Source comparison

| Source | Machine-readable useful fields | Missing for the common graph | Access, licence, update |
| --- | --- | --- | --- |
| ODPT Metro/Toei station JSON | station reference coordinate, operator, railway, code, multilingual title and `connectingStation` | numbered entrances, gates, platforms, corridor edges, length, traversal time, paid-area state, direction and hours | ODPT registration/token; Metro Basic License, Toei CC BY 4.0. Preserve attribution and obtained/version metadata and refresh after provider updates. |
| Tokyo Metro static GTFS `20261008` | exact service, line-level stops and reference coordinates | no location hierarchy, platforms, transfers, pathways or levels | authenticated ODPT download under the dataset licence; update by feed version/validity audit |
| GTFS Schedule specification | standard can express entrance/platform nodes, levels, directed pathways, modes, length/traversal time and minimum transfers | capability is absent from this feed | open specification; does not supply Tokyo data |
| Operator station/accessibility pages | human-readable exit numbers, gate/platform descriptions, lifts/escalators and some hours; official diagrams show topology | no documented bulk API, stable node IDs, coordinates, complete lengths or traversal times | operator web copyright terms do not permit copying/republication beyond applicable legal exceptions without permission; pages/diagrams can be review evidence, not a silently extracted database |
| Tokyo Metro `my!` indoor navigation | demonstrates that platform/gate/exit routing exists in the official app | no public download/API or reuse licence was found | consumer app content is protected and redistribution/copying is restricted |
| Tokyo Open Data | monthly Toei elevator inspection/construction schedule | no station topology, connector endpoints, normal traversal time or entrance coordinates | downloadable open-data resource, monthly; useful later as an outage overlay only |
| Google Places (New) | Place entrances as latitude/longitude; transit-station stop code/location and wheelchair entrance signal may be returned | no exit number contract, gates, indoor edges, lengths, traversal times, direction or hours | billing and API key/OAuth required. Entrances trigger Place Details Pro; transit-station details can require Enterprise. Current list prices begin after 5,000/1,000 free calls at USD 17/20 per 1,000 respectively. Places content has attribution, map-use and caching restrictions; lat/lon caching is limited to 30 days, so it is unsuitable as a committed persistent graph. |
| Google Routes/Indoor Maps | consumer transit/walk routes and visible floor plans | no exportable indoor graph; transit preferences may still return other modes and do not preserve this app's exact scope/candidate contract | billed service and Google terms; not a source for offline reusable graph edges |
| OpenStreetMap | community nodes can include entrances, platforms, levels, elevators, stairs, escalators, one-way and opening hours | not operator-authoritative; coverage/completeness and station containment vary | ODbL, attribution and potential share-alike database obligations. It needs a separate product/licence decision and validation pipeline. |
| MLIT National Land Numerical Information | station/line geometry and related public datasets | no detailed indoor network | open-data terms per dataset; insufficient for this graph |

Primary references:

- <https://ckan.odpt.org/en/dataset/r_station-tokyometro>
- <https://ckan.odpt.org/dataset/r_station-toei>
- <https://developer.odpt.org/terms/data_basic_license.html>
- <https://gtfs.org/documentation/schedule/reference/>
- <https://gtfs.org/documentation/schedule/examples/pathways/>
- <https://www.tokyometro.jp/station/otemachi/accessibility/index.html>
- <https://www.tokyometro.jp/mobiledevice/smartphone/my/howto06.html>
- <https://www.tokyometro.jp/terms/index.html>
- <https://www.kotsu.metro.tokyo.jp/subway/stations/asakusa.html>
- <https://www.kotsu.metro.tokyo.jp/riyo/>
- <https://catalog.data.metro.tokyo.lg.jp/dataset/t000018d0000000051>
- <https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places>
- <https://developers.google.com/maps/documentation/places/web-service/usage-and-billing>
- <https://developers.google.com/maps/billing-and-pricing/pricing>
- <https://cloud.google.com/maps-platform/terms/maps-service-terms/index-20240422>
- <https://osmfoundation.org/wiki/Attribution_Guidelines>

## Reusable directed-graph contract

A future licensed input adapter should normalize data into one provider-neutral
graph, rather than station-specific code. Node kinds are `station_area`,
`entrance`, `gate`, `concourse_junction`, `vertical_landing`, `platform` and
`destination_anchor`. Each node carries stable source IDs, operator/station,
paid-area state, level, optional coordinate and provenance.

Directed edges represent corridor, stairs, escalator, elevator, gate crossing
or outdoor link. Each edge must separately carry:

- direction and opening calendar/window;
- physical length plus its source, or explicit unknown;
- traversal/minimum-transfer time plus whether it is measured, published or
  application-estimated;
- accessibility/equipment constraints and update timestamp;
- evidence URL/version, licence and confidence dimensions.

A transfer is eligible only when every edge in a platform-to-platform path is
available for the direction and time. The same graph supports exit selection
by appending an outdoor destination cost to eligible entrance nodes. A shared
graph does not create a clique among lines in the same station complex:
connectivity must be present in the source path graph or in an explicit,
cited exception.

Loader priority is: GTFS Pathways/Levels/Transfers if supplied by the operator;
another operator-licensed structured facility feed; then narrowly reviewed
exceptions. OSM and Google are separate optional adapters only after licensing,
storage, attribution and coverage decisions. The current inputs fail the
minimum node/edge requirements, so no speculative runtime loader was added.

## Mathematical audit of representative coordinates

For actual transfer endpoints `p` and `q`, any physical route length `L`
satisfies `L >= geodesic(p, q)`. ODPT station reference points `r1` and `r2`
are not established as `p`, `q`, or mandatory waypoints. There is therefore no
general ordering between `geodesic(r1, r2)` and `L`.

Counterexamples are immediate:

- two services can share a platform (`L` close to zero) while their reference
  points are assigned to different entrances hundreds of metres apart;
- two reference points can coincide at a station centroid while the usable
  platforms and corridor are far apart.

The reference-point separation is a valid lower bound only if both reference
points are proved mandatory points of every admissible route (or equivalent
certified endpoint sets are supplied). Current ODPT/GTFS data supplies no such
proof. PR #253 therefore renames the value to
`station_reference_point_separation_meters`, removes the >600 m rejection and
80 m/min time-floor check, and never uses it for pruning or walking resources.

## Evidence and release policy

Runtime/audit metadata tracks these independently:

1. `official_connection_verified`;
2. `path_verified`;
3. `physical_distance_verified`;
4. `minimum_time_verified`;
5. `direction_restrictions_verified`;
6. `availability_hours_verified`.

For all 89 automatic pairs only item 1 is true. Physical distance stays null;
600 m is an accounting debit, not a measured walk. The app-owned 15 minutes is
not operator-published, measured or guaranteed. Existing four reviewed
overrides verify path/distance/time, but direction/hours stay false unless a
cited exception supplies them.

Production-safe policy is fail-closed: automatic pairs remain Draft/experimental
until a licensed path source or station review establishes the required path,
distance/time sufficiency and relevant direction/hour constraints. If product
owners later choose an explicitly estimated public mode, it must be separately
approved, visibly labelled and monitored; it must not be described as an
official or guaranteed transfer. This audit does not make that choice.
