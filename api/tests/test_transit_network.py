"""Scheduled common-network contracts; every feed/link here is synthetic."""
import contextlib
from dataclasses import replace
from datetime import date, datetime, timezone
from fractions import Fraction
import io
from pathlib import Path
import tempfile
import unittest

import networkx as nx

from reviewed_walk_time import ReviewedWalkingLink
from route_engine import RouteContractError, RouteSearchLimitError
from transit_dataset import (
    FeedMetadata, ServiceCalendar, ServiceException, TransitDataset, TransitMode,
    TransitRoute, TransitStop, TransitStopTime, TransitTrip,
)
from transit_engine import BatchSearchRequest, PythonTransitSearchCore, SearchEndpoint
from transit_network import DirectedWalkLink, NetworkCosts, build_transit_network, physical_node
from transit_timetable_choices import (
    DatasetTimetableChoices, NetworkRideEvent, NetworkSearchParameters,
    NetworkWalkEvent, search_network,
)
from yokohama_shared_network import build_shared_municipal_network, search_shared_municipal_network
from tests.test_transit_network_experiment import feeds, LINKS
from tests.test_yokohama_municipal_transfer import _feed, JST
from yokohama_municipal_transfer import ExplicitTransferLink, search_explicit_municipal_transfer


SERVICE_DAY = date(2026, 10, 14)
FIXTURE_EVIDENCE = "https://www.city.yokohama.lg.jp/fake-fixture-not-real"


def dataset(feed, trips, *, mode=TransitMode.BUS):
    stops = {stop for rows in trips.values() for stop, *_ in rows}
    metadata = FeedMetadata(feed, "gtfs", "https://example.invalid/fixture", "fixture-v1",
                            datetime(2026, 10, 14, tzinfo=timezone.utc))
    return TransitDataset(
        metadata,
        {f"{feed}:{s}": TransitStop(f"{feed}:{s}", s, s, 35.0, 139.0) for s in stops},
        {f"{feed}:r": TransitRoute(f"{feed}:r", "r", "R", "Fixture", mode)},
        {f"{feed}:{t}": TransitTrip(f"{feed}:{t}", t, f"{feed}:r", f"{feed}:s", "") for t in trips},
        tuple(TransitStopTime(f"{feed}:{t}", f"{feed}:{s}", index * 5 + 1, a, d, *flags)
              for t, rows in trips.items() for index, (s, a, d, *flags) in enumerate(rows)),
        {f"{feed}:s": ServiceCalendar(f"{feed}:s", "s", (True,) * 7,
                                     date(2026, 1, 1), date(2026, 12, 31))},
    )


def network(*datasets, allowed=None, links=()):
    return build_transit_network(datasets, allowed_trip_ids=(
        frozenset(t for d in datasets for t in d.trips) if allowed is None else allowed),
        walking_links=links, costs=NetworkCosts())


def query(snapshot, origin, destination, *, mode="time", day=SERVICE_DAY, departure=590, **params):
    with contextlib.redirect_stdout(io.StringIO()):
        return search_network(snapshot, origin, destination, service_date=day,
                              departure_minute=departure, mode=mode,
                              parameters=NetworkSearchParameters(**params))


