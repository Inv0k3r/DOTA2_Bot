import unittest
from unittest.mock import patch

import game_features


class GameFeaturesTest(unittest.TestCase):
    @patch('game_features.get_player_streak', return_value=0)
    @patch('game_features.reward_bound_players', return_value=[])
    @patch('game_features.settle_prediction_bets')
    @patch('game_features.save_match_stats')
    def test_prediction_settlement_is_added_to_report_summary(
        self, save_stats, settle, reward, get_streak
    ):
        settle.return_value = [{
            'correct': True, 'user_name': '竞猜人', 'delta': 100, 'score': 1100,
        }]
        rows = [{'account_id': 42, 'nickname': '测试玩家'}]

        result = game_features.persist_and_summarize(101, 123, rows)

        save_stats.assert_called_once_with(101, game_features.config.QQ_GROUP_ID, 123, rows)
        settle.assert_called_once_with(game_features.config.QQ_GROUP_ID, 101, 123, rows)
        self.assertTrue(any('🎲 竞猜结算' in line for line in result))
        self.assertTrue(any('竞猜人 +100' in line for line in result))

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
