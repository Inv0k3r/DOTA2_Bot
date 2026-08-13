import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

TEST_DATABASE_PATH = os.environ.setdefault(
    'DATABASE_PATH',
    os.path.join(tempfile.gettempdir(), 'dota2_bot_test_{}.db'.format(uuid.uuid4().hex)),
)

import DOTA2
import common
from message_sender import MessageSendError
from player import PLAYER_LIST, Player


class CommonTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        import DBOper

        DBOper.conn.close()
        if os.path.exists(TEST_DATABASE_PATH):
            os.remove(TEST_DATABASE_PATH)

    def setUp(self):
        import DBOper

        with DBOper.conn:
            DBOper.c.execute('DELETE FROM prediction_bets')
            DBOper.c.execute('DELETE FROM prediction_scores')
            DBOper.c.execute('DELETE FROM prediction_player_links')
            DBOper.c.execute('DELETE FROM prediction_game_rewards')
        PLAYER_LIST.clear()
        common._poll_failures.clear()
        common._next_poll_at.clear()
        common._match_detail_failures.clear()
        common._next_match_detail_at.clear()
        common._priority_poll_until.clear()
        common._next_status_refresh_at = 0
        self.tracked = Player("测试玩家", 42, 76561197960265770, 100)
        PLAYER_LIST.append(self.tracked)

    def tearDown(self):
        PLAYER_LIST.clear()

    def test_outbox_persists_and_advances_player(self):
        import DBOper

        DBOper.insert_info(42, 76561197960265770, "测试玩家", 100)
        self.assertTrue(DBOper.enqueue_match(101, "report", [42]))
        pending = DBOper.get_pending_matches()
        self.assertEqual(pending[0]['match_id'], 101)
        self.assertEqual(pending[0]['player_ids'], [42])

        player_ids = DBOper.mark_match_sent(101, 999)
        self.assertEqual(player_ids, [42])
        self.assertEqual(DBOper.get_DOTA2_match_ID(42), 101)
        self.assertEqual(DBOper.get_match_outbox_status(101), 'sent')

    def test_prediction_bet_can_change_and_settles_once(self):
        import DBOper

        first = DBOper.place_prediction_bet(1, 99, '群友', 42, '测试玩家', True, 100, 2.0, 100)
        changed = DBOper.place_prediction_bet(1, 99, '群友', 42, '测试玩家', False, 200, 1.5, 100)
        self.assertFalse(first['changed'])
        self.assertTrue(changed['changed'])
        self.assertEqual(len(DBOper.get_open_prediction_bets(1, 99)), 1)

        rows = [{'account_id': 42, 'nickname': '测试玩家', 'won': False}]
        settled = DBOper.settle_prediction_bets(1, 101, 9999999999, rows)
        repeated = DBOper.settle_prediction_bets(1, 101, 9999999999, rows)

        self.assertEqual(len(settled), 1)
        self.assertTrue(settled[0]['correct'])
        self.assertEqual(repeated, [])
        self.assertEqual(DBOper.get_prediction_score(1, 99)['score'], 1100)
        self.assertEqual(DBOper.get_prediction_score(1, 99)['wagered'], 300)
        self.assertEqual(DBOper.get_prediction_score(1, 99)['returned'], 400)

    def test_prediction_does_not_settle_against_old_match(self):
        import DBOper

        DBOper.place_prediction_bet(1, 98, '群友2', 42, '测试玩家', True, 100, 2.0, 200)
        rows = [{'account_id': 42, 'nickname': '测试玩家', 'won': True}]

        self.assertEqual(DBOper.settle_prediction_bets(1, 199, 9999999999, rows), [])
        self.assertEqual(len(DBOper.get_open_prediction_bets(1, 98)), 1)

    def test_prediction_after_match_start_rolls_to_next_match(self):
        import DBOper

        DBOper.place_prediction_bet(1, 97, '群友3', 42, '测试玩家', True, 100, 2.0, 100)
        rows = [{'account_id': 42, 'nickname': '测试玩家', 'won': True}]

        self.assertEqual(DBOper.settle_prediction_bets(1, 101, 0, rows), [])
        self.assertEqual(len(DBOper.get_open_prediction_bets(1, 97)), 1)

    def test_prediction_rejects_insufficient_balance(self):
        import DBOper

        with self.assertRaisesRegex(ValueError, '余额不足'):
            DBOper.place_prediction_bet(1, 96, '穷人', 42, '测试玩家', True, 1001, 2.0, 100)

    def test_bound_player_cannot_bet_on_self(self):
        import DBOper

        DBOper.bind_prediction_player(1, 94, '玩家本人', 42, '测试玩家')

        with self.assertRaisesRegex(ValueError, '不能竞猜自己'):
            DBOper.place_prediction_bet(1, 94, '玩家本人', 42, '测试玩家', False, 100, 2.0, 100)

        self.assertEqual(DBOper.get_open_prediction_bets(1, 94), [])
        self.assertEqual(DBOper.get_prediction_score(1, 94)['score'], 1000)

    def test_binding_player_cancels_and_refunds_existing_self_bet(self):
        import DBOper

        DBOper.place_prediction_bet(1, 93, '玩家本人', 42, '测试玩家', False, 100, 2.0, 100)
        self.assertEqual(DBOper.get_prediction_score(1, 93)['score'], 900)

        refunded = DBOper.bind_prediction_player(1, 93, '玩家本人', 42, '测试玩家')

        self.assertEqual(refunded, 100)
        self.assertEqual(DBOper.get_open_prediction_bets(1, 93), [])
        score = DBOper.get_prediction_score(1, 93)
        self.assertEqual(score['score'], 1000)
        self.assertEqual(score['returned'], 100)

    def test_settlement_cancels_legacy_self_bet(self):
        import DBOper

        DBOper.place_prediction_bet(1, 92, '玩家本人', 42, '测试玩家', False, 100, 2.0, 100)
        with DBOper.conn:
            DBOper.c.execute(
                'INSERT INTO prediction_player_links VALUES (?,?,?,?,?,?)',
                (1, 92, '玩家本人', 42, '测试玩家', 1),
            )

        rows = [{'account_id': 42, 'nickname': '测试玩家', 'won': False}]
        self.assertEqual(DBOper.settle_prediction_bets(1, 101, 9999999999, rows), [])
        self.assertEqual(DBOper.get_open_prediction_bets(1, 92), [])
        self.assertEqual(DBOper.get_prediction_score(1, 92)['score'], 1000)

    def test_dynamic_odds_use_smoothed_match_history(self):
        import DBOper

        rows = []
        for index, won in enumerate((1, 1, 1, 0), 1):
            rows.append((index, 42, 1, '测试玩家', index, won, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1.0, 1.0, index))
        with DBOper.conn:
            DBOper.c.executemany(
                'INSERT OR REPLACE INTO match_stats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
        odds = DBOper.get_prediction_odds(1, 42)
        self.assertEqual(odds['games'], 4)
        self.assertLess(odds['win'], odds['lose'])

    def test_bound_player_earns_once_per_match(self):
        import DBOper

        DBOper.bind_prediction_player(1, 95, '玩家本人', 42, '测试玩家')
        rows = [{'account_id': 42, 'nickname': '测试玩家', 'won': True}]

        first = DBOper.reward_bound_players(1, 101, rows)
        repeated = DBOper.reward_bound_players(1, 101, rows)

        self.assertEqual(first[0]['amount'], 50)
        self.assertEqual(repeated, [])
        self.assertEqual(DBOper.get_prediction_score(1, 95)['score'], 1050)
        self.assertEqual(DBOper.get_prediction_score(1, 95)['game_earned'], 50)

    @patch("common.mark_match_sent", return_value=[42])
    @patch("common.mark_match_attempt")
    @patch("common.send", return_value={"message_id": 1})
    @patch(
        "common.get_pending_matches",
        return_value=[{
            "match_id": 101,
            "payload": "report",
            "player_ids": [42],
            "attempts": 0,
        }],
    )
    @patch("common.enqueue_match", return_value=True)
    @patch("common.get_match_outbox", return_value=None)
    @patch("common.DOTA2.generate_match_message", return_value="report")
    @patch("common.update_DOTA2")
    def test_queues_sends_and_marks_match(
        self,
        update_dota,
        generate,
        get_outbox,
        enqueue,
        get_pending,
        send,
        mark_attempt,
        mark_sent,
    ):
        update_dota.return_value = {101: [self.tracked]}

        common.update_and_send_message_DOTA2()

        generate.assert_called_once_with(101, [self.tracked])
        enqueue.assert_called_once_with(101, "report", {42})
        send.assert_called_once_with("report")
        mark_attempt.assert_called_once_with(101)
        mark_sent.assert_called_once_with(101, 1)
        self.assertEqual(self.tracked.last_DOTA2_match_ID, 101)

    @patch("common.get_pending_matches", return_value=[])
    @patch("common.enqueue_match")
    @patch("common.get_match_outbox", return_value=None)
    @patch(
        "common.DOTA2.generate_match_message",
        side_effect=DOTA2.DOTA2HTTPError("not ready"),
    )
    @patch("common.update_DOTA2")
    def test_generation_failure_does_not_queue_or_advance(
        self, update_dota, generate, get_outbox, enqueue, get_pending
    ):
        update_dota.return_value = {101: [self.tracked]}

        common.update_and_send_message_DOTA2()

        enqueue.assert_not_called()
        self.assertEqual(self.tracked.last_DOTA2_match_ID, 100)
        self.assertEqual(common._match_detail_failures[101], 1)
        self.assertGreater(common._next_match_detail_at[101], 0)

    @patch("common.get_pending_matches", return_value=[])
    @patch("common.enqueue_match")
    @patch("common.get_match_outbox", return_value=None)
    @patch("common.DOTA2.generate_match_message")
    @patch("common.update_DOTA2")
    def test_generation_respects_match_detail_backoff(
        self, update_dota, generate, get_outbox, enqueue, get_pending
    ):
        update_dota.return_value = {101: [self.tracked]}
        common._next_match_detail_at[101] = float("inf")

        common.update_and_send_message_DOTA2()

        generate.assert_not_called()
        get_outbox.assert_not_called()
        enqueue.assert_not_called()

    @patch("common.mark_match_failed")
    @patch("common.mark_match_attempt")
    @patch("common.send", side_effect=MessageSendError("offline"))
    @patch(
        "common.get_pending_matches",
        return_value=[{
            "match_id": 101,
            "payload": "report",
            "player_ids": [42],
            "attempts": 0,
        }],
    )
    @patch("common.update_DOTA2", return_value={})
    def test_send_failure_remains_pending(
        self, update_dota, get_pending, send, mark_attempt, mark_failed
    ):
        common.update_and_send_message_DOTA2()

        mark_attempt.assert_called_once_with(101)
        mark_failed.assert_called_once()
        self.assertEqual(self.tracked.last_DOTA2_match_ID, 100)

    @patch('common.DOTA2.get_recent_match_ids_by_short_steamID', return_value=[103, 102, 101, 100])
    def test_detects_every_unseen_match_oldest_first(self, _recent):
        detected = common.update_DOTA2()
        self.assertEqual(list(detected), [101, 102, 103])
        self.assertEqual(detected[101], [self.tracked])

    @patch('common.DOTA2.get_active_dota_account_ids', return_value=[42])
    @patch('common.time.monotonic', return_value=100)
    def test_active_player_is_prioritized_by_batched_status(self, _monotonic, _active):
        common._next_poll_at[42] = 999

        common.refresh_match_poll_priorities()

        self.assertEqual(common._next_poll_at[42], 100)
        self.assertGreater(common._priority_poll_until[42], 100)

    @patch('common.time.monotonic', return_value=100)
    def test_inactive_player_uses_slow_poll_interval(self, _monotonic):
        common._record_poll_success(self.tracked, now=100)

        self.assertEqual(
            common._next_poll_at[42],
            100 + common.config.INACTIVE_MATCH_POLL_INTERVAL,
        )


if __name__ == "__main__":
    unittest.main()
