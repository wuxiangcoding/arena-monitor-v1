import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src" / "arena_monitor.py"
SPEC = importlib.util.spec_from_file_location("arena_monitor", MODULE_PATH)
arena_monitor = importlib.util.module_from_spec(SPEC)
sys.modules["arena_monitor"] = arena_monitor
assert SPEC.loader is not None
SPEC.loader.exec_module(arena_monitor)


def board(entries):
    return {
        "entries": [
            {
                "model_name": name,
                "rank": rank,
                "leaderboard_publish_date": "2026-07-23",
            }
            for name, rank in entries
        ]
    }


class ChangeDetectionTests(unittest.TestCase):
    def test_detects_selected_v1_events(self):
        previous = board(
            [
                ("Alpha", 1),
                ("Beta", 2),
                ("Gamma", 3),
                ("Delta", 4),
                ("Epsilon", 10),
                ("Zeta", 11),
                ("Removed", 20),
            ]
        )
        current = board(
            [
                ("Beta", 1),
                ("Alpha", 2),
                ("Delta", 3),
                ("Gamma", 4),
                ("Zeta", 10),
                ("Epsilon", 11),
                ("New", 18),
            ]
        )

        events = arena_monitor.detect_board_changes("text", previous, current)
        kinds = [event.kind for event in events]

        self.assertIn("added", kinds)
        self.assertIn("removed", kinds)
        self.assertIn("leader_changed", kinds)
        self.assertEqual(kinds.count("entered_top"), 2)
        self.assertEqual(kinds.count("left_top"), 2)

    def test_ignores_ordinary_rank_changes(self):
        previous = board([("Alpha", 1), ("Beta", 5), ("Gamma", 6)])
        current = board([("Alpha", 1), ("Beta", 6), ("Gamma", 5)])

        events = arena_monitor.detect_board_changes("webdev", previous, current)

        self.assertEqual(events, [])

    def test_alias_prevents_false_remove_and_add(self):
        previous = board([("Model Old Name", 4)])
        current = board([("Model New Name", 4)])
        aliases = {
            arena_monitor.normalize_name("Model Old Name"): arena_monitor.normalize_name("model"),
            arena_monitor.normalize_name("Model New Name"): arena_monitor.normalize_name("model"),
        }

        events = arena_monitor.detect_board_changes("agent", previous, current, aliases)

        self.assertEqual(events, [])

    def test_detects_top_three_and_top_ten_independently(self):
        previous = board([("Alpha", 11)])
        current = board([("Alpha", 2)])

        events = arena_monitor.detect_board_changes("image-edit", previous, current)
        boundaries = sorted(event.boundary for event in events if event.kind == "entered_top")

        self.assertEqual(boundaries, [3, 10])


if __name__ == "__main__":
    unittest.main()
