#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Receive OneBot HTTP events and hand them to the main thread safely."""
import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue
from threading import Thread

import config
from command_handler import handle_event

logger = logging.getLogger(__name__)
EVENT_QUEUE = Queue(maxsize=1000)


class _Handler(BaseHTTPRequestHandler):
    def _read_body(self):
        length_header = self.headers.get('Content-Length')
        if length_header is not None:
            length = int(length_header)
            if length < 0 or length > 1024 * 1024:
                raise ValueError('invalid content length')
            return self.rfile.read(length) if length else b''

        if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            chunks = []
            total = 0
            while True:
                size_line = self.rfile.readline().strip()
                size = int(size_line.split(b';', 1)[0], 16)
                if size == 0:
                    while self.rfile.readline().strip():
                        pass
                    break
                total += size
                if total > 1024 * 1024:
                    raise ValueError('event body too large')
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)
            return b''.join(chunks)
        return b''

    def do_POST(self):
        expected_path = '/onebot/{}'.format(config.EVENT_SECRET) if config.EVENT_SECRET else '/onebot'
        if not hmac.compare_digest(self.path.rstrip('/'), expected_path.rstrip('/')):
            self.send_error(404)
            return
        try:
            body = self._read_body()
            if not body:
                self.send_response(204)
                self.end_headers()
                return
            event = json.loads(body.decode('utf-8'))
            EVENT_QUEUE.put_nowait(event)
        except Exception as exc:
            logger.warning('拒绝无效的 OneBot 事件: %s', exc)
            self.send_error(400)
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        logger.debug(fmt, *args)


def start_event_server():
    server = ThreadingHTTPServer((config.EVENT_HOST, config.EVENT_PORT), _Handler)
    thread = Thread(target=server.serve_forever, name='onebot-events', daemon=True)
    thread.start()
    logger.info('OneBot 事件接收器监听 %s:%s', config.EVENT_HOST, config.EVENT_PORT)
    return server


def process_pending_events(limit=50):
    processed = 0
    while processed < limit:
        try:
            event = EVENT_QUEUE.get_nowait()
        except Empty:
            break
        try:
            handle_event(event)
        except Exception:
            logger.exception('处理 OneBot 事件失败')
        finally:
            EVENT_QUEUE.task_done()
        processed += 1
    return processed
