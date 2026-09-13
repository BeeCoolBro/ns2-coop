#!/usr/bin/env python3
"""NEON SIEGE 2 co-op server — pairs two players by room code.

Locally:      python server.py
On Render:    start command `python server.py`, which reads $PORT.

The server is a dumb pipe. It never parses a game message, never simulates
anything, and keeps no state beyond "these two sockets are paired" — the host
stays authoritative exactly as it is on a direct peer-to-peer link.

Standard library only, so there is nothing to install and nothing to break on
deploy. The WebSocket layer is a small RFC 6455 implementation; pulling in a
framework for ~120 lines of framing would be the project's only dependency.
"""
import argparse
import base64
import hashlib
import json
import os
import random
import socket
import struct
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = 'neon-siege-2-coop.html'

ROOMS = {}
ROOMS_LOCK = threading.Lock()
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # no O/0, no I/1
ROOM_TTL = 15 * 60          # an abandoned room is forgotten after this


def log(*a):
    print(*a, flush=True)


def new_code():
    while True:
        c = ''.join(random.choice(CODE_ALPHABET) for _ in range(4))
        if c not in ROOMS:
            return c


class Room(object):
    def __init__(self, code, host):
        self.code = code
        self.host = host
        self.guest = None
        self.touched = time.time()

    def partner_of(self, peer):
        return self.guest if peer is self.host else self.host


class Peer(object):
    """One websocket. `send` is serialised: the two directions run on separate
    threads and must never interleave frames on the same socket."""

    def __init__(self, handler):
        self.h = handler
        self.lock = threading.Lock()
        self.room = None
        self.role = None
        self.alive = True

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
    """Returns (opcode, payload) or None at EOF. Reassembles continuation
    frames: a 9KB snapshot can arrive split."""
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
        if route == '/healthz':
            body = b'ok'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
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
            if opcode == 0x9:                       # ping -> pong
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

        if t == 'host':
            want = str(msg.get('code', '') or '').strip().upper()
            with ROOMS_LOCK:
                sweep()
                room = ROOMS.get(want) if want else None
                # A host that dropped (deploy, sleeping instance, flaky wifi) can
                # reclaim its own code, so the code the guest was given still works.
                if room is not None and (room.host is None or not room.host.alive):
                    room.host = peer
                    room.touched = time.time()
                    code = want
                    reclaimed = True
                else:
                    code = new_code()
                    ROOMS[code] = Room(code, peer)
                    reclaimed = False
                other = ROOMS[code].guest
            peer.room, peer.role = code, 'host'
            peer.send({'t': 'hosted', 'code': code})
            log('[room %s] host %s' % (code, 'reclaimed' if reclaimed else 'connected'))
            if other is not None and other.alive:
                peer.send({'t': 'paired', 'role': 'host', 'code': code})
                other.send({'t': 'paired', 'role': 'guest', 'code': code})
            return

        if t == 'join':
            code = str(msg.get('code', '') or '').strip().upper()
            with ROOMS_LOCK:
                sweep()
                room = ROOMS.get(code)
                if room is None:
                    peer.send({'t': 'error', 'msg': 'no room called ' + (code or '?')})
                    return
                if room.guest is not None and room.guest.alive and room.guest is not peer:
                    peer.send({'t': 'error', 'msg': 'room ' + code + ' is full'})
                    return
                room.guest = peer
                room.touched = time.time()
                host = room.host
            peer.room, peer.role = code, 'guest'
            peer.send({'t': 'paired', 'role': 'guest', 'code': code})
            if host is not None and host.alive:
                host.send({'t': 'paired', 'role': 'host', 'code': code})
            log('[room %s] guest joined' % code)
            return

        if t == 'msg':
            room = ROOMS.get(peer.room) if peer.room else None
            if not room:
                return
            room.touched = time.time()
            other = room.partner_of(peer)
            if other is not None and other.alive:
                other.send({'t': 'msg', 'm': msg.get('m')})

    def drop(self, peer):
        peer.alive = False
        code = peer.room
        if not code:
            return
        with ROOMS_LOCK:
            room = ROOMS.get(code)
            if not room:
                return
            other = room.partner_of(peer)
            if peer is room.host:
                # keep the room briefly so a reconnecting host keeps its code
                room.host = None
                room.touched = time.time()
                log('[room %s] host dropped (code held %ds)' % (code, ROOM_TTL))
            elif peer is room.guest:
                room.guest = None
                room.touched = time.time()
                log('[room %s] guest left' % code)
        if other is not None and other.alive:
            other.send({'t': 'gone'})


def sweep():
    """Forget rooms nobody came back to. Caller holds ROOMS_LOCK."""
    now = time.time()
    for code in [c for c, r in ROOMS.items()
                 if (r.host is None or not r.host.alive)
                 and (r.guest is None or not r.guest.alive)
                 and now - r.touched > ROOM_TTL]:
        ROOMS.pop(code, None)
        log('[room %s] expired' % code)


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
    ap = argparse.ArgumentParser(description='NEON SIEGE 2 co-op server')
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8765)))
    ap.add_argument('--host', default='0.0.0.0')
    args = ap.parse_args()

    os.chdir(HERE)
    if not os.path.exists(GAME):
        log('!! %s is missing — keep it next to server.py' % GAME)
        sys.exit(1)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    log('NEON SIEGE 2 co-op server on :%d' % args.port)
    if os.environ.get('RENDER'):
        log('  running on Render')
    else:
        log('  you:        http://localhost:%d' % args.port)
        log('  same wifi:  http://%s:%d' % (lan_ip(), args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log('stopped')


if __name__ == '__main__':
    main()
