"""Absolute-clock priorities stay below actual float timetable arrivals."""

from __future__ import annotations

import math
import random
import unittest
from fractions import Fraction

from tokyo_time_rounding import TimeRoundingGuard


def _guard(start, deadline, steps, maximum, reverse=None):
    return TimeRoundingGuard(start_minute=start, deadline=deadline,
                             max_forward_steps=steps,
                             max_reverse_steps=steps + 1 if reverse is None else reverse,
                             max_edge_minutes=maximum)


def _raw_interval(departure, arrival):
    duration = arrival - departure
    return max(0.0, math.nextafter(duration, -math.inf)) if duration else 0.0


class TokyoTimeRoundingTest(unittest.TestCase):
    def test_goal_and_zero_bound_keep_the_original_clock_exactly(self):
        guard = _guard(600, 840, 200000, 240)
        for current in (600.0, 683.2873359962757, 840.0):
            self.assertEqual(guard(current, 0.0), current)
            self.assertEqual(guard(current, -0.0), current)

    def test_static_timetable_arrival_assignment_is_not_a_zero_started_sum(self):
        start, departure, arrival = 598.0, 600.0, 610.0
        guard = _guard(start, 838, 10, 10)
        # Ready plus preparation waits for the stored departure; the ride then
        # assigns the stored arrival clock, and alighting adds one minute.
        actual_goal = arrival + 1.0
        self.assertLessEqual(guard(start, 2.0 + _raw_interval(departure, arrival) + 1.0), actual_goal)
        self.assertLessEqual(guard(departure, _raw_interval(departure, arrival) + 1.0), actual_goal)

    def test_raw_ride_interval_and_shifted_endpoint_rounding_have_a_real_counterexample(self):
        departure, arrival, delay = 575.8869929427119, 579.1059658896453, 6.038374834740296
        current, actual_goal = departure + delay, arrival + delay
        remaining = _raw_interval(departure, arrival)
        self.assertGreater(current + remaining, actual_goal)
        guard = _guard(580, 820, 1, remaining)
        self.assertLessEqual(guard(current, remaining), actual_goal)

    def test_bus_derived_delay_need_not_equal_original_route_delay(self):
        board_departure, requested_delay = 970.0, 28.281880106322717
        board_clock = board_departure + requested_delay
        derived_delay = board_clock - board_departure
        self.assertNotEqual(derived_delay, requested_delay)
        departure, arrival = 998.771439314174, 1005.6149419895675
        current, actual_goal = departure + derived_delay, arrival + derived_delay
        remaining = _raw_interval(departure, arrival)
        self.assertGreater(current + remaining, actual_goal)
        guard = _guard(995, 1235, 8, 40)
        self.assertLessEqual(guard(current, remaining), actual_goal)

    def test_real_bus_choices_use_the_same_derived_offset_at_both_ride_endpoints(self):
        from tests import test_tokyo_bus_choices_contract as bus
        graph = bus._graph(("A", "B"), ("B", "C"))
        departure, arrival = 998.771439314174, 1005.6149419895675
        repository = bus._repository((
            "through", "active", (("A", 970, 970), ("B", departure, departure),
                                   ("C", arrival, arrival)),
        ))
        manager = bus.engine.TimetableManager()
        requested_delay = 28.281880106322717
        manager.bus_realtime_delays[bus.ROUTE] = requested_delay
        choices, options = bus._choices(graph, repository, manager=manager, ready=995,
                                       deadline=1235, use_realtime=True)
        current, state = options[0]
        derived_delay = state.departure_minute - 970.0
        self.assertNotEqual(derived_delay, requested_delay)
        current, state = choices.ride_options(bus._line("A"), bus._line("B"), current, state)[0]
        final_clock, state = choices.ride_options(bus._line("B"), bus._line("C"), current, state)[0]
        self.assertEqual(current, departure + derived_delay)
        self.assertEqual(final_clock, arrival + derived_delay)
        remaining = _raw_interval(departure, arrival)
        self.assertGreater(current + remaining, final_clock)
        self.assertLessEqual(_guard(995, 1235, 12, 40)(current, remaining), final_clock)
        self.assertEqual(state.trip_id, "through")

    def test_each_small_clock_addition_can_round_away_a_positive_duration(self):
        current = 1e16
        increments = [0.6] * 10
        actual_goal = current
        for increment in increments:
            actual_goal += increment
        remaining = 0.0
        for increment in reversed(increments):
            remaining += increment
        self.assertEqual(actual_goal, current)
        self.assertGreater(current + remaining, actual_goal)
        guard = _guard(current, current + 240, len(increments), 0.6)
        self.assertEqual(guard(current, remaining), actual_goal)

    def test_dwell_waiting_and_absolute_ride_clock_keep_the_bound_optimistic(self):
        current, departure, arrival, delay = 604.0, 606.0, 610.0, 2.25
        actual_goal = arrival + delay
        # Current can precede the pinned departure; ignoring dwell/wait is a
        # relaxation, not an instruction to switch to another run.
        guard = _guard(600, 840, 4, 4)
        self.assertLessEqual(guard(current, _raw_interval(departure, arrival)), actual_goal)

    def test_fixed_error_does_not_prefer_a_different_prefix_at_equal_estimated_clock(self):
        guard = _guard(600, 840, 200000, 240)
        self.assertEqual(guard(600.0, 10.0), guard(605.0, 5.0))

    def test_near_tie_still_places_a_legal_prefix_before_a_later_goal(self):
        start = 600.0
        actual_goal = (start + 0.1) + 0.1
        later_goal = math.nextafter(actual_goal, math.inf)
        guard = _guard(start, 840, 10, 0.2)
        prefix_priority = guard(start + 0.1, 0.1)
        self.assertLessEqual(prefix_priority, actual_goal)
        self.assertLess(prefix_priority, guard(later_goal, 0.0))
        self.assertEqual(math.ceil(actual_goal), math.ceil(later_goal))

    def test_query_clock_range_and_nonfinite_values_disable_only_the_heuristic(self):
        guard = _guard(600, 840, 100, 2)
        for clock in (-1.0, 599.0, 841.0, math.inf, -math.inf):
            self.assertEqual(guard(clock, 1), clock)
        self.assertTrue(math.isnan(guard(math.nan, 1)))
        for bound in (-1.0, math.inf, math.nan, "invalid", 1000.0):
            self.assertEqual(guard(610, bound), 610.0)

    def test_invalid_parameters_or_overflow_disable_the_heuristic(self):
        for overrides in (
                {"start_minute": -1}, {"deadline": 599}, {"deadline": math.inf},
                {"max_forward_steps": -1}, {"max_reverse_steps": 0.5},
                {"max_reverse_steps": 2**53}, {"max_edge_minutes": math.inf},
                {"max_edge_minutes": -1}, {"max_edge_minutes": 1e308}):
            with self.subTest(overrides=overrides):
                arguments = dict(start_minute=600, deadline=840, max_forward_steps=100,
                                 max_reverse_steps=100, max_edge_minutes=2)
                arguments.update(overrides)
                guard = TimeRoundingGuard(**arguments)
                self.assertFalse(guard.report["enabled"])
                self.assertEqual(guard(610, 1), 610.0)

    def test_reverse_error_is_rounded_up_against_independent_real_sum(self):
        guard = _guard(600, 840, 1000, 6, reverse=1000)
        self.assertTrue(guard.report["enabled"])
        exact_reverse_error = Fraction(1000, 2**53 - 1000) * 6000
        self.assertGreaterEqual(Fraction.from_float(guard.report["reverse_error_minutes"]),
                                exact_reverse_error)
        self.assertGreaterEqual(guard.report["transition_error_minutes"],
                                1000 * math.ulp(840.0))

    def test_seeded_mixed_clock_additions_and_timetable_assignments_are_admissible(self):
        randomizer = random.Random(20261005)
        checked = 0
        for case in range(400):
            start = randomizer.uniform(0, 2000)
            deadline = start + 240
            clocks, weights = [start], []
            for _ in range(randomizer.randint(1, 30)):
                current = clocks[-1]
                if randomizer.randrange(2):
                    duration = randomizer.choice((0.0, 0.0125, 0.1, 0.2, 1.0, 2.0, 3.25))
                    following, weight = current + duration, duration
                else:
                    delay = randomizer.uniform(-20, 40)
                    departure = current - delay
                    while departure + delay < current:
                        departure = math.nextafter(departure, math.inf)
                    arrival = departure + randomizer.uniform(0, 5)
                    following = arrival + delay
                    weight = _raw_interval(departure, arrival)
                self.assertGreaterEqual(following, current)
                self.assertLessEqual(following, deadline)
                clocks.append(following)
                weights.append(weight)
            guard = _guard(start, deadline, len(weights), max(weights))
            for index, current in enumerate(clocks):
                remaining = 0.0
                for weight in reversed(weights[index:]):
                    remaining += weight
                self.assertLessEqual(guard(current, remaining), clocks[-1],
                                     (case, index, clocks, weights))
                checked += 1
        self.assertGreater(checked, 5000)


if __name__ == "__main__":
    unittest.main()
