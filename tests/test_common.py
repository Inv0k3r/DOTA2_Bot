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
        PLAYER_LIST.clear()
        common._poll_failures.clear()
        common._next_poll_at.clear()
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


if __name__ == "__main__":
    unittest.main()
