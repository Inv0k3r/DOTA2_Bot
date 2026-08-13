import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault(
    'DATABASE_PATH',
    os.path.join(tempfile.gettempdir(), 'dota2_bot_test_{}.db'.format(uuid.uuid4().hex)),
)

import command_handler
import config
from player import PLAYER_LIST, Player


class CommandHandlerTest(unittest.TestCase):
    def setUp(self):
        PLAYER_LIST.clear()
        self.admin_event = {
            'post_type': 'message',
            'message_type': 'group',
            'group_id': config.QQ_GROUP_ID,
            'user_id': 123,
            'sender': {'role': 'admin'},
        }

    def tearDown(self):
        PLAYER_LIST.clear()

    @patch('command_handler.send')
    @patch('command_handler.upsert_player', return_value=100)
    @patch('command_handler.DOTA2.get_last_match_id_by_short_steamID', return_value=100)
    def test_admin_can_add_player(self, latest, upsert, send):
        event = dict(self.admin_event, message='添加监控 76561197960265770 测试玩家')
        self.assertTrue(command_handler.handle_event(event))
        self.assertEqual(len(PLAYER_LIST), 1)
        self.assertEqual(PLAYER_LIST[0].short_steamID, 42)
        send.assert_called_once()

    @patch('command_handler.send')
    @patch('command_handler.disable_player', return_value=True)
    def test_admin_can_remove_player(self, disable, send):
        PLAYER_LIST.append(Player('测试玩家', 42, 76561197960265770, 100))
        event = dict(self.admin_event, message='删除监控 测试玩家')
        self.assertTrue(command_handler.handle_event(event))
        self.assertEqual(PLAYER_LIST, [])
        disable.assert_called_once_with(42)

    @patch('command_handler.send')
    def test_member_cannot_change_players(self, send):
        event = dict(self.admin_event, sender={'role': 'member'}, message='添加监控 42 测试玩家')
        self.assertTrue(command_handler.handle_event(event))
        self.assertEqual(PLAYER_LIST, [])
        send.assert_not_called()

    def test_extract_text_from_onebot_segments(self):
        event = {'message': [
            {'type': 'at', 'data': {'qq': 1}},
            {'type': 'text', 'data': {'text': ' 监控列表 '}},
        ]}
        self.assertEqual(command_handler._plain_text(event), '监控列表')

    @patch('command_handler.send')
    @patch('command_handler.add_comment_rule', return_value=12)
    def test_admin_can_add_comment_with_at(self, add_rule, send):
        event = dict(self.admin_event, self_id=999, message=[
            {'type': 'at', 'data': {'qq': '999'}},
            {'type': 'text', 'data': {'text': ' 加锐评 死亡>=10 60% 测试锐评'}},
        ])
        self.assertTrue(command_handler.handle_event(event))
        add_rule.assert_called_once()
        self.assertIn('锐评 #12 已添加', send.call_args.args[0])

    @patch('command_handler.send')
    @patch('command_handler.add_comment_rule')
    def test_comment_command_requires_at(self, add_rule, send):
        event = dict(self.admin_event, self_id=999, message='加锐评 死亡>=10 60% 测试锐评')
        self.assertFalse(command_handler.handle_event(event))
        add_rule.assert_not_called()
        send.assert_not_called()

    @patch('command_handler.send')
    def test_help_is_available_to_members_when_at_bot(self, send):
        event = dict(self.admin_event, self_id=999, sender={'role': 'member'}, message=[
            {'type': 'at', 'data': {'qq': '999'}},
            {'type': 'text', 'data': {'text': ' 帮助'}},
        ])
        self.assertTrue(command_handler.handle_event(event))
        response = send.call_args.args[0]
        self.assertIn('加锐评 <条件> <概率> <文案>', response)
        self.assertIn('添加监控', response)
        self.assertIn('TI下注', response)

    @patch('command_handler.send')
    def test_bare_at_prompts_for_help(self, send):
        event = dict(self.admin_event, self_id=999, sender={'role': 'member'}, message=[
            {'type': 'at', 'data': {'qq': '999'}},
        ])
        self.assertTrue(command_handler.handle_event(event))
        self.assertIn('@bot 帮助', send.call_args.args[0])

    @patch('command_handler.send')
    @patch('command_handler.get_prediction_odds', return_value={
        'games': 10, 'wins': 6, 'win': 1.8, 'lose': 2.2,
    })
    @patch('command_handler.place_prediction_bet', return_value={
        'id': 1, 'changed': False, 'balance': 900,
    })
    def test_member_can_bet_on_next_match_without_api_call(self, place_bet, odds, send):
        PLAYER_LIST.append(Player('测试玩家', 42, 76561197960265770, 100))
        event = dict(self.admin_event, self_id=999, user_id=321,
                     sender={'role': 'member', 'card': '竞猜人'}, message=[
                         {'type': 'at', 'data': {'qq': '999'}},
                         {'type': 'text', 'data': {'text': ' 竞猜 测试玩家 赢 100'}},
                     ])

        self.assertTrue(command_handler.handle_event(event))

        place_bet.assert_called_once_with(
            config.QQ_GROUP_ID, 321, '竞猜人', 42, '测试玩家', True, 100, 1.8, 100,
        )
        self.assertIn('下注成功', send.call_args.args[0])

    @patch('command_handler.send')
    @patch('command_handler.get_prediction_score', return_value={
        'user_name': '竞猜人', 'score': 1200, 'wins': 3, 'losses': 1,
        'wagered': 500, 'returned': 700, 'game_earned': 50,
        'checkin_earned': 100, 'commission_earned': 20,
    })
    def test_member_can_query_prediction_score(self, get_score, send):
        event = dict(self.admin_event, self_id=999, user_id=321,
                     sender={'role': 'member'}, message=[
                         {'type': 'at', 'data': {'qq': '999'}},
                         {'type': 'text', 'data': {'text': ' 我的积分'}},
                     ])

        self.assertTrue(command_handler.handle_event(event))
        self.assertIn('余额 1200点', send.call_args.args[0])
        self.assertIn('净收益 +200', send.call_args.args[0])
        self.assertIn('反向提成 20', send.call_args.args[0])

    @patch('command_handler.send')
    @patch('command_handler.get_prediction_leaderboard', return_value=[{
        'user_id': 321, 'user_name': 'player', 'score': 1350,
        'wins': 4, 'losses': 1, 'wagered': 800, 'returned': 1050,
        'game_earned': 100,
    }])
    def test_member_can_query_prediction_leaderboard(self, leaderboard, send):
        event = dict(self.admin_event, self_id=999, user_id=321,
                     sender={'role': 'member'}, message=[
                         {'type': 'at', 'data': {'qq': '999'}},
                         {'type': 'text', 'data': {'text': ' \u7ade\u731c\u699c'}},
                     ])

        self.assertTrue(command_handler.handle_event(event))
        leaderboard.assert_called_once_with(config.QQ_GROUP_ID)
        output = send.call_args.args[0]
        self.assertIn('player', output)
        self.assertIn('+250', output)

    @patch('command_handler.send')
    @patch('command_handler._refresh_ti_schedule', return_value=None)
    @patch('command_handler.get_ti_series', return_value={
        'team_1_name': 'Team Liquid', 'team_2_name': 'Xtreme Gaming',
    })
    @patch('command_handler.resolve_ti_team', return_value={
        'id': 2163, 'name': 'Team Liquid',
    })
    @patch('command_handler.place_ti_bet', return_value={
        'id': 8, 'changed': False, 'balance': 875, 'odds': 1.9,
    })
    def test_member_can_place_ti_bet_with_spaced_team_name(
        self, place_bet, resolve_team, get_series, refresh, send
    ):
        event = dict(self.admin_event, self_id=999, user_id=321,
                     sender={'role': 'member', 'card': 'TI玩家'}, message=[
                         {'type': 'at', 'data': {'qq': '999'}},
                         {'type': 'text', 'data': {
                             'text': ' TI竞猜 7 Team Liquid 125'
                         }},
                     ])

        self.assertTrue(command_handler.handle_event(event))

        resolve_team.assert_called_once_with(get_series.return_value, 'Team Liquid')
        place_bet.assert_called_once_with(
            config.QQ_GROUP_ID, 321, 'TI玩家', 7, 2163, 'Team Liquid', 125,
        )
        self.assertIn('TI下注成功', send.call_args.args[0])

    @patch('command_handler.send')
    @patch('command_handler.claim_prediction_daily_checkin', return_value={
        'claimed': True, 'amount': 100, 'balance': 1100,
    })
    def test_member_can_daily_checkin(self, claim, send):
        event = dict(self.admin_event, self_id=999, user_id=321,
                     sender={'role': 'member', 'card': '签到人'}, message=[
                         {'type': 'at', 'data': {'qq': '999'}},
                         {'type': 'text', 'data': {'text': ' 签到'}},
                     ])

        self.assertTrue(command_handler.handle_event(event))
        claim.assert_called_once_with(config.QQ_GROUP_ID, 321, '签到人')
        self.assertIn('签到成功', send.call_args.args[0])

    @patch('command_handler.send')
    @patch('command_handler.unbind_prediction_player', return_value={
        'user_id': 456, 'user_name': '群友', 'account_id': 42,
        'nickname': '测试玩家',
    })
    def test_admin_can_unbind_mentioned_player(self, unbind, send):
        event = dict(self.admin_event, self_id=999, message=[
            {'type': 'at', 'data': {'qq': '999'}},
            {'type': 'text', 'data': {'text': ' 取消绑定 '}},
            {'type': 'at', 'data': {'qq': '456'}},
        ])

        self.assertTrue(command_handler.handle_event(event))
        unbind.assert_called_once_with(
            config.QQ_GROUP_ID, user_id=456, account_id=None
        )
        self.assertIn('已取消绑定', send.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
