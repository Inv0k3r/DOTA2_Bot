import unittest
from unittest.mock import Mock, patch

import message_sender


class MessageSenderTest(unittest.TestCase):
    @patch("message_sender.requests.post")
    def test_send_group_message_via_onebot_http(self, post):
        response = Mock()
        response.json.return_value = {
            "status": "ok",
            "retcode": 0,
            "data": {"message_id": 123},
        }
        post.return_value = response

        with patch.object(message_sender.config, "NAPCAT_HTTP_URL", "http://127.0.0.1:3000"), \
                patch.object(message_sender.config, "NAPCAT_ACCESS_TOKEN", "secret"), \
                patch.object(message_sender.config, "QQ_GROUP_ID", 456), \
                patch.object(message_sender.config, "REQUEST_TIMEOUT", 10):
            result = message_sender.message("hello")

        self.assertEqual(result, {"message_id": 123})
        post.assert_called_once_with(
            "http://127.0.0.1:3000/send_group_msg",
            json={"group_id": 456, "message": "hello"},
            headers={"Authorization": "Bearer secret"},
            timeout=10,
        )
        response.raise_for_status.assert_called_once_with()

    @patch("message_sender.requests.post")
    def test_raise_when_onebot_rejects_message(self, post):
        response = Mock()
        response.json.return_value = {
            "status": "failed",
            "retcode": 1404,
            "message": "group not found",
        }
        post.return_value = response

        with self.assertRaises(message_sender.MessageSendError):
            message_sender.message("hello")


if __name__ == "__main__":
    unittest.main()
