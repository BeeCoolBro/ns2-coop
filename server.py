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
import hmac
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

# ── dev mode ──────────────────────────────────────────────────────
# OFF unless you set DEV_KEY in the environment. There is deliberately no
# default: this repo is public and the client is served to everyone, so a
# credential written here would be a working backdoor into your own deployment
# for anyone who reads the source. Unset means every admin request is refused
# outright, so a fresh deploy has no dev mode at all.
# Render: Environment -> Add Environment Variable -> DEV_KEY.
# The passphrase typed into the page only opens the panel on that machine; it
# proves nothing to the server, which checks this value and nothing else.
DEV_KEY = os.environ.get('DEV_KEY', '')
MATCHES = {}                    # id -> {'host', 'guest', 'spec': set, 'start': frame}
NEXT_ID = [1]


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
        self.admin = False
        self.match = None       # id of the match this peer plays in
        self.watching = None    # id of the match this peer spectates

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
    mid = NEXT_ID[0]
    NEXT_ID[0] += 1
    host.match = guest.match = mid
    MATCHES[mid] = {'host': host, 'guest': guest, 'spec': set(), 'start': None,
                    'since': time.time()}
    STATS['paired'] += 1


def close_match(mid):
    """Caller holds LOCK."""
    m = MATCHES.pop(mid, None)
    if not m:
        return set()
    return set(m['spec'])


def watcher_count(mid):
    """Tell a game how many people are watching it. It streams only while that
    is above zero -- otherwise every solo campaign run in the world would be
    uploading a snapshot 15 times a second for nobody."""
    with LOCK:
        m = MATCHES.get(mid)
        if not m:
            return
        owner, n = m['host'], len(m['spec'])
    if owner is not None and owner.alive:
        owner.send({'t': 'watchers', 'n': n})


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
                                   'live': STATS['live'], 'paired': STATS['paired'],
                                   'matches': len(MATCHES)}).encode()
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

        if t == 'session':
            # any game at all, campaign included -- one player, no partner
            with LOCK:
                if peer.match is None:
                    mid = NEXT_ID[0]
                    NEXT_ID[0] += 1
                    peer.match = mid
                    peer.role = 'host'
                    MATCHES[mid] = {'host': peer, 'guest': None, 'spec': set(),
                                    'start': None, 'since': time.time(), 'solo': True}
                mid = peer.match
            peer.send({'t': 'session', 'id': mid, 'n': 0})
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
            # Spectators see whatever the host is telling its guest. This is the
            # one place the server looks inside a game frame, and only at 'k':
            # a spectator who joins mid-match needs the 'start' that set the map
            # up, which it missed, so that one frame is remembered and replayed.
            if peer.role == 'host' and peer.match:
                body = msg.get('m')
                with LOCK:
                    m = MATCHES.get(peer.match)
                    if m is not None:
                        if isinstance(body, dict) and body.get('k') == 'start':
                            m['start'] = body
                        watchers = [w for w in m['spec'] if w.alive]
                    else:
                        watchers = []
                for w in watchers:
                    w.send({'t': 'msg', 'm': body})
            return

        # ── dev mode ──────────────────────────────────────────────
        if t == 'admin':
            # constant-time, and an unset DEV_KEY can never match
            ok = bool(DEV_KEY) and hmac.compare_digest(str(msg.get('key') or ''), DEV_KEY)
            peer.admin = ok
            peer.send({'t': 'admin', 'ok': ok})
            log('dev mode %s' % ('unlocked' if ok else 'REFUSED'))
            return

        if not peer.admin:
            return              # everything below is admin-only

        if t == 'list':
            with LOCK:
                rows = [{'id': mid, 'spectators': len(m['spec']),
                         'mins': round((time.time() - m['since']) / 60, 1),
                         'ready': m['start'] is not None,
                         'solo': bool(m.get('solo'))}
                        for mid, m in sorted(MATCHES.items())]
            peer.send({'t': 'matches', 'rows': rows})
            return

        if t == 'watch':
            mid = msg.get('id')
            old_id = peer.watching
            with LOCK:
                old = MATCHES.get(peer.watching)
                if old is not None:
                    old['spec'].discard(peer)
                m = MATCHES.get(mid)
                if m is None:
                    peer.watching = None
                    peer.send({'t': 'watch', 'ok': False})
                    return
                m['spec'].add(peer)
                peer.watching = mid
                start = m['start']
            peer.send({'t': 'watch', 'ok': True, 'id': mid})
            if start is not None:
                peer.send({'t': 'msg', 'm': start})
            watcher_count(mid)
            if old is not None and old is not m:
                watcher_count(old_id)
            return

        if t == 'unwatch':
            left = peer.watching
            with LOCK:
                m = MATCHES.get(peer.watching)
                if m is not None:
                    m['spec'].discard(peer)
                peer.watching = None
            peer.send({'t': 'watch', 'ok': False})
            if left is not None:
                watcher_count(left)
            return

        if t == 'inject':
            with LOCK:
                m = MATCHES.get(msg.get('id') or peer.watching)
                host = m['host'] if m else None
            if host is not None and host.alive:
                host.send({'t': 'msg', 'm': {'k': 'dev', 'op': msg.get('op'),
                                             'type': msg.get('type'), 'n': msg.get('n')}})
            return

    def drop(self, peer):
        peer.alive = False
        watchers = set()
        left = peer.watching
        with LOCK:
            STATS['live'] -= 1
            dequeue(peer)
            m = MATCHES.get(peer.watching)
            if m is not None:
                m['spec'].discard(peer)
            if peer.match:
                watchers = close_match(peer.match)
                peer.match = None
            other = peer.partner
            peer.partner = None
            if other is not None:
                other.partner = None
                other.match = None
        if left is not None:
            watcher_count(left)
        for w in watchers:
            if w.alive:
                w.watching = None
                w.send({'t': 'watch', 'ok': False})
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
