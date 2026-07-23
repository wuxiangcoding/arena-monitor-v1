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


class FeishuTests(unittest.TestCase):
    def test_card_contains_change_and_source_link(self):
        event = arena_monitor.ChangeEvent(
            board="webdev",
            kind="entered_top",
            model="Alpha",
            old_rank=4,
            new_rank=3,
            boundary=3,
        )
        snapshot = {
            "fetched_at": "2026-07-23T14:00:00Z",
            "boards": {
                "webdev": {
                    "publish_date": "2026-07-23",
                }
            },
        }

        card = arena_monitor.build_feishu_card([event], snapshot)
        serialized = str(card)

        self.assertIn("Arena 榜单变动简报", serialized)
        self.assertIn("Alpha", serialized)
        self.assertIn("Top 3", serialized)
        self.assertIn(arena_monitor.BOARDS["webdev"]["url"], serialized)

    def test_feishu_sender_uses_interactive_card(self):
        calls = []

        def fake_post(url, payload):
            calls.append((url, payload))
            return {"code": 0, "msg": "success"}

        arena_monitor.send_feishu_card(
            "https://example.invalid/webhook",
            {"elements": []},
            post=fake_post,
        )

        self.assertEqual(calls[0][1]["msg_type"], "interactive")
        self.assertEqual(calls[0][1]["card"], {"elements": []})

    def test_feishu_sender_raises_on_api_error(self):
        def fake_post(url, payload):
            return {"code": 19024, "msg": "Key Words Not Found"}

        with self.assertRaisesRegex(RuntimeError, "19024"):
            arena_monitor.send_feishu_card(
                "https://example.invalid/webhook",
                {"elements": []},
                post=fake_post,
            )


if __name__ == "__main__":
    unittest.main()
