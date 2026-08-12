import http.client
import json
import threading
import unittest
from unittest.mock import patch

import config
import event_receiver


class EventReceiverTest(unittest.TestCase):
    def setUp(self):
        self.secret = 'test-secret'
        self.config_patch = patch.object(config, 'EVENT_SECRET', self.secret)
        self.config_patch.start()
        self.server = event_receiver.ThreadingHTTPServer(('127.0.0.1', 0), event_receiver._Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.config_patch.stop()
        while not event_receiver.EVENT_QUEUE.empty():
            event_receiver.EVENT_QUEUE.get_nowait()
            event_receiver.EVENT_QUEUE.task_done()

    def test_accept_chunked_event(self):
        body = json.dumps({'post_type': 'meta_event'}).encode()
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(
            'POST', '/onebot/' + self.secret, body=iter([body]),
            headers={'Content-Type': 'application/json'}, encode_chunked=True,
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 204)
        self.assertEqual(event_receiver.EVENT_QUEUE.get_nowait()['post_type'], 'meta_event')
        event_receiver.EVENT_QUEUE.task_done()

    def test_accept_empty_health_post(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request('POST', '/onebot/' + self.secret, body=b'')
        self.assertEqual(connection.getresponse().status, 204)


if __name__ == '__main__':
    unittest.main()
