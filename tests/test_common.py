import os
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

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
            DBOper.c.execute('DELETE FROM playerInfo')
            DBOper.c.execute('DELETE FROM removed_players')
            DBOper.c.execute('DELETE FROM match_outbox')
            DBOper.c.execute('DELETE FROM match_stats')
            DBOper.c.execute('DELETE FROM player_aliases')
            DBOper.c.execute('DELETE FROM combo_names')
            DBOper.c.execute('DELETE FROM prediction_bets')
            DBOper.c.execute('DELETE FROM prediction_scores')
            DBOper.c.execute('DELETE FROM prediction_player_links')
            DBOper.c.execute('DELETE FROM prediction_game_rewards')
            DBOper.c.execute('DELETE FROM prediction_daily_checkins')
            DBOper.c.execute('DELETE FROM prediction_commissions')
            DBOper.c.execute('DELETE FROM prediction_loans')
            DBOper.c.execute('DELETE FROM prediction_deaths')
        PLAYER_LIST.clear()
        common._poll_failures.clear()
        common._next_poll_at.clear()
        common._match_detail_failures.clear()
        common._next_match_detail_at.clear()
        common._priority_poll_until.clear()
        common._active_dota_account_ids.clear()
        common._active_status_updated_at = 0
        common._next_status_refresh_at = 0
        common._steam_history_failures = 0
        common._steam_history_retry_at = 0
        self.tracked = Player("测试玩家", 42, 76561197960265770, 100)
        PLAYER_LIST.append(self.tracked)

    def tearDown(self):
        PLAYER_LIST.clear()

    def _record_results(self, account_id, results, group_id=1, first_match_id=100):
        import DBOper

        for offset, won in enumerate(results):
            DBOper.save_match_stats(
                first_match_id + offset, group_id, 1000 + offset,
                [{
                    'account_id': account_id, 'nickname': '测试玩家',
                    'won': won, 'team': 1, 'hero_id': 1, 'kills': 1,
                    'deaths': 1, 'assists': 1, 'gpm': 1, 'xpm': 1,
                    'last_hits': 1, 'damage': 1, 'damage_share': 1.0,
                    'participation': 1.0,
                }],
            )

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

    def test_delete_player_clears_related_data_and_refunds_open_bets(self):
        import DBOper

        DBOper.insert_info(42, 76561197960265770, "测试玩家", 100)
        DBOper.set_player_alias(1, 42, '外号', 100, 1)
        DBOper.set_combo_name(1, [42, 99], '组合', 1)
        self._record_results(42, [1], group_id=1)
        DBOper.bind_prediction_player(1, 200, '本人', 42, '测试玩家')
        DBOper.place_prediction_bet(1, 201, '竞猜者', 42, '测试玩家', 1, 250, 2.0, 100)
        DBOper.enqueue_match(101, '待发送战报', [42, 99])

        result = DBOper.delete_player_data(42)

        self.assertEqual(result['refunded_bets'], 1)
        self.assertEqual(result['refunded_score'], 250)
        self.assertEqual(DBOper.get_prediction_score(1, 201)['score'], 1000)
        for table, column in (
            ('playerInfo', 'short_steamID'),
            ('match_stats', 'account_id'),
            ('player_aliases', 'account_id'),
            ('prediction_bets', 'target_account_id'),
            ('prediction_player_links', 'account_id'),
        ):
            count = DBOper.c.execute(
                'SELECT COUNT(*) FROM {} WHERE {}=?'.format(table, column), (42,)
            ).fetchone()[0]
            self.assertEqual(count, 0, table)
        self.assertIsNone(DBOper.get_combo_name(1, [42, 99]))
        self.assertIsNone(DBOper.get_match_outbox(101))
        self.assertTrue(DBOper.is_player_stored(42))

        DBOper.upsert_player(42, 76561197960265770, '重新添加', 999)
        self.assertEqual(DBOper.get_enabled_players()[0]['last_DOTA2_match_ID'], 999)
        tombstones = DBOper.c.execute(
            'SELECT COUNT(*) FROM removed_players WHERE short_steamID=42'
        ).fetchone()[0]
        self.assertEqual(tombstones, 0)

    def test_forget_player_clears_runtime_state(self):
        common._poll_failures[42] = 2
        common._next_poll_at[42] = 100
        common._priority_poll_until[42] = 200
        common._active_dota_account_ids.add(42)

        common.forget_player(42)

        self.assertNotIn(42, common._poll_failures)
        self.assertNotIn(42, common._next_poll_at)
        self.assertNotIn(42, common._priority_poll_until)
        self.assertNotIn(42, common._active_dota_account_ids)

    def test_sent_match_can_queue_addendum_for_late_player(self):
        import DBOper

        match_id = 901001
        DBOper.enqueue_match(match_id, 'original', [99])
        DBOper.mark_match_sent(match_id, 123)

        self.assertTrue(DBOper.enqueue_match_addendum(match_id, 'addendum', [42]))
        self.assertFalse(DBOper.enqueue_match_addendum(match_id, 'duplicate', [42]))
        pending = DBOper.get_pending_matches()
        item = next(row for row in pending if row['match_id'] == match_id)
        self.assertEqual(item['payload'], 'addendum')
        self.assertEqual(item['player_ids'], [42, 99])

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

    def test_prediction_loan_borrow_and_repay(self):
        import DBOper

        with patch.object(DBOper.config, 'PREDICTION_LOAN_MAX', 2000):
            loan = DBOper.create_prediction_loan(1, 700, '借款人', 2000, now=1000)
        self.assertEqual((loan['principal'], loan['interest'], loan['total_due']),
                         (2000, 200, 2200))
        self.assertEqual(loan['balance'], 3000)
        paid = DBOper.repay_prediction_loan(1, 700, now=1001)
        self.assertEqual(paid['paid'], 2200)
        self.assertEqual(paid['balance'], 800)
        self.assertEqual(DBOper.get_prediction_loan_status(1, 700, now=1002)['loan']['status'],
                         'repaid')

    def test_prediction_loan_rejects_second_and_bad_amount(self):
        import DBOper

        with self.assertRaisesRegex(ValueError, '100–2000'):
            DBOper.create_prediction_loan(1, 701, '借款人', 2001, now=1000)
        DBOper.create_prediction_loan(1, 701, '借款人', 100, now=1000)
        with self.assertRaisesRegex(ValueError, '未还'):
            DBOper.create_prediction_loan(1, 701, '借款人', 100, now=1001)

    def test_prediction_loan_default_kills_once_and_revives(self):
        import DBOper

        with patch.object(DBOper.config, 'PREDICTION_LOAN_TERM_SECONDS', 100), \
             patch.object(DBOper.config, 'PREDICTION_DEATH_SECONDS', 300):
            DBOper.create_prediction_loan(1, 702, '老赖', 500, now=1000)
            with DBOper.conn:
                DBOper.c.execute(
                    """INSERT INTO prediction_bets
                       (group_id,user_id,user_name,target_account_id,target_nickname,prediction,
                        stake,odds,after_match_id,status,created_at,updated_at)
                       VALUES (1,702,'老赖',42,'测试玩家',1,100,2.0,100,'open',1000,1000)"""
                )
                DBOper.c.execute(
                    'UPDATE prediction_scores SET score=score-100 WHERE group_id=1 AND user_id=702'
                )
            first = DBOper.enforce_overdue_prediction_loans(now=1100)
            repeated = DBOper.enforce_overdue_prediction_loans(now=1200)
            self.assertEqual(len(first), 1)
            self.assertEqual(repeated, [])
            self.assertEqual(DBOper.get_prediction_score(1, 702)['score'], 0)
            self.assertEqual(DBOper.get_open_prediction_bets(1, 702), [])
            with self.assertRaisesRegex(ValueError, '已死亡'):
                DBOper.claim_prediction_daily_checkin(1, 702, '老赖', now=1200)
            with self.assertRaisesRegex(ValueError, '已死亡'):
                DBOper.create_prediction_loan(1, 702, '老赖', 100, now=1200)
            status = DBOper.get_prediction_loan_status(1, 702, now=1399)
            self.assertIsNotNone(status['death'])
            revived = DBOper.claim_prediction_daily_checkin(1, 702, '老赖', now=1400)
            self.assertTrue(revived['claimed'])
            self.assertIsNone(DBOper.get_prediction_loan_status(1, 702, now=1400)['death'])

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

    def test_three_loss_streak_locks_betting_until_next_win(self):
        import DBOper

        with patch.object(DBOper.config, 'PREDICTION_LOSS_STREAK_LIMIT', 3):
            self._record_results(42, [False, False])
            allowed = DBOper.place_prediction_bet(
                1, 91, '群友', 42, '测试玩家', False, 100, 2.0, 101
            )
            self.assertEqual(allowed['balance'], 900)

            with DBOper.conn:
                DBOper.c.execute(
                    "UPDATE prediction_bets SET status='cancelled' WHERE id=?",
                    (allowed['id'],),
                )
            self._record_results(42, [False], first_match_id=102)
            with self.assertRaisesRegex(ValueError, '连续 3 败'):
                DBOper.place_prediction_bet(
                    1, 90, '群友2', 42, '测试玩家', False, 100, 2.0, 102
                )

            self._record_results(42, [True], first_match_id=103)
            unlocked = DBOper.place_prediction_bet(
                1, 90, '群友2', 42, '测试玩家', True, 100, 2.0, 103
            )
            self.assertEqual(unlocked['balance'], 900)

    def test_third_loss_cancels_all_open_bets_before_payout(self):
        import DBOper

        with patch.object(DBOper.config, 'PREDICTION_LOSS_STREAK_LIMIT', 3):
            self._record_results(42, [False, False])
            DBOper.place_prediction_bet(
                1, 89, '押输的人', 42, '测试玩家', False, 100, 2.0, 101
            )
            DBOper.place_prediction_bet(
                1, 88, '押赢的人', 42, '测试玩家', True, 200, 2.0, 999
            )
            self._record_results(42, [False], first_match_id=102)
            risk_events = []

            settled = DBOper.settle_prediction_bets(
                1, 102, 9999999999,
                [{'account_id': 42, 'nickname': '测试玩家', 'won': False}],
                participant_account_ids=[42], risk_events=risk_events,
            )

            self.assertEqual(settled, [])
            self.assertEqual(risk_events[0]['reason'], 'loss_streak')
            self.assertEqual(risk_events[0]['bet_count'], 2)
            self.assertEqual(risk_events[0]['refund'], 300)
            self.assertEqual(DBOper.get_prediction_score(1, 89)['score'], 1000)
            self.assertEqual(DBOper.get_prediction_score(1, 88)['score'], 1000)
            self.assertEqual(DBOper.get_prediction_score(1, 89)['wins'], 0)
            self.assertEqual(DBOper.settle_prediction_bets(
                1, 102, 9999999999,
                [{'account_id': 42, 'nickname': '测试玩家', 'won': False}],
            ), [])
            self.assertEqual(DBOper.get_prediction_score(1, 89)['score'], 1000)

    def test_same_match_participant_bet_is_voided_and_refunded(self):
        import DBOper

        DBOper.bind_prediction_player(1, 87, '同局玩家', 99, '另一个玩家')
        DBOper.place_prediction_bet(
            1, 87, '同局玩家', 42, '测试玩家', False, 100, 2.0, 100
        )
        risk_events = []

        settled = DBOper.settle_prediction_bets(
            1, 101, 9999999999,
            [{'account_id': 42, 'nickname': '测试玩家', 'won': False}],
            participant_account_ids=[42, 99], risk_events=risk_events,
        )

        self.assertEqual(settled, [])
        self.assertEqual(risk_events[0]['reason'], 'match_participant')
        self.assertEqual(DBOper.get_prediction_score(1, 87)['score'], 1000)
        cancelled = DBOper.c.execute(
            "SELECT status,cancel_reason FROM prediction_bets WHERE user_id=87"
        ).fetchone()
        self.assertEqual(cancelled, ('cancelled', 'match_participant'))

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

        self.assertEqual(first[0]['amount'], 100)
        self.assertEqual(repeated, [])
        self.assertEqual(DBOper.get_prediction_score(1, 95)['score'], 1100)
        self.assertEqual(DBOper.get_prediction_score(1, 95)['game_earned'], 100)

    def test_bound_player_loss_reward_is_fifty(self):
        import DBOper

        DBOper.bind_prediction_player(1, 95, '玩家本人', 42, '测试玩家')
        rewards = DBOper.reward_bound_players(
            1, 102, [{'account_id': 42, 'nickname': '测试玩家', 'won': False}]
        )

        self.assertEqual(rewards[0]['amount'], 50)
        self.assertFalse(rewards[0]['won'])
        self.assertEqual(DBOper.get_prediction_score(1, 95)['score'], 1050)

    def test_daily_checkin_awards_once_per_local_day(self):
        import DBOper

        first = DBOper.claim_prediction_daily_checkin(
            1, 96, '签到人', now=100000
        )
        repeated = DBOper.claim_prediction_daily_checkin(
            1, 96, '签到人', now=100100
        )
        tomorrow = DBOper.claim_prediction_daily_checkin(
            1, 96, '签到人', now=100000 + 86400
        )

        self.assertTrue(first['claimed'])
        self.assertFalse(repeated['claimed'])
        self.assertTrue(tomorrow['claimed'])
        self.assertEqual(tomorrow['balance'], 1200)
        self.assertEqual(DBOper.get_prediction_score(1, 96)['checkin_earned'], 200)

    def test_winner_gets_commission_from_bets_predicting_loss(self):
        import DBOper

        DBOper.bind_prediction_player(1, 97, '玩家本人', 42, '测试玩家')
        DBOper.place_prediction_bet(
            1, 98, '看衰的人', 42, '测试玩家', False, 200, 2.0, 100
        )
        DBOper.place_prediction_bet(
            1, 99, '看好的人', 42, '测试玩家', True, 100, 2.0, 100
        )
        commissions = []
        rows = [{'account_id': 42, 'nickname': '测试玩家', 'won': True}]

        DBOper.settle_prediction_bets(
            1, 101, 9999999999, rows, commissions=commissions
        )
        DBOper.settle_prediction_bets(
            1, 101, 9999999999, rows, commissions=commissions
        )

        self.assertEqual(len(commissions), 1)
        self.assertEqual(commissions[0]['opposition_stake'], 200)
        self.assertEqual(commissions[0]['amount'], 20)
        score = DBOper.get_prediction_score(1, 97)
        self.assertEqual(score['score'], 1020)
        self.assertEqual(score['commission_earned'], 20)

    def test_loser_gets_no_commission_from_bets_predicting_win(self):
        import DBOper

        DBOper.bind_prediction_player(1, 97, '玩家本人', 42, '测试玩家')
        DBOper.place_prediction_bet(
            1, 99, '看好的人', 42, '测试玩家', True, 200, 2.0, 100
        )
        commissions = []
        DBOper.settle_prediction_bets(
            1, 101, 9999999999,
            [{'account_id': 42, 'nickname': '测试玩家', 'won': False}],
            commissions=commissions,
        )

        self.assertEqual(commissions, [])
        self.assertEqual(DBOper.get_prediction_score(1, 97)['commission_earned'], 0)

    def test_prediction_binding_is_strictly_one_to_one_and_can_unbind(self):
        import DBOper

        DBOper.bind_prediction_player(1, 90, '甲', 42, '测试玩家')
        with self.assertRaisesRegex(ValueError, '已绑定'):
            DBOper.bind_prediction_player(1, 90, '甲', 99, '另一个玩家')
        with self.assertRaisesRegex(ValueError, '已被 QQ 90 绑定'):
            DBOper.bind_prediction_player(1, 91, '乙', 42, '测试玩家')

        removed = DBOper.unbind_prediction_player(1, user_id=90)
        self.assertEqual(removed['account_id'], 42)
        DBOper.bind_prediction_player(1, 91, '乙', 42, '测试玩家')
        self.assertIsNone(DBOper.unbind_prediction_player(1, user_id=90))

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

    @patch("common.enqueue_match_addendum", return_value=True)
    @patch("common.DOTA2.generate_match_message", return_value="late report")
    @patch("common.get_match_outbox", return_value={
        'status': 'sent', 'payload': 'original', 'player_ids': [99],
    })
    def test_late_player_queues_addendum(self, get_outbox, generate, enqueue_addendum):
        common._queue_detected_matches({101: [self.tracked]})

        generate.assert_called_once_with(101, [self.tracked])
        payload = enqueue_addendum.call_args.args[1]
        self.assertIn('补充战报', payload)
        self.assertIn('late report', payload)
        enqueue_addendum.assert_called_once_with(101, payload, [42])

    @patch("common.acknowledge_sent_match")
    @patch("common.DOTA2.generate_match_message")
    @patch("common.get_match_outbox", return_value={
        'status': 'sent', 'payload': 'original', 'player_ids': [42],
    })
    def test_already_delivered_player_is_only_acknowledged(
        self, get_outbox, generate, acknowledge
    ):
        common._queue_detected_matches({101: [self.tracked]})

        generate.assert_not_called()
        acknowledge.assert_called_once_with(101, [42])

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
        self.assertTrue(common.is_player_currently_in_dota(42, now=101))
        self.assertFalse(common.is_player_currently_in_dota(42, now=251))

    @patch('common.time.monotonic', return_value=100)
    def test_inactive_player_uses_slow_poll_interval(self, _monotonic):
        common._record_poll_success(self.tracked, now=100)

        self.assertEqual(
            common._next_poll_at[42],
            100 + common.config.INACTIVE_MATCH_POLL_INTERVAL,
        )

    @patch('common.random.uniform', return_value=1.0)
    @patch('common.time.monotonic', return_value=100)
    def test_transient_steam_failures_open_global_circuit(self, _monotonic, _uniform):
        error = DOTA2.DOTA2HTTPError('Steam match history returned HTTP 503')

        for _ in range(common.config.STEAM_HISTORY_CIRCUIT_THRESHOLD):
            common._record_steam_history_result(error)

        expected = 100 + common.config.STEAM_HISTORY_CIRCUIT_COOLDOWN
        self.assertEqual(common._steam_history_retry_at, expected)
        self.assertGreaterEqual(common._next_poll_at[42], expected)

    @patch('common.DOTA2.get_recent_match_ids_by_short_steamID')
    @patch('common.time.monotonic', return_value=100)
    def test_global_circuit_skips_history_requests(self, _monotonic, recent):
        common._steam_history_retry_at = 200

        self.assertEqual(common.update_DOTA2(), {})

        recent.assert_not_called()

    @patch('common.random.uniform', return_value=1.0)
    @patch('common.time.monotonic', return_value=100)
    def test_steam_429_opens_circuit_immediately(self, _monotonic, _uniform):
        error = DOTA2.DOTA2HTTPError('Steam match history returned HTTP 429')

        common._record_steam_history_result(error)

        self.assertEqual(
            common._steam_history_retry_at,
            100 + common.config.STEAM_HISTORY_CIRCUIT_COOLDOWN,
        )

    def test_success_resets_transient_steam_failure_streak(self):
        error = DOTA2.DOTA2HTTPError('Steam match history returned HTTP 503')
        common._record_steam_history_result(error, now=100)

        common._record_steam_history_result(now=101)

        self.assertEqual(common._steam_history_failures, 0)


if __name__ == "__main__":
    unittest.main()
