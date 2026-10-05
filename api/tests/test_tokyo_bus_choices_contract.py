"""Concrete Tokyo bus choices retain a GTFS trip and stop occurrence."""

import contextlib
import datetime
import io
import unittest
from unittest.mock import patch

import networkx as nx

import toei_engine as engine
from gtfs_loader import GtfsRepository
from tokyo_timetable_choices import TimetableChoices


ROUTE = "R"
LINE = "buspat:test"


def _phys(stop):
    return ("phys", stop)


def _line(stop):
    return ("line", stop, LINE)


def _graph(*pairs):
    graph = nx.DiGraph()
    for left, right in pairs:
        for stop in (left, right):
            graph.add_node(_phys(stop), name=stop, name_en=stop,
                           lat=35.0, lon=139.0)
            graph.add_node(_line(stop), name=stop, mode="bus", route_id=ROUTE,
                           disp="Test bus", disp_en="Test bus")
            graph.add_edge(_phys(stop), _line(stop), etype="board",
                           w=engine.TRANSFER_PENALTY)
            graph.add_edge(_line(stop), _phys(stop), etype="alight", w=0.0)
        graph.add_edge(_line(left), _line(right), etype="ride", mode="bus",
                       w=engine.BUS_RIDE_COST)
    return graph


def _repository(*trips):
    """A trip is (id, service_id, [(stop, arrival, departure), ...])."""
    repository = GtfsRepository("tokyo-test")
    repository.routes[ROUTE] = {"route_short_name": "Test"}
    for trip_id, service_id, stops in trips:
        repository.trips[trip_id] = {
            "route_id": ROUTE, "service_id": service_id, "headsign": stops[-1][0],
        }
        for sequence, (stop, arrival, departure) in enumerate(stops, 1):
            repository.stops[stop] = {"name": stop, "name_en": stop}
            repository.stop_times[trip_id][sequence] = (stop, arrival, departure)
            repository.timetable_index[f"{ROUTE}|{stop}"].append(
                (departure, sequence, trip_id)
            )
    for departures in repository.timetable_index.values():
        departures.sort()
    return repository


def _day(*services):
    return engine.ServiceDayType(
        "holiday", datetime.date(2026, 10, 4), frozenset(services), True,
    )


def _choices(graph, repository, *, manager=None, ready=598, deadline=838,
             services=("active",), use_realtime=False):
    manager = manager or engine.TimetableManager()
    choices = TimetableChoices(
        graph, manager, _day(*services), use_realtime=use_realtime,
        deadline=deadline, bus_repository=repository,
    )
    return choices, choices.board_options(_phys("A"), _line("A"), ready)


