import unittest
from unittest.mock import patch

import DOTA2
from player import player


class Dota2Test(unittest.TestCase):

    @patch('DOTA2._request_json')
    def test_recent_matches_use_steam_before_opendota(self, request_json):
        request_json.return_value = {
            'result': {'matches': [{'match_id': 102}, {'match_id': 101}]}
        }

        self.assertEqual(DOTA2.get_recent_match_ids_by_short_steamID(42), [102, 101])

        request_json.assert_called_once()
        self.assertEqual(request_json.call_args.kwargs['provider'], 'Steam match history')
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
                    "account_id": 99,
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
                patch('report_builder.persist_and_summarize', return_value=[]) as persist:
            report = DOTA2.generate_match_message(123, [tracked])

        self.assertEqual(persist.call_args.kwargs['participant_account_ids'], {42, 99})
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
                 "gold_per_min": 600, "xp_per_min": 700, "last_hits": 180,
                 "party_id": 7},
                {"account_id": 43, "player_slot": 1, "kills": 4, "deaths": 3,
                 "assists": 15, "hero_id": 2, "hero_damage": 16000,
                 "gold_per_min": 480, "xp_per_min": 560, "last_hits": 80,
                 "party_id": 7},
            ],
        }
        with patch.object(DOTA2, "get_match_detail_info", return_value=match), \
                patch('report_builder.choose_custom_comment', return_value=None), \
                patch('report_builder.display_name', side_effect=lambda _id, name, _match: name), \
                patch('report_builder.persist_and_summarize', return_value=[]) as persist:
            report = DOTA2.generate_match_message(123, [first, second])

        self.assertEqual(persist.call_args.kwargs['participant_account_ids'], {42, 43})
        self.assertIn("发现2人组队开黑：甲、乙", report)
        self.assertIn("✅ 甲", report)
        self.assertIn("零死", report)
        self.assertNotIn("DOTA2 战报", report)

    def test_same_team_without_party_id_is_not_called_a_party(self):
        first = player("甲", 42, 76561197960265770, 122)
        second = player("乙", 43, 76561197960265771, 122)
        match = {
            "match_id": 123, "start_time": 1_700_000_000, "duration": 1800,
            "game_mode": 1, "lobby_type": 7, "radiant_win": True,
            "players": [
                {"account_id": 42, "player_slot": 0, "hero_id": 1},
                {"account_id": 43, "player_slot": 1, "hero_id": 2},
            ],
        }
        with patch('report_builder.choose_custom_comment', return_value=None), \
                patch('report_builder.display_name', side_effect=lambda _id, name, _match: name), \
                patch('report_builder.persist_and_summarize', return_value=[]):
            report = DOTA2.generate_match_message(123, [first, second], match=match)

        self.assertIn("发现2人同队同局：甲、乙", report)
        self.assertNotIn("组队开黑", report)

    def test_match_details_find_all_tracked_players(self):
        tracked = [
            player("甲", 42, 76561197960265770, 122),
            player("乙", 43, 76561197960265771, 122),
            player("不在本局", 99, 76561197960265827, 122),
        ]
        match = {'players': [
            {'account_id': 42}, {'account_id': None}, {'account_id': 43},
        ]}

        found = DOTA2.get_tracked_players_in_match(match, tracked)

        self.assertEqual([item.short_steamID for item in found], [42, 43])


if __name__ == "__main__":
    unittest.main()