class TransitNetworkTest(unittest.TestCase):
    def test_preparation_deadline_and_exact_query_local_board_cache(self):
        source = dataset("bus", {"t": [("a", 600, 600), ("b", 610, 610)]})
        snapshot = network(source)
        choices = DatasetTimetableChoices(snapshot, service_date=SERVICE_DAY, deadline=830)
        edge = next(iter(snapshot.departures))
        with self.assertRaisesRegex(RouteContractError, "explicit deadline-scoped"):
            choices.board_options(*edge, 590)
        error = RouteSearchLimitError("preparation deadline", reason="time_limit_sec")
        def expired():
            raise error
        with self.assertRaises(RouteSearchLimitError) as raised:
            choices.prepare(expired)
        self.assertIs(raised.exception, error)
        self.assertIsNone(choices.active_trips)
        # A separate provider represents a separate query, not recovery of it.
        choices = DatasetTimetableChoices(snapshot, service_date=SERVICE_DAY, deadline=830)
        choices.prepare(lambda: None)
        first = choices.board_options(*edge, 590)
        self.assertIs(first, choices.board_options(*edge, 590))
        self.assertEqual(choices.board_options(*edge, 600.01), ())
        with self.assertRaisesRegex(RouteContractError, "already prepared"):
            choices.prepare(lambda: None)

    def test_dwell_and_later_faster_trip_are_preserved(self):
        source = dataset("bus", {
            "slow": [("a", 600, 600), ("b", 610, 640), ("c", 660, 660)],
            "fast": [("a", 605, 605), ("b", 615, 620), ("c", 630, 630)],
        })
        snapshot = network(source)
        journey = query(snapshot, "bus:a", "bus:c")[0]
        self.assertEqual(journey.arrival_minute, 630)
        self.assertEqual(journey.events[0].trip_id, "bus:fast")
        self.assertEqual(journey.events[0].stop_ids, ("bus:a", "bus:b", "bus:c"))
        onboard = query(snapshot, "bus:b", "bus:c", departure=616)[0].events[0]
        self.assertEqual(onboard.departure_minute, 620)

    def test_circular_occurrences_and_original_sequences(self):
        source = dataset("bus", {"loop": [
            ("a", 600, 600), ("b", 610, 610), ("a", 620, 620, 1, 0), ("c", 630, 630),
        ]})
        for mode in ("time", "cost", "fewTransfers"):
            with self.subTest(mode=mode):
                event = query(network(source), "bus:a", "bus:c", mode=mode)[0].events[0]
                self.assertEqual(event.stop_ids, ("bus:a", "bus:b", "bus:a", "bus:c"))
                self.assertEqual((event.from_sequence, event.to_sequence), (1, 16))
                self.assertEqual(event.source_trip_id, "loop")

    def test_pattern_graph_does_not_expand_per_trip(self):
        source = dataset("bus", {str(i): [("a", 600, 600), ("b", 610, 610)] for i in range(100)})
        snapshot = network(source)
        self.assertEqual(len(snapshot.graph), 4)
        self.assertEqual(len(set(snapshot.trip_patterns.values())), 1)
        self.assertEqual(len(next(iter(snapshot.departures.values()))), 100)

    def test_pickup_dropoff_and_conditional_service_are_not_boarding_points(self):
        for pickup, dropoff in ((1, 1), (2, 3)):
            with self.subTest(pickup=pickup, dropoff=dropoff):
                source = dataset("bus", {"t": [("a", 600, 600), ("b", 610, 610, pickup, dropoff),
                                               ("c", 620, 620)]})
                snapshot = network(source)
                self.assertEqual(query(snapshot, "bus:a", "bus:c")[0].arrival_minute, 620)
                self.assertEqual(query(snapshot, "bus:b", "bus:c"), ())
                self.assertEqual(query(snapshot, "bus:a", "bus:b"), ())

    def test_all_clocks_are_validated_including_excluded_trips(self):
        source = dataset("bus", {"bad": [("a", 600, 600), ("b", 610, 605)]})
        with self.assertRaisesRegex(ValueError, "arrival after departure.*bus:bad"):
            network(source, allowed=())
        source = dataset("bus", {"bad": [("a", 600, 600), ("b", 599, 610)]})
        with self.assertRaisesRegex(ValueError, "trip goes backwards"):
            network(source)
        source = dataset("bus", {"bad": [("a", 600, 600), ("b", 610, None), ("c", 620, 620)]})
        with self.assertRaisesRegex(ValueError, "missing departure"):
            network(source)

    def test_service_exceptions_and_24_plus_times(self):
        source = dataset("bus", {"t": [("a", 1430, 1430), ("b", 1450, None)]})
        source = replace(source, service_exceptions=(ServiceException("bus:s", SERVICE_DAY, 2),))
        self.assertEqual(query(network(source), "bus:a", "bus:b", departure=1420), ())
        source = replace(source, service_exceptions=(ServiceException("bus:s", SERVICE_DAY, 1),),
                         calendars={})
        event = query(network(source), "bus:a", "bus:b", departure=1420)[0].events[0]
        self.assertEqual(event.arrival_minute, 1450)
        self.assertEqual(event.service_date, SERVICE_DAY)
        source = replace(source, service_exceptions=source.service_exceptions * 2)
        with self.assertRaisesRegex(ValueError, "duplicate service exception"):
            network(source)

    def test_no_proximity_links_or_implicit_trip_scope(self):
        bus = dataset("bus", {"t": [("a", 600, 600), ("b", 610, 610)]})
        rail = dataset("rail", {"t": [("a", 620, 620), ("b", 630, 630)]}, mode=TransitMode.RAIL)
        self.assertEqual(query(network(bus, rail), "bus:a", "rail:b"), ())
        self.assertEqual(query(network(bus, allowed=()), "bus:a", "bus:b"), ())
        with self.assertRaisesRegex(ValueError, "explicit trip-ID"):
            build_transit_network(
                (bus,), allowed_trip_ids=None, walking_links=(), costs=NetworkCosts())
        with self.assertRaisesRegex(ValueError, "unknown allowed"):
            network(bus, allowed={"bus:missing"})

    def test_zero_meter_reviewed_walk_retains_exact_zero_resource(self):
        source = dataset("bus", {"t": [("a", 600, 600), ("b", 610, 610)]})
        link = DirectedWalkLink(ReviewedWalkingLink("bus:a", "bus:b", 0, 0,
                                                   FIXTURE_EVIDENCE, True), "fixture-v1", "fixture-v1")
        journey = query(network(source, allowed=(), links=(link,)), "bus:a", "bus:b",
                        max_total_walk_meters=0, max_segment_walk_meters=0)[0]
        self.assertEqual(journey.walk_meters, 0)
        self.assertEqual(journey.arrival_minute, 590)
        self.assertIsInstance(journey.events[0], NetworkWalkEvent)

    def test_boarding_cap_retains_later_prefix_with_fewer_boardings(self):
        source = dataset("bus", {
            "early1": [("a", 600, 600), ("x", 605, 605)],
            "early2": [("x", 605, 605), ("m", 610, 610)],
            "later": [("a", 600, 600), ("m", 620, 620)],
            "last": [("m", 620, 620), ("d", 630, 630)],
        })
        result = query(network(source), "bus:a", "bus:d", max_boardings=2)[0]
        self.assertEqual([e.trip_id for e in result.events], ["bus:later", "bus:last"])

    def test_snapshot_isolated_from_mutable_inputs_and_public_graph_edits(self):
        source = dataset("bus", {"t": [("a", 600, 600), ("b", 610, 610)]})
        snapshot = network(source)
        source.trips.clear()
        source.calendars.clear()
        self.assertEqual(query(snapshot, "bus:a", "bus:b")[0].arrival_minute, 610)
        with self.assertRaises(TypeError):
            snapshot.graph.nodes[physical_node("bus:a")]["lat"] = 0
        with self.assertRaises(nx.NetworkXError):
            snapshot.graph.add_node("other")
        with self.assertRaises(TypeError):
            snapshot.trips["bus:t"] = None

    def test_rail_preparation_past_deadline_yields_no_boarding(self):
        source = dataset("rail", {"t": [("a", 600, 600), ("b", 610, 610)]}, mode=TransitMode.RAIL)
        self.assertEqual(query(network(source), "rail:a", "rail:b", departure=599,
                               max_travel_minutes=2, rail_boarding_minutes=3), ())

    def test_fastest_matches_existing_v1_selected_trip_and_clocks(self):
        source = dataset("bus", {"slow": [("a", 600, 600), ("b", 660, 660)],
                                 "fast": [("a", 605, 605), ("b", 630, 630)]})
        previous = PythonTransitSearchCore(source).search(BatchSearchRequest(
            SERVICE_DAY, 590, (SearchEndpoint("bus:a"),), (SearchEndpoint("bus:b"),), "fastest"))
        event = query(network(source), "bus:a", "bus:b")[0].events[0]
        leg = previous.pairs[0].itinerary.legs[0]
        self.assertEqual((event.trip_id, event.departure_minute, event.arrival_minute),
                         (leg.trip_id, leg.departure_minute, leg.arrival_minute))

    def test_few_transfers_city_tiebreak_is_explicit_and_matches_v1_arrival(self):
        source = dataset("bus", {"fast": [("a", 600, 600), ("x", 605, 605), ("b", 610, 610)],
                                 "cheap": [("a", 600, 600), ("b", 620, 620)]})
        snapshot = network(source)
        comfort = query(snapshot, "bus:a", "bus:b", mode="fewTransfers")[0]
        arrival = query(snapshot, "bus:a", "bus:b", mode="fewTransfers", few_transfers_tiebreak="arrival")[0]
        previous = PythonTransitSearchCore(source).search(BatchSearchRequest(
            SERVICE_DAY, 590, (SearchEndpoint("bus:a"),), (SearchEndpoint("bus:b"),), "fewest_transfers"))
        self.assertEqual(comfort.events[0].trip_id, "bus:cheap")
        self.assertEqual(arrival.events[0].trip_id, previous.pairs[0].itinerary.legs[0].trip_id)
        self.assertEqual(arrival.arrival_minute, 610)

    def test_two_directed_walks_and_three_rides_delegate_to_common_core(self):
        with tempfile.TemporaryDirectory() as root:
            sources = feeds(Path(root))
            datasets = tuple(source.load() for source in sources)
            # Explicit adaptation of synthetic test evidence, not production reviews.
            links = tuple(DirectedWalkLink(x.link, x.from_feed_version, x.to_feed_version) for x in LINKS)
            snapshot = network(*datasets, links=links)
            fastest = query(snapshot, "demo_bus:a", "demo_bus:d", departure=595)[0]
            self.assertEqual(fastest.arrival_minute, 655)
            self.assertEqual(fastest.rides, 3)
            walks = [event for event in fastest.events if isinstance(event, NetworkWalkEvent)]
            self.assertEqual(len(walks), 2)
            self.assertEqual([(e.departure_minute, e.arrival_minute) for e in walks], [(610, 620), (631, 641)])
            self.assertEqual(fastest.walk_meters, 480)
            few = query(snapshot, "demo_bus:a", "demo_bus:d", mode="fewTransfers", departure=595)[0]
            self.assertEqual((few.rides, few.arrival_minute), (1, 680))
            comfort = query(snapshot, "demo_bus:a", "demo_bus:d", mode="cost", departure=595)
            self.assertEqual(comfort[0].rides, 1)
            self.assertGreater(len(comfort), 1)

    def test_gtfs_optional_flags_are_preserved_and_invalid_flags_stop_loading(self):
        with tempfile.TemporaryDirectory() as root:
            sources = feeds(Path(root))
            path = Path(root) / "stop_times.txt"
            text = path.read_text()
            lines = text.splitlines()
            lines[0] += ",pickup_type,drop_off_type"
            lines[1] += ",1,2"
            path.write_text("\n".join(lines))
            loaded = sources[0].load()
            self.assertEqual((loaded.stop_times[0].pickup_type, loaded.stop_times[0].drop_off_type), (1, 2))
            self.assertEqual(loaded.stop_times[0].arrival_service_seconds, 36000)
            path.write_text(path.read_text().replace(",1,2", ",invalid,2"))
            with self.assertRaisesRegex(ValueError, "invalid GTFS pickup_type"):
                sources[0].load()

    def test_subminute_source_times_are_retained_and_not_silently_rounded_in_v2(self):
        with tempfile.TemporaryDirectory() as root:
            sources = feeds(Path(root))
            path = Path(root) / "stop_times.txt"
            path.write_text(path.read_text().replace("10:00:00", "10:00:59"))
            loaded = sources[0].load()
            self.assertEqual(loaded.stop_times[0].arrival_service_seconds, 36059)
            self.assertEqual(loaded.stop_times[0].arrival_minute, 601)  # existing v1 contract
            snapshot = network(loaded)
            self.assertEqual(snapshot.rows_by_trip['demo_bus:t1'][0].arrival_minute, Fraction(36059, 60))
            journey = query(snapshot, 'demo_bus:a', 'demo_bus:b')[0]
            self.assertEqual(journey.events[0].departure_minute, Fraction(36059, 60))

    def test_odpt_source_seconds_are_retained_in_exact_scheduled_clock(self):
        with tempfile.TemporaryDirectory() as root:
            sources = feeds(Path(root))
            first = sources[1].train_timetables[0]["odpt:trainTimetableObject"][0]
            first["odpt:arrivalTime"] = first["odpt:departureTime"] = "10:19:59"
            loaded = sources[1].load()
            self.assertEqual(loaded.stop_times[0].departure_service_seconds, 37199)
            self.assertEqual(loaded.stop_times[0].departure_minute, 620)
            snapshot = network(loaded)
            self.assertEqual(snapshot.rows_by_trip['demo_rail:early'][0].departure_minute, Fraction(37199, 60))

    def test_exact_walking_and_boarding_boundary_in_all_objectives(self):
        def seconds_dataset(feed, trips, **kwargs):
            source = dataset(feed, trips, **kwargs)
            return replace(source, stop_times=tuple(replace(
                row, arrival_minute=(row.arrival_minute + 30) // 60,
                departure_minute=(row.departure_minute + 30) // 60,
                arrival_service_seconds=row.arrival_minute,
                departure_service_seconds=row.departure_minute) for row in source.stop_times))
        bus = seconds_dataset('bus', {'t': [('a', 33000, 33000), ('b', 33659, 33659)]})
        rail = seconds_dataset('rail', {
            'early': [('c', 34276, 34276), ('d', 34400, 34400)],
            'equal': [('c', 34277, 34277), ('d', 34501, 34501)],
        }, mode=TransitMode.RAIL)
        link = DirectedWalkLink(ReviewedWalkingLink(
            from_stop_id='bus:b', to_stop_id='rail:c', walk_meters=100,
            walk_minutes=10, official_evidence_url=FIXTURE_EVIDENCE,
            includes_station_access=True),
            'fixture-v1', 'fixture-v1')
        snapshot = network(bus, rail, links=(link,))
        for mode in ('time', 'fewTransfers', 'cost'):
            journey = query(snapshot, 'bus:a', 'rail:d', mode=mode, departure=540,
                            bus_alighting_minutes=0.1, rail_boarding_minutes=0.2)[0]
            self.assertEqual([e.trip_id for e in journey.events if isinstance(e, NetworkRideEvent)],
                             ['bus:t', 'rail:equal'])
            self.assertEqual(journey.arrival_minute, Fraction(34501, 60))
            self.assertIsInstance(journey.arrival_minute, Fraction)
            self.assertEqual(journey.walk_meters, 100)

    def test_source_order_is_checked_before_minute_rounding(self):
        source = dataset('bus', {'t': [('a', 600, 600), ('b', 600, 600)]})
        rows = tuple(replace(r, arrival_service_seconds=36020 if i == 0 else 36019,
                             departure_service_seconds=36020 if i == 0 else 36019)
                     for i, r in enumerate(source.stop_times))
        with self.assertRaisesRegex(ValueError, 'trip goes backwards.*bus:t'):
            network(replace(source, stop_times=rows))

    def test_source_clock_mismatch_is_not_repaired(self):
        source = dataset('bus', {'t': [('a', 600, 600), ('b', 610, 610)]})
        bad = replace(source.stop_times[0], departure_service_seconds=36059)
        with self.assertRaisesRegex(ValueError, 'source seconds/minutes mismatch.*bus:t'):
            network(replace(source, stop_times=(bad, source.stop_times[1])))

    def test_source_dwell_is_checked_at_second_precision(self):
        source = dataset('bus', {'t': [('a', 600, 600), ('b', 610, 610)]})
        bad = replace(source.stop_times[0], arrival_service_seconds=36020,
                      departure_service_seconds=36019)
        with self.assertRaisesRegex(ValueError, 'arrival after departure.*bus:t'):
            network(replace(source, stop_times=(bad, source.stop_times[1])))

    def test_exact_departure_and_service_day_across_midnight(self):
        source = dataset('bus', {'t': [('a', 1440, 1440), ('b', 1440, 1440)]})
        rows = tuple(replace(r, arrival_service_seconds=s, departure_service_seconds=s)
                     for r, s in zip(source.stop_times, (86399, 86401)))
        snapshot = network(replace(source, stop_times=rows))
        for start in (Fraction(86398, 60), Fraction(86399, 60)):
            journey = query(snapshot, 'bus:a', 'bus:b', departure=start)[0]
            self.assertEqual(journey.arrival_minute, Fraction(86401, 60))
            self.assertEqual(journey.events[0].service_date, SERVICE_DAY)
        self.assertEqual(query(snapshot, 'bus:a', 'bus:b', departure=Fraction(86400, 60)), ())

    def test_query_clock_rejects_unknown_types_and_nonfinite_values(self):
        snapshot = network(dataset('bus', {'t': [('a', 600, 600), ('b', 610, 610)]}))
        for clock in (True, '600', float('nan'), float('inf'), -1):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                query(snapshot, 'bus:a', 'bus:b', departure=clock)


