#!/usr/bin/env python3
"""NEON SIEGE 2 co-op server — matchmaking.

    python server.py          (Render: start command `python server.py`, reads $PORT)

Press PLAY in the game and you are put in a queue; the moment someone else
presses it you are paired and dropped into the same match. No codes.

The server is a dumb pipe. It never parses a game message and holds no state
beyond "these two sockets are paired", so the host remains the sole authority
exactly as it is over a direct peer-to-peer link.

Standard library only, so there is nothing to install and nothing to break on
deploy. The WebSocket layer is a small RFC 6455 implementation; a framework
for ~120 lines of framing would be this project's only dependency.
"""
import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = 'neon-siege-2-coop.html'

QUEUE = []                      # peers waiting for a partner, longest wait first
LOCK = threading.Lock()
STATS = {'paired': 0, 'live': 0}


def log(*a):
    print(*a, flush=True)


class Peer(object):
    """One websocket. `send` is serialised: the two directions run on separate
    threads and must never interleave frames on the same socket."""

    def __init__(self, handler):
        self.h = handler
        self.lock = threading.Lock()
        self.partner = None
        self.role = None
        self.alive = True
        self.since = time.time()

    def send(self, obj):
        data = json.dumps(obj, separators=(',', ':')).encode('utf-8')
        with self.lock:
            if not self.alive:
                return
            try:
                self.h.wfile.write(ws_frame(data))
                self.h.wfile.flush()
            except Exception:
                self.alive = False


# ── framing ───────────────────────────────────────────────────────
def ws_frame(payload, opcode=0x1):
    n = len(payload)
    head = bytearray([0x80 | opcode])
    if n < 126:
        head.append(n)
    elif n < (1 << 16):
        head.append(126)
        head += struct.pack('>H', n)
    else:
        head.append(127)
        head += struct.pack('>Q', n)
    return bytes(head) + payload


def read_exact(rfile, n):
    buf = b''
    while len(buf) < n:
        chunk = rfile.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def ws_read(rfile):
    """(opcode, payload) or None at EOF. Reassembles continuation frames:
    a 9KB snapshot can arrive split."""
    data = b''
    first_op = None
    while True:
        hdr = read_exact(rfile, 2)
        if not hdr:
            return None
        fin = hdr[0] & 0x80
        opcode = hdr[0] & 0x0f
        masked = hdr[1] & 0x80
        n = hdr[1] & 0x7f
        if n == 126:
            ext = read_exact(rfile, 2)
            if not ext:
                return None
            n = struct.unpack('>H', ext)[0]
        elif n == 127:
            ext = read_exact(rfile, 8)
            if not ext:
                return None
            n = struct.unpack('>Q', ext)[0]
        if n > 4 << 20:
            return None
        mask = read_exact(rfile, 4) if masked else None
        if masked and mask is None:
            return None
        payload = read_exact(rfile, n) if n else b''
        if payload is None:
            return None
        if mask:
            payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        if first_op is None and opcode != 0:
            first_op = opcode
        data += payload
        if fin:
            return (first_op if first_op is not None else opcode), data


# ── matchmaking ───────────────────────────────────────────────────
def pair(host, guest):
    """Caller holds LOCK. The one who waited longer hosts: they already have
    the tab open and warm, so the match starts sooner."""
    host.partner, guest.partner = guest, host
    host.role, guest.role = 'host', 'guest'
    STATS['paired'] += 1


def dequeue(peer):
    """Caller holds LOCK."""
    try:
        QUEUE.remove(peer)
    except ValueError:
        pass


def find_match(peer):
    with LOCK:
        # drop anyone who left while queued
        while QUEUE and not QUEUE[0].alive:
            QUEUE.pop(0)
        if peer.partner is not None:
            return None, 0
        dequeue(peer)
        if QUEUE:
            other = QUEUE.pop(0)
            pair(other, peer)
            return other, 0
        QUEUE.append(peer)
        return None, len(QUEUE)


# ── handler ───────────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def translate_path(self, path):
        if path in ('/', '/index.html'):
            path = '/' + GAME
        return SimpleHTTPRequestHandler.translate_path(self, path)

    def do_GET(self):
        route = self.path.split('?')[0]
        if route == '/ws':
            return self.websocket()
        if route in ('/healthz', '/stats'):
            with LOCK:
                body = json.dumps({'ok': True, 'waiting': len(QUEUE),
                                   'live': STATS['live'], 'paired': STATS['paired']}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return SimpleHTTPRequestHandler.do_GET(self)

    def websocket(self):
        key = self.headers.get('Sec-WebSocket-Key')
        if not key or 'websocket' not in (self.headers.get('Upgrade') or '').lower():
            self.send_error(400, 'expected a websocket upgrade')
            return
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        self.send_response(101, 'Switching Protocols')
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', accept)
        self.end_headers()
        self.wfile.flush()

        peer = Peer(self)
        with LOCK:
            STATS['live'] += 1
        try:
            self.pump(peer)
        except Exception:
            pass
        finally:
            self.drop(peer)

    def pump(self, peer):
        while True:
            frame = ws_read(self.rfile)
            if frame is None:
                return
            opcode, payload = frame
            if opcode == 0x8:
                return
            if opcode == 0x9:
                with peer.lock:
                    self.wfile.write(ws_frame(payload, 0xA))
                    self.wfile.flush()
                continue
            if opcode != 0x1:
                continue
            try:
                msg = json.loads(payload.decode('utf-8'))
            except Exception:
                continue
            self.route(peer, msg)

    def route(self, peer, msg):
        t = msg.get('t')

        if t == 'find':
            other, ahead = find_match(peer)
            if other is not None:
                other.send({'t': 'paired', 'role': 'host'})
                peer.send({'t': 'paired', 'role': 'guest'})
                log('paired (%d total, %d still waiting)' % (STATS['paired'], len(QUEUE)))
            else:
                peer.send({'t': 'waiting', 'n': ahead})
            return

        if t == 'cancel':
            with LOCK:
                dequeue(peer)
            peer.send({'t': 'idle'})
            return

        if t == 'msg':
            other = peer.partner
            if other is not None and other.alive:
                other.send({'t': 'msg', 'm': msg.get('m')})
            return

    def drop(self, peer):
        peer.alive = False
        with LOCK:
            STATS['live'] -= 1
            dequeue(peer)
            other = peer.partner
            peer.partner = None
            if other is not None:
                other.partner = None
        if other is not None and other.alive:
            other.send({'t': 'gone'})
            log('a match ended (partner left)')


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description='NEON SIEGE 2 co-op matchmaking server')
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8765)))
    ap.add_argument('--host', default='0.0.0.0')
    args = ap.parse_args()

    os.chdir(HERE)
    if not os.path.exists(GAME):
        log('!! %s is missing — keep it next to server.py' % GAME)
        sys.exit(1)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    log('NEON SIEGE 2 matchmaking on :%d' % args.port)
    if not os.environ.get('RENDER'):
        log('  you:        http://localhost:%d' % args.port)
        log('  same wifi:  http://%s:%d' % (lan_ip(), args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log('stopped')


if __name__ == '__main__':
    main()
