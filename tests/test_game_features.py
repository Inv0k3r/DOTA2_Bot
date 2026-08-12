import unittest
from unittest.mock import patch

import game_features


class GameFeaturesTest(unittest.TestCase):
    @patch('game_features.get_match_stats')
    def test_roast_player_uses_match_performance(self, get_stats):
        get_stats.return_value = [{
            'account_id': 42, 'nickname': '测试玩家', 'deaths': 12,
            'participation': 20, 'gpm': 400, 'damage_share': 10, 'won': 0,
        }]
        result = game_features.roast_player(123, '测试玩家')
        self.assertIn('死了12次', result)

    @patch('game_features.get_today_stats')
    def test_today_leaderboard(self, get_stats):
        get_stats.return_value = [
            {'account_id': 1, 'nickname': '红', 'games': 3, 'wins': 3,
             'kills': 20, 'deaths': 5, 'assists': 20},
            {'account_id': 2, 'nickname': '黑', 'games': 4, 'wins': 0,
             'kills': 2, 'deaths': 30, 'assists': 5},
        ]
        result = game_features.today_leaderboard()
        self.assertIn('红榜：红', result)
        self.assertIn('黑榜：黑', result)


if __name__ == '__main__':
    unittest.main()