class YokohamaSharedNetworkTest(unittest.TestCase):
    def setUp(self):
        bus_dir, rail_dir = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(bus_dir.cleanup)
        self.addCleanup(rail_dir.cleanup)
        self.bus = _feed(Path(bus_dir.name), rail=False)
        self.rail = _feed(Path(rail_dir.name), rail=True)
        self.link = DirectedWalkLink(ReviewedWalkingLink(
            "yokohama_bus:B", "yokohama_subway:S", 120, 3, FIXTURE_EVIDENCE, True),
            "synthetic-v1", "synthetic-v1")

    def context(self, policy, links=None, bus=None):
        return build_shared_municipal_network(
            self.bus if bus is None else bus, self.rail, policy_id=policy,
            walking_links=(self.link,) if links is None else links, costs=NetworkCosts())

    def search(self, context, origin="yokohama_bus:O", destination="yokohama_subway:D"):
        with contextlib.redirect_stdout(io.StringIO()):
            return search_shared_municipal_network(
                context, origin, destination, service_date=SERVICE_DAY,
                departure_minute=540, mode="time", parameters=NetworkSearchParameters())

    def test_both_passes_match_existing_reviewed_handoff_and_exclude_faster_sightseeing(self):
        for policy in ("yokohama_welfare_special_pass", "yokohama_senior_special_pass"):
            with self.subTest(policy=policy):
                context = self.context(policy)
                result = self.search(context)[0]
                previous = search_explicit_municipal_transfer(
                    bus_coverage=self.bus, subway_coverage=self.rail,
                    origin_stop_id="yokohama_bus:O", destination_stop_id="yokohama_subway:D",
                    depart_at=datetime(2026, 10, 14, 9, 0, tzinfo=JST), policy_id=policy,
                    transfer=ExplicitTransferLink("yokohama_bus:B", "yokohama_subway:S", 120, 3,
                                                  FIXTURE_EVIDENCE))
                self.assertEqual(result.arrival_minute, previous.final_arrival_minute)
                self.assertEqual([e.trip_id for e in result.events if isinstance(e, NetworkRideEvent)],
                                 [e.trip_id for e in (*previous.first_legs, *previous.second_legs)])
                self.assertNotIn("yokohama_bus:EXPRESS", context.snapshot.allowed_trip_ids)

    def test_reverse_direction_and_empty_review_are_not_implicitly_enabled(self):
        policy = "yokohama_welfare_special_pass"
        self.assertEqual(self.search(self.context(policy, links=())), ())
        context = self.context(policy)
        self.assertFalse(context.snapshot.graph.has_edge(
            physical_node("yokohama_subway:S"), physical_node("yokohama_bus:B")))
        self.assertEqual(self.search(context, "yokohama_subway:S", "yokohama_bus:O"), ())

    def test_empty_trip_level_approval_does_not_revert_to_v1_route_approval(self):
        bus = replace(self.bus, reviewed_free_trip_uris={})
        context = self.context("yokohama_senior_special_pass", bus=bus)
        self.assertFalse(any(t.startswith("yokohama_bus:") for t in context.snapshot.allowed_trip_ids))
        self.assertEqual(self.search(context), ())

    def test_mismatched_version_and_legacy_bidirectional_review_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "feed version mismatch"):
            self.context("yokohama_welfare_special_pass", links=(replace(self.link, to_feed_version="old"),))
        with self.assertRaisesRegex(ValueError, "version-pinned directed"):
            self.context("yokohama_welfare_special_pass", links=(
                ExplicitTransferLink("yokohama_bus:B", "yokohama_subway:S", 120, 3, FIXTURE_EVIDENCE),))
