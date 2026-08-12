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

    @patch('command_handler.send')
    def test_bare_at_prompts_for_help(self, send):
        event = dict(self.admin_event, self_id=999, sender={'role': 'member'}, message=[
            {'type': 'at', 'data': {'qq': '999'}},
        ])
        self.assertTrue(command_handler.handle_event(event))
        self.assertIn('@bot 帮助', send.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
