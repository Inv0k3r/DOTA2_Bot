import unittest
from unittest.mock import patch

import DOTA2
from player import player


class Dota2Test(unittest.TestCase):
    def test_match_details_fall_back_to_steam(self):
        expected = {"match_id": 123, "players": []}
        with patch.object(
            DOTA2,
            "_get_match_detail_from_opendota",
            side_effect=DOTA2.DOTA2HTTPError("OpenDota unavailable"),
        ), patch.object(
            DOTA2,
            "_get_match_detail_from_steam",
            return_value=expected,
        ):
            self.assertIs(DOTA2.get_match_detail_info(123), expected)

    def test_generate_report_from_opendota_compatible_match(self):
        tracked = player("测试玩家", 42, 76561197960265770, 122)
        match = {
            "match_id": 123,
            "start_time": 1_700_000_000,
            "duration": 1800,
            "game_mode": 1,
            "lobby_type": 7,
            "radiant_win": True,
            "players": [
                {
                    "player_slot": 128,
                    "kills": 1,
                    "deaths": 2,
                    "assists": 3,
                    "hero_damage": 1000,
                },
                {
                    "account_id": 42,
                    "player_slot": 0,
                    "kills": 4,
                    "deaths": 3,
                    "assists": 10,
                    "hero_id": 1,
                    "last_hits": 123,
                    "hero_damage": 20000,
                    "gold_per_min": 500,
                    "xp_per_min": 600,
                }
            ],
        }
        with patch.object(DOTA2, "get_match_detail_info", return_value=match), \
                patch('report_builder.choose_custom_comment', return_value=None), \
                patch('report_builder.display_name', side_effect=lambda _id, name, _match: name), \
                patch('report_builder.persist_and_summarize', return_value=[]):
            report = DOTA2.generate_match_message(123, [tracked])

        self.assertIn("测试玩家", report)
        self.assertIn("4/3/10", report)
        self.assertEqual(tracked.kda, 14 / 3)

    def test_merge_party_members_into_one_report(self):
        first = player("甲", 42, 76561197960265770, 122)
        second = player("乙", 43, 76561197960265771, 122)
        match = {
            "match_id": 123,
            "start_time": 1_700_000_000,
            "duration": 1800,
            "game_mode": 1,
            "lobby_type": 7,
            "radiant_win": True,
            "players": [
                {"account_id": 42, "player_slot": 0, "kills": 8, "deaths": 0,
                 "assists": 12, "hero_id": 1, "hero_damage": 24000,
                 "gold_per_min": 600, "xp_per_min": 700, "last_hits": 180},
                {"account_id": 43, "player_slot": 1, "kills": 4, "deaths": 3,
                 "assists": 15, "hero_id": 2, "hero_damage": 16000,
                 "gold_per_min": 480, "xp_per_min": 560, "last_hits": 80},
            ],
        }
        with patch.object(DOTA2, "get_match_detail_info", return_value=match), \
                patch('report_builder.choose_custom_comment', return_value=None), \
                patch('report_builder.display_name', side_effect=lambda _id, name, _match: name), \
                patch('report_builder.persist_and_summarize', return_value=[]):
            report = DOTA2.generate_match_message(123, [first, second])

        self.assertIn("发现2人组队开黑：甲、乙", report)
        self.assertIn("✅ 甲", report)
        self.assertIn("零死", report)
        self.assertNotIn("DOTA2 战报", report)


if __name__ == "__main__":
    unittest.main()