class TokyoBusChoicesContractTest(unittest.TestCase):
    def test_later_departure_and_earlier_arrival_is_kept_and_detailed_same_trip(self):
        graph = _graph(("A", "B"))
        repository = _repository(
            ("slow", "active", (("A", 600, 600), ("B", 620, 620))),
            ("fast", "active", (("A", 601, 601), ("B", 610, 610))),
        )
        choices, options = _choices(graph, repository)
        self.assertEqual([state.trip_id for _, state in options], ["slow", "fast"])
        arrivals = [choices.ride_options(_line("A"), _line("B"), dep, state)[0][0]
                    for dep, state in options]
        self.assertEqual(arrivals, [620, 610])

        with patch.object(engine, "gtfs_repo", repository), contextlib.redirect_stdout(io.StringIO()):
            arrival, path = engine.find_fastest_path(
                graph, engine.TimetableManager(), _phys("A"), _phys("B"),
                start_time_str="09:58", day_type=_day("active"), use_realtime=False,
            )
            detailed = engine.segments_detailed(
                graph, path, engine.TimetableManager(), "09:58", _day("active"),
                use_realtime=False,
            )
            validated_arrival = engine.calculate_real_arrival_time(
                graph, engine.TimetableManager(), path, "09:58", _day("active"),
                use_realtime=False,
            )
        self.assertEqual(arrival, 610)  # No hidden alighting minute for a GTFS bus.
        self.assertEqual(validated_arrival, arrival)
        buses = [step for step in detailed if step["kind"] == "bus"]
        self.assertEqual(len(buses), 1)
        self.assertEqual(buses[0]["trip_id"], "fast")
        self.assertEqual(buses[0]["departureStopId"], "A")
        self.assertEqual(buses[0]["arrivalPoleId"], "B")
        self.assertEqual((buses[0]["departure_time"], buses[0]["arrival_time"]),
                         ("10:01", "10:10"))

    def test_onboard_vehicle_cannot_switch_to_a_faster_trip_at_intermediate_stop(self):
        graph = _graph(("A", "B"), ("B", "C"), ("B", "A"))
        repository = _repository(
            ("through", "active", (("A", 600, 600), ("B", 605, 606), ("C", 620, 620))),
            ("later", "active", (("B", 607, 607), ("C", 608, 608))),
            ("reverse", "active", (("B", 606, 606), ("A", 609, 609))),
        )
        choices, options = _choices(graph, repository)
        departure, state = options[0]
        arrival, state = choices.ride_options(_line("A"), _line("B"), departure, state)[0]
        self.assertEqual(arrival, 605)
        self.assertFalse(choices.ride_options(_line("B"), _line("A"), arrival, state))
        arrival, state = choices.ride_options(_line("B"), _line("C"), arrival, state)[0]
        self.assertEqual((arrival, state.trip_id), (620, "through"))

    def test_revisited_stop_uses_exact_occurrence_and_midnight_clocks_do_not_wrap(self):
        graph = _graph(("A", "B"), ("B", "A"), ("A", "C"))
        repository = _repository(
            ("loop", "active", (("A", 1450, 1450), ("B", 1455, 1456),
                                 ("A", 1460, 1461), ("C", 1465, 1465))),
        )
        choices, options = _choices(graph, repository, ready=1449, deadline=1500)
        self.assertEqual([state.sequence for _, state in options], [1, 3])
        time, state = options[0]
        for left, right in (("A", "B"), ("B", "A")):
            time, state = choices.ride_options(_line(left), _line(right), time, state)[0]
        self.assertEqual((time, state.sequence), (1460, 3))
        self.assertFalse(choices.ride_options(_line("A"), _line("B"), time, state))
        time, state = choices.ride_options(_line("A"), _line("C"), time, state)[0]
        metadata = choices.metadata(state)
        self.assertEqual(time, 1465)
        self.assertEqual((metadata["board_sequence"], metadata["sequence"]), (1, 4))
        self.assertEqual(metadata["service_key"], "2026-10-04")

    def test_departure_and_continuation_share_original_deadline(self):
        graph = _graph(("A", "B"), ("B", "C"))
        repository = _repository(
            ("long", "active", (("A", 600, 600), ("B", 610, 611), ("C", 620, 620))),
            ("after", "active", (("A", 616, 616), ("B", 621, 621))),
        )
        choices, options = _choices(graph, repository, ready=600, deadline=615)
        self.assertEqual([state.trip_id for _, state in options], ["long"])
        time, state = choices.ride_options(_line("A"), _line("B"), *options[0])[0]
        self.assertFalse(choices.ride_options(_line("B"), _line("C"), time, state))

    def test_inactive_trip_is_not_boardable(self):
        graph = _graph(("A", "B"))
        repository = _repository(
            ("off", "inactive", (("A", 600, 600), ("B", 601, 601))),
            ("on", "active", (("A", 602, 602), ("B", 610, 610))),
        )
        _, options = _choices(graph, repository)
        self.assertEqual([state.trip_id for _, state in options], ["on"])

    def test_bus_delay_and_vehicle_snapshot_do_not_change_mid_query(self):
        graph = _graph(("A", "B"), ("B", "C"))
        repository = _repository(
            ("through", "active", (("A", 600, 600), ("B", 605, 606), ("C", 620, 620))),
        )
        manager = engine.TimetableManager()
        manager.bus_realtime_delays[ROUTE] = 3
        manager.latest_bus_positions = [{"vehicle_id": "V1", "trip_id": "through"}]
        choices, options = _choices(graph, repository, manager=manager, use_realtime=True)
        manager.bus_realtime_delays[ROUTE] = 100
        manager.latest_bus_positions[0]["vehicle_id"] = "V2"
        time, state = options[0]
        self.assertEqual(time, 603)
        for left, right in (("A", "B"), ("B", "C")):
            time, state = choices.ride_options(_line(left), _line(right), time, state)[0]
        self.assertEqual(time, 623)
        self.assertEqual(choices.metadata(state)["actual_arrival_minute"], 623)
        self.assertEqual(choices.manager.latest_bus_positions[0]["vehicle_id"], "V1")


if __name__ == "__main__":
    unittest.main()
