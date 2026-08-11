import unittest

from app.services.route_step_ids import assign_candidate_step_ids


class RouteStepIdsTest(unittest.TestCase):
    def test_assigns_unique_ids_to_every_step(self):
        values = iter(["walk-a", "wait-b", "bus-c", "walk-d"])
        candidate = {
            "steps": [
                {"kind": "walk"},
                {"kind": "wait"},
                {"kind": "bus"},
                {"kind": "walk"},
            ]
        }

        assign_candidate_step_ids(candidate, id_factory=lambda: next(values))

        self.assertEqual(
            [step["step_id"] for step in candidate["steps"]],
            [
                "step-walk-walk-a",
                "step-wait-wait-b",
                "step-bus-bus-c",
                "step-walk-walk-d",
            ],
        )


if __name__ == "__main__":
    unittest.main()
