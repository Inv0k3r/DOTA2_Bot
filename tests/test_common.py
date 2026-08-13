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
        import ti_event

        with DBOper.conn:
            DBOper.c.execute('DELETE FROM match_stats')
            DBOper.c.execute('DELETE FROM prediction_bets')
            DBOper.c.execute('DELETE FROM prediction_scores')
            DBOper.c.execute('DELETE FROM prediction_player_links')
            DBOper.c.execute('DELETE FROM prediction_game_rewards')
            DBOper.c.execute('DELETE FROM ti_notifications')
            DBOper.c.execute('DELETE FROM ti_bets')
            DBOper.c.execute('DELETE FROM ti_scores')
            DBOper.c.execute('DELETE FROM ti_series')
        PLAYER_LIST.clear()
        common._poll_failures.clear()
        common._next_poll_at.clear()
        common._match_detail_failures.clear()
        common._next_match_detail_at.clear()
        common._priority_poll_until.clear()
        common._next_status_refresh_at = 0
        ti_event._next_refresh_at = 0
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

    def _ti_payload(self, team_1_id=101, team_2_id=202, scheduled_time=2000,
                    started=False, completed=False, team_1_wins=0,
                    team_2_wins=0, match_winners=None):
        team_names = {
            101: ('Team Alpha', 'ALPHA'),
            202: ('Team Beta', 'BETA'),
            303: ('Team Gamma', 'GAMMA'),
        }
        standings = []
        for team_id in (101, 202, 303):
            name, tag = team_names[team_id]
            standings.append({
                'team_id': team_id, 'team_name': name, 'team_tag': tag,
                'team_abbreviation': tag,
            })
        node = {
            'node_id': 1, 'node_group_id': 2, 'scheduled_time': scheduled_time,
            'actual_time': scheduled_time if started else 0, 'series_id': 55,
            'team_id_1': team_1_id, 'team_id_2': team_2_id,
            'team_1_wins': team_1_wins, 'team_2_wins': team_2_wins,
            'has_started': started, 'is_completed': completed,
            'matches': [
                {'match_id': str(9000 + index), 'winning_team_id': winner}
                for index, winner in enumerate(match_winners or [])
            ],
        }
        return {
            'info': {'league_id': 19719, 'name': 'The International 2026'},
            'node_groups': [{
                'node_group_id': 1, 'team_standings': standings, 'nodes': [],
                'node_groups': [{
                    'node_group_id': 2, 'name': 'Swiss', 'nodes': [node],
                    'team_standings': [], 'node_groups': [],
                }],
            }],
        }

    def _refresh_ti(self, payload, now):
        import ti_event

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        with patch.object(ti_event.requests, 'get', return_value=response):
            return ti_event.refresh_ti_event(force=True, now=now)

    def test_ti_lifecycle_uses_separate_points_and_settles_once(self):
        import DBOper
        import ti_event

        self._refresh_ti(self._ti_payload(), 1000)
        placed = ti_event.place_ti_bet(
            1, 501, 'TI玩家', 1, 101, 'Team Alpha', 100, now=1000
        )
        self.assertEqual(placed['balance'], 900)
        self.assertEqual(
            DBOper.c.execute(
                'SELECT COUNT(*) FROM prediction_scores WHERE group_id=1 AND user_id=501'
            ).fetchone()[0],
            0,
        )

        transient = self._ti_payload(
            started=True, completed=True, team_1_wins=0, team_2_wins=0
        )
        self._refresh_ti(transient, 2100)
        self.assertEqual(ti_event.get_ti_series(1)['status'], 'locked')
        self.assertEqual(len(ti_event.get_open_ti_bets(1, 501)), 1)

        result = self._ti_payload(
            started=True, completed=True, team_1_wins=2, team_2_wins=0,
            match_winners=[101, 101],
        )
        first = self._refresh_ti(result, 2160)
        second = self._refresh_ti(result, 2220)
        repeated = self._refresh_ti(result, 2280)

        self.assertEqual(first['settled_bets'], 0)
        self.assertEqual(second['settled_bets'], 1)
        self.assertEqual(repeated['settled_bets'], 0)
        score = ti_event.get_ti_score(1, 501)
        self.assertEqual(score['score'], 1090)
        self.assertEqual((score['wins'], score['losses']), (1, 0))
        self.assertEqual(
            DBOper.c.execute('SELECT COUNT(*) FROM ti_notifications').fetchone()[0], 1
        )

    def test_ti_partial_then_changed_matchup_refunds_only_once(self):
        import DBOper
        import ti_event

        initial = self._ti_payload(scheduled_time=5000)
        self._refresh_ti(initial, 1000)
        ti_event.place_ti_bet(
            1, 502, '改盘玩家', 1, 202, 'Team Beta', 100, now=1000
        )

        partial = self._ti_payload(team_2_id=0, scheduled_time=5000)
        self._refresh_ti(partial, 1100)
        preserved = ti_event.get_ti_series(1)
        self.assertEqual(preserved['team_2_id'], 202)
        self.assertEqual(preserved['status'], 'pending')

        changed = self._ti_payload(team_2_id=303, scheduled_time=5000)
        self._refresh_ti(changed, 1200)
        self._refresh_ti(changed, 1260)
        self.assertEqual(ti_event.get_ti_series(1)['team_2_id'], 303)
        self.assertEqual(ti_event.get_ti_score(1, 502)['score'], 1000)
        self.assertEqual(ti_event.get_ti_score(1, 502)['returned'], 100)
        self.assertEqual(ti_event.get_open_ti_bets(1, 502), [])
        self.assertEqual(
            DBOper.c.execute(
                "SELECT COUNT(*) FROM ti_bets WHERE status='cancelled'"
            ).fetchone()[0],
            1,
        )

    def test_ti_rejects_stale_data_and_closes_at_boundary(self):
        import ti_event

        payload = self._ti_payload(scheduled_time=2000)
        self._refresh_ti(payload, 1000)
        with self.assertRaisesRegex(ValueError, '数据已过期'):
            ti_event.place_ti_bet(
                1, 503, '过期玩家', 1, 101, 'Team Alpha', 10, now=1181
            )

        self._refresh_ti(payload, 1699)
        ti_event.place_ti_bet(
            1, 503, '边界玩家', 1, 101, 'Team Alpha', 10, now=1699
        )
        with self.assertRaisesRegex(ValueError, '已封盘'):
            ti_event.place_ti_bet(
                1, 504, '迟到玩家', 1, 101, 'Team Alpha', 10, now=1700
            )

    def test_ti_unresolved_result_times_out_and_refunds(self):
        import DBOper
        import ti_event

        self._refresh_ti(self._ti_payload(), 1000)
        ti_event.place_ti_bet(
            1, 505, '退款玩家', 1, 101, 'Team Alpha', 100, now=1000
        )
        unresolved = self._ti_payload(started=True, completed=True)
        self._refresh_ti(unresolved, 2100)
        with patch.object(ti_event.config, 'TI_RESULT_GRACE_SECONDS', 600):
            self._refresh_ti(unresolved, 2700)

        self.assertEqual(ti_event.get_ti_series(1)['status'], 'cancelled')
        self.assertEqual(ti_event.get_ti_score(1, 505)['score'], 1000)
        self.assertEqual(ti_event.get_open_ti_bets(1, 505), [])
        self.assertEqual(
            DBOper.c.execute(
                "SELECT cancel_reason FROM ti_bets WHERE user_id=505"
            ).fetchone()[0],
            'unresolved_result',
        )

    def test_ti_missing_market_eventually_refunds(self):
        import ti_event

        self._refresh_ti(self._ti_payload(), 1000)
        ti_event.place_ti_bet(
            1, 506, '消失赛程玩家', 1, 202, 'Team Beta', 100, now=1000
        )
        empty_payload = {
            'info': {'league_id': 19719, 'name': 'The International 2026'},
            'node_groups': [],
        }
        self._refresh_ti(empty_payload, 4599)
        self.assertEqual(len(ti_event.get_open_ti_bets(1, 506)), 1)
        self._refresh_ti(empty_payload, 4600)
        self.assertEqual(ti_event.get_open_ti_bets(1, 506), [])
        self.assertEqual(ti_event.get_ti_score(1, 506)['score'], 1000)
        self.assertEqual(ti_event.get_ti_series(1)['status'], 'cancelled')

    def test_ti_schema_migrates_pre_event_series_table(self):
        import DBOper
        import ti_event

        with DBOper.conn:
            DBOper.c.execute('DROP TABLE ti_series')
            DBOper.c.execute(
                """CREATE TABLE ti_series (
                    league_id INTEGER NOT NULL,node_id INTEGER NOT NULL,
                    node_group_id INTEGER NOT NULL,group_name TEXT NOT NULL,
                    node_name TEXT NOT NULL,scheduled_time INTEGER NOT NULL DEFAULT 0,
                    actual_time INTEGER NOT NULL DEFAULT 0,series_id INTEGER NOT NULL DEFAULT 0,
                    team_1_id INTEGER NOT NULL DEFAULT 0,team_1_name TEXT NOT NULL DEFAULT '',
                    team_1_tag TEXT NOT NULL DEFAULT '',team_1_abbr TEXT NOT NULL DEFAULT '',
                    team_2_id INTEGER NOT NULL DEFAULT 0,team_2_name TEXT NOT NULL DEFAULT '',
                    team_2_tag TEXT NOT NULL DEFAULT '',team_2_abbr TEXT NOT NULL DEFAULT '',
                    team_1_wins INTEGER NOT NULL DEFAULT 0,team_2_wins INTEGER NOT NULL DEFAULT 0,
                    has_started INTEGER NOT NULL DEFAULT 0,is_completed INTEGER NOT NULL DEFAULT 0,
                    winner_team_id INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL,
                    PRIMARY KEY (league_id,node_group_id,node_id)
                )"""
            )
        ti_event._init_schema()
        columns = {
            row[1] for row in DBOper.c.execute('PRAGMA table_info(ti_series)').fetchall()
        }
        self.assertTrue({
            'status', 'locked_at', 'result_signature', 'result_confirmations',
            'completed_seen_at',
        }.issubset(columns))
        self._refresh_ti(self._ti_payload(), 1000)
        self.assertEqual(ti_event.get_ti_series(1)['status'], 'open')

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
