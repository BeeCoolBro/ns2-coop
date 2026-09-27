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
import collections
import hashlib
import hmac
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# The chat's filter lives in its own file. If it is ever missing from a
# deploy, the chat switches off and says so -- it does not take the game, the
# vault and the links down with it.
try:
    import chat_filter
except Exception as e:                  # pragma: no cover
    chat_filter = None
    print('!! chat_filter.py could not be loaded (%s): chat is off' % e, flush=True)

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
HERE = os.path.dirname(os.path.abspath(__file__))
GAME = 'neon-siege-2-coop.html'
VAULT = 'vault.html'

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

# ── vault links ───────────────────────────────────────────────────
# The vault's Links tab. Anyone can read the list; changing it takes DEV_KEY,
# checked here. BEESCANFLY opens the vault's dev mode, but it is written in the
# public page source, so it proves nothing to this server.
#
# The list is kept in the GitHub repo, not on this disk: Render's free disk is
# wiped whenever the service sleeps, which is every fifteen idle minutes.
# links.json sits on its own branch so saving a link never redeploys the site.
# Reading needs nothing -- the repo is public. Writing needs GITHUB_TOKEN: a
# fine-grained token for this one repository, Contents: read and write.
# Render: Environment -> Add Environment Variable -> GITHUB_TOKEN.
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_API = os.environ.get('GITHUB_API', 'https://api.github.com').rstrip('/')
LINKS_REPO = os.environ.get('LINKS_REPO', 'BeeCoolBro/ns2-coop')
LINKS_BRANCH = os.environ.get('LINKS_BRANCH', 'vault-data')
LINKS_PATH = 'links.json'
LINKS_TTL = 300                 # seconds a read is trusted before asking GitHub again
LINKS_MAX = 300
LINKS_BODY_MAX = 16384
LINKS = {'list': [], 'sha': None, 'at': 0.0, 'ok': False}
LINKS_LOCK = threading.Lock()   # guards LINKS

# ── chat ──────────────────────────────────────────────────────────
# The vault's Chat tab: one room for everyone on the site. Every message and
# every name goes through chat_filter here, before anyone else sees it. History
# is kept in memory only -- the free disk is wiped when the service sleeps, and
# chat logs have no business in a public repository.
CHAT_HISTORY = 80               # messages a newcomer is shown
CHAT_MAX_LEN = 240
CHAT_NAME_LEN = 20
CHAT_FRAME_MAX = 4096           # bytes; anything larger closes the socket
CHAT_PER_IP = 6                 # chat sockets one address may hold open
CHAT_BURST = 5                  # messages allowed at once...
CHAT_REFILL = 1.2               # ...then one every this many seconds
CHAT_DUP_WINDOW = 20            # the same line twice within this is dropped
CHAT_MUTE_SECS = 30 * 60
CHAT_RENAME_GAP = 2.0           # seconds between name changes
CHAT_MENTIONS_MAX = 3           # names one message may mention
CHAT_SALT = os.urandom(16)      # addresses are kept only as salted hashes
CHAT = {'peers': set(), 'history': collections.deque(maxlen=CHAT_HISTORY), 'next': 1, 'muted': {}}
CHAT_LOCK = threading.Lock()
# names nobody but the owner may take
CHAT_RESERVED = re.compile(r'owner|admin|moderator|\bmod\b|staff|official|developer|\bdev\b|system|server|beecoolbro',
                           re.I)
LINKS_WRITE = threading.Lock()  # one save at a time, across the whole GitHub round trip
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
def gh(method, path, body=None):
    """One GitHub REST call. Returns (status, parsed body or None); 0 = no answer."""
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(GITHUB_API + path, data=data, method=method)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('X-GitHub-Api-Version', '2022-11-28')
    req.add_header('User-Agent', 'ns2-coop-vault-links')
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    if GITHUB_TOKEN:
        req.add_header('Authorization', 'Bearer ' + GITHUB_TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
            return e.code, (json.loads(raw) if raw else None)
        except Exception:
            return e.code, None
    except Exception as e:
        log('github %s %s failed: %s' % (method, path.split('?')[0], e))
        return 0, None


def tidy(v, n):
    """Printable text, whitespace collapsed, at most n characters."""
    t = ''.join(ch for ch in str(v or '') if ch.isprintable() or ch.isspace())
    return ' '.join(t.split())[:n]


def safe_url(u):
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return False
    return p.scheme in ('http', 'https') and bool(p.netloc) and len(u) <= 2048


def clean_link(x):
    """A link as stored, or None if it is not one. Applied to everything read
    back as well as everything written, so a hand-edited file cannot slip a
    javascript: address into the page."""
    if not isinstance(x, dict):
        return None
    name = tidy(x.get('name'), 60)
    url = str(x.get('url') or '').strip()
    if not name or not safe_url(url):
        return None
    lid = ''.join(ch for ch in str(x.get('id') or '') if ch.isalnum() or ch in '-_')[:24]
    try:
        added = max(0, int(x.get('added') or 0))
    except (TypeError, ValueError):
        added = 0
    return {'id': lid or new_link_id(), 'name': name, 'url': url,
            'desc': tidy(x.get('desc'), 140), 'added': added}


def new_link_id():
    return base64.urlsafe_b64encode(os.urandom(6)).decode('ascii')


def contents_path():
    return '/repos/%s/contents/%s' % (LINKS_REPO, LINKS_PATH)


def links_load(force=False):
    """Refresh the cache from GitHub when it is stale. True when the cache is
    now current; False when GitHub could not be read (the old cache stands)."""
    with LINKS_LOCK:
        if not force and LINKS['ok'] and time.time() - LINKS['at'] < LINKS_TTL:
            return True
    st, js = gh('GET', contents_path() + '?ref=' + urllib.parse.quote(LINKS_BRANCH, safe=''))
    if st == 200 and isinstance(js, dict) and js.get('type') == 'file':
        try:
            doc = json.loads(base64.b64decode(js.get('content') or '').decode('utf-8'))
        except Exception:
            log('!! %s on %s is not valid JSON; keeping the cached list' % (LINKS_PATH, LINKS_BRANCH))
            return False
        raw = doc.get('links', []) if isinstance(doc, dict) else doc
        items = [c for c in (clean_link(x) for x in (raw if isinstance(raw, list) else [])) if c]
        with LINKS_LOCK:
            LINKS.update(list=items, sha=js.get('sha'), at=time.time(), ok=True)
        return True
    if st == 404:
        # no branch or no file yet: that is an empty list, not a failure
        with LINKS_LOCK:
            LINKS.update(list=[], sha=None, at=time.time(), ok=True)
        return True
    return False


def make_branch():
    """Create the links branch from the default branch's head. Only reached if
    the branch was deleted; normally it already exists."""
    st, repo = gh('GET', '/repos/%s' % LINKS_REPO)
    if st != 200 or not isinstance(repo, dict):
        return False
    base = repo.get('default_branch') or 'main'
    st, ref = gh('GET', '/repos/%s/git/ref/heads/%s' % (LINKS_REPO, urllib.parse.quote(base, safe='')))
    if st != 200 or not isinstance(ref, dict):
        return False
    st, _ = gh('POST', '/repos/%s/git/refs' % LINKS_REPO,
               {'ref': 'refs/heads/' + LINKS_BRANCH, 'sha': ref['object']['sha']})
    return st in (201, 422)         # 422: it appeared in the meantime, which is fine


def links_commit(items, sha, message):
    """Write the list as one commit. ('ok'|'conflict'|'fail', message)."""
    doc = json.dumps({'v': 1, 'links': items}, indent=2, ensure_ascii=False) + '\n'
    body = {'message': message[:120], 'branch': LINKS_BRANCH,
            'content': base64.b64encode(doc.encode('utf-8')).decode('ascii')}
    if sha:
        body['sha'] = sha
    for first in (True, False):
        st, js = gh('PUT', contents_path(), body)
        said = str((js or {}).get('message', '')).lower() if isinstance(js, dict) else ''
        if st in (200, 201):
            new_sha = ((js or {}).get('content') or {}).get('sha')
            with LINKS_LOCK:
                LINKS.update(list=items, sha=new_sha, at=time.time(), ok=True)
            return 'ok', ''
        if st in (404, 422) and 'branch' in said and first:
            if make_branch():
                continue
            return 'fail', "Couldn't create the %s branch on GitHub." % LINKS_BRANCH
        if st == 409 or (st == 422 and 'sha' in said):
            return 'conflict', ''
        if st in (401, 403):
            return 'fail', 'GitHub refused the token. It needs Contents: read and write on %s.' % LINKS_REPO
        if st == 404:
            return 'fail', "GitHub can't see %s with that token. Check which repository it was made for." % LINKS_REPO
        return 'fail', "Couldn't reach GitHub (%s). Try again." % (st or 'no answer')
    return 'fail', "Couldn't save to GitHub."


def links_mutate(change):
    """Apply change(items) -> (new_items, message) | None on top of the newest
    list and commit it. Re-reads first, so a save made on another machine a
    second ago is built on rather than overwritten."""
    with LINKS_WRITE:
        for _ in range(3):
            if not links_load(force=True):
                return 502, {'ok': False, 'error': "Couldn't read the current list from GitHub. Try again."}
            with LINKS_LOCK:
                items = [dict(x) for x in LINKS['list']]
                sha = LINKS['sha']
            try:
                result = change(items)
            except ValueError as e:
                return 400, {'ok': False, 'error': str(e)}
            if result is None:          # nothing to do: say so without a commit
                return 200, {'ok': True, 'links': items}
            new_items, message = result
            st, err = links_commit(new_items, sha, message)
            if st == 'ok':
                return 200, {'ok': True, 'links': new_items}
            if st == 'fail':
                return 502, {'ok': False, 'error': err}
        return 409, {'ok': False, 'error': 'The list kept changing underneath the save. Try again.'}


def links_post(key, raw):
    """One owner request. Returns (http status, reply)."""
    # constant-time, and an unset DEV_KEY can never match
    if not DEV_KEY:
        return 403, {'ok': False, 'error': 'This server has no owner key. Set DEV_KEY in Render -> Environment.'}
    if not hmac.compare_digest(key.encode('utf-8'), DEV_KEY.encode('utf-8')):
        return 403, {'ok': False, 'error': 'That owner key was refused.'}
    try:
        msg = json.loads(raw.decode('utf-8'))
    except Exception:
        return 400, {'ok': False, 'error': 'That request was not JSON.'}
    if not isinstance(msg, dict):
        return 400, {'ok': False, 'error': 'That request was not an object.'}
    if not GITHUB_TOKEN:
        return 503, {'ok': False, 'error': 'Saving is not set up yet. Set GITHUB_TOKEN in Render -> Environment.'}
    op = msg.get('op')

    if op == 'add':
        item = clean_link({'name': msg.get('name'), 'url': msg.get('url'),
                           'desc': msg.get('desc'), 'added': int(time.time())})
        if not item:
            return 400, {'ok': False, 'error': 'A link needs a name and an http:// or https:// address.'}

        def add(items):
            if any(x['url'] == item['url'] for x in items):
                raise ValueError('That address is already on the list.')
            if len(items) >= LINKS_MAX:
                raise ValueError('The list is full (%d links).' % LINKS_MAX)
            return items + [item], 'vault links: add %s' % item['name']
        return links_mutate(add)

    if op == 'remove':
        lid = str(msg.get('id') or '')

        def remove(items):
            gone = [x for x in items if x['id'] == lid]
            if not gone:
                return None             # already removed, maybe from another machine
            return [x for x in items if x['id'] != lid], 'vault links: remove %s' % gone[0]['name']
        return links_mutate(remove)

    return 400, {'ok': False, 'error': 'Unknown request.'}


class ChatPeer(object):
    """One chat socket. Sends are serialised the same way Peer's are."""

    def __init__(self, handler, ip):
        self.h = handler
        self.lock = threading.Lock()
        self.alive = True
        self.ip = ip                    # salted hash, never the address
        self.tokens = float(CHAT_BURST)
        self.refilled = time.time()
        self.last_text = ''
        self.last_at = 0.0
        self.guest = 'Guest-%04d' % (int.from_bytes(os.urandom(2), 'big') % 10000)
        self.name = None                # the name shown for this socket, once it says one
        self.named_at = 0.0

    def shown(self):
        return self.name or self.guest

    def send(self, obj):
        data = json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        with self.lock:
            if not self.alive:
                return
            try:
                self.h.wfile.write(ws_frame(data))
                self.h.wfile.flush()
            except Exception:
                self.alive = False

    def allow(self):
        """A token bucket: a short burst, then a steady trickle."""
        now = time.time()
        self.tokens = min(float(CHAT_BURST), self.tokens + (now - self.refilled) / CHAT_REFILL)
        self.refilled = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


def chat_broadcast(obj, skip=None):
    with CHAT_LOCK:
        peers = list(CHAT['peers'])
    for p in peers:
        if p is not skip:
            p.send(obj)


def owner_ok(key):
    # constant-time, and an unset DEV_KEY can never match
    return bool(DEV_KEY) and isinstance(key, str) and \
        hmac.compare_digest(key.encode('utf-8'), DEV_KEY.encode('utf-8'))


def chat_name(raw, peer, owner):
    name = tidy(raw, CHAT_NAME_LEN)
    if not name or chat_filter.clean(name)[1]:
        return peer.guest
    if not owner and CHAT_RESERVED.search(name):
        return peer.guest
    return name


def chat_roster():
    """Tell everyone who is here."""
    with CHAT_LOCK:
        names = sorted({p.shown() for p in CHAT['peers']}, key=str.lower)
        online = len(CHAT['peers'])
    chat_broadcast({'t': 'roster', 'names': names, 'online': online})


def chat_rename(peer, msg):
    """A page saying what it is called -- on connecting, and whenever the
    vault's name changes. Filtered like a message; answered with the name
    actually shown, which may be a guest name."""
    now = time.time()
    if peer.name is not None and now - peer.named_at < CHAT_RENAME_GAP:
        peer.send({'t': 'you', 'name': peer.shown()})
        return
    wanted = tidy(msg.get('name'), CHAT_NAME_LEN)
    name = chat_name(wanted, peer, owner_ok(msg.get('key')))
    changed = name != peer.shown() or peer.name is None
    peer.name, peer.named_at = name, now
    peer.send({'t': 'you', 'name': name, 'asked': wanted})
    if changed:
        chat_roster()


def chat_mentions(text, names):
    """Names in the room that the text @-mentions. Longest first, so "@Cool
    Bee" is one mention even when someone called "Cool" is also here."""
    found, work = [], text
    for name in sorted(names, key=len, reverse=True):
        pat = re.compile(r'(?<![\w])@' + re.escape(name) + r'(?![\w])', re.I)
        m = pat.search(work)
        if not m:
            continue
        found.append(name)
        # blank out what matched so a shorter name cannot claim the same text
        work = work[:m.start()] + ' ' * (m.end() - m.start()) + work[m.end():]
        if len(found) >= CHAT_MENTIONS_MAX:
            break
    return found


def chat_say(peer, msg):
    text = ' '.join(str(msg.get('text') or '').split())[:CHAT_MAX_LEN]
    if not text:
        return
    now = time.time()
    with CHAT_LOCK:
        until = CHAT['muted'].get(peer.ip, 0)
    if until > now:
        mins = int((until - now) // 60) + 1
        peer.send({'t': 'err', 'code': 'muted', 'msg': 'You are muted for %d more minute%s.' % (mins, '' if mins == 1 else 's')})
        return
    if not peer.allow():
        peer.send({'t': 'err', 'code': 'slow', 'msg': 'Slow down a little.'})
        return
    if text == peer.last_text and now - peer.last_at < CHAT_DUP_WINDOW:
        peer.send({'t': 'err', 'code': 'dup', 'msg': 'You just said that.'})
        return
    peer.last_text, peer.last_at = text, now
    owner = owner_ok(msg.get('key'))
    # the name this socket is known by; a page that never said one is named
    # from the message, the way the first version of the chat worked
    name = peer.name if peer.name is not None else chat_name(msg.get('name'), peer, owner)
    clean, changed = chat_filter.clean(text)
    with CHAT_LOCK:
        here = {p.shown() for p in CHAT['peers']}
        mid = CHAT['next']
        CHAT['next'] += 1
        m = {'id': mid, 'name': name, 'text': clean, 'at': int(now * 1000)}
        mentions = chat_mentions(clean, here - {name})
        if mentions:
            m['mentions'] = mentions
        if owner:
            m['owner'] = True
        # a random tag the sender chose, so its own page can tell which
        # messages are its own; it identifies nobody to anyone else
        tag = str(msg.get('n') or '')
        if tag.isalnum() and len(tag) <= 12:
            m['n'] = tag
        CHAT['history'].append((m, peer.ip))
    chat_broadcast({'t': 'msg', 'm': m})
    if changed:
        peer.send({'t': 'filtered'})


def chat_mod(peer, msg):
    if not owner_ok(msg.get('key')):
        peer.send({'t': 'err', 'code': 'key', 'msg': 'That owner key was refused.'})
        return
    op, mid = msg.get('op'), msg.get('id')
    now = time.time()
    if op == 'clear':
        with CHAT_LOCK:
            CHAT['history'].clear()
        chat_broadcast({'t': 'clear'})
    elif op in ('delete', 'mute'):
        with CHAT_LOCK:
            hit = [(m, ip) for (m, ip) in CHAT['history'] if m['id'] == mid]
            if hit:
                CHAT['history'] = collections.deque(
                    [(m, ip) for (m, ip) in CHAT['history'] if m['id'] != mid], maxlen=CHAT_HISTORY)
                if op == 'mute':
                    CHAT['muted'][hit[0][1]] = now + CHAT_MUTE_SECS
            # forget mutes that have run out
            CHAT['muted'] = {ip: t for ip, t in CHAT['muted'].items() if t > now}
        if hit:
            chat_broadcast({'t': 'del', 'id': mid})
    else:
        return
    peer.send({'t': 'mod-ok', 'op': op})


class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    # Set while serving a file off disk, so the cache header lands on the game
    # and not on the websocket handshake or the health endpoint.
    revalidate = False

    def translate_path(self, path):
        if path in ('/', '/index.html'):
            path = '/' + GAME
        # Bee's Vault rides along as its own page. It is nothing to do with the
        # game and shares none of its state; it is here because this is the
        # host that is already wired to the repo.
        elif path in ('/vault', '/vault/'):
            path = '/' + VAULT
        return SimpleHTTPRequestHandler.translate_path(self, path)

    def end_headers(self):
        # The game is a single HTML file and it changes every deploy. Without a
        # directive the browser caches it heuristically off Last-Modified and
        # can serve a days-old copy, which is how one player ends up reporting
        # prices and bugs from a build that no longer exists. no-cache means
        # "revalidate", not "do not store": an unchanged file still answers 304.
        if self.revalidate:
            self.send_header('Cache-Control', 'no-cache, must-revalidate')
        SimpleHTTPRequestHandler.end_headers(self)

    def do_GET(self):
        # Reset per request: a keep-alive connection reuses this instance, and
        # the flag belongs to the file being served, not to the socket.
        self.revalidate = False
        route = self.path.split('?')[0]
        if route == '/ws':
            return self.websocket()
        if route == '/chat':
            return self.chat_socket()
        if route == '/api/links':
            # a failed refresh with an older list in hand serves the older list;
            # with nothing in hand it says so, rather than claiming there are none
            fresh = links_load()
            with LINKS_LOCK:
                ok, items = LINKS['ok'], list(LINKS['list'])
            if not fresh and not ok:
                return self.send_json(502, {'links': [], 'error': "Couldn't read the links from GitHub."})
            return self.send_json(200, {'links': items, 'writable': bool(DEV_KEY and GITHUB_TOKEN)})
        if route in ('/healthz', '/stats'):
            with LOCK:
                body = json.dumps({'ok': True, 'waiting': len(QUEUE),
                                   'live': STATS['live'], 'paired': STATS['paired'],
                                   'matches': len(MATCHES), 'chat': len(CHAT['peers'])}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.revalidate = True
        return SimpleHTTPRequestHandler.do_GET(self)

    # ── the links API ────────────────────────────────────────────
    # Open to every origin: the vault can be opened from a copy on disk, and
    # CORS is no defence for a write endpoint anyway -- the key is.
    def cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Dev-Key')
        self.send_header('Access-Control-Max-Age', '86400')

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.revalidate = False
        if self.path.split('?')[0] == '/api/links':
            self.send_response(204)
            self.cors()
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self.send_response(405)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        self.revalidate = False
        if self.path.split('?')[0] != '/api/links':
            self.close_connection = True
            return self.send_json(404, {'ok': False, 'error': 'Not found.'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > LINKS_BODY_MAX:
            # the body was not read, so this connection cannot be reused
            self.close_connection = True
            return self.send_json(413 if n > LINKS_BODY_MAX else 400,
                                  {'ok': False, 'error': 'Bad request size.'})
        code, reply = links_post(self.headers.get('X-Dev-Key') or '', self.rfile.read(n))
        return self.send_json(code, reply)

    def ws_accept(self):
        """Answer a websocket upgrade. False, with a 400 sent, if it is not one."""
        key = self.headers.get('Sec-WebSocket-Key')
        if not key or 'websocket' not in (self.headers.get('Upgrade') or '').lower():
            self.send_error(400, 'expected a websocket upgrade')
            return False
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        self.send_response(101, 'Switching Protocols')
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', accept)
        self.end_headers()
        self.wfile.flush()
        return True

    def client_ip(self):
        """The caller's address as a salted hash. Behind Render's proxy the real
        address is the last X-Forwarded-For entry; anything before it is
        whatever the client chose to send."""
        fwd = [p.strip() for p in (self.headers.get('X-Forwarded-For') or '').split(',') if p.strip()]
        ip = fwd[-1] if fwd else self.client_address[0]
        return hashlib.sha256(CHAT_SALT + ip.encode('utf-8', 'replace')).hexdigest()[:16]

    def chat_socket(self):
        if chat_filter is None:
            # no filter, no chat: an unfiltered room is not an option
            return self.send_json(503, {'ok': False, 'error': 'Chat is offline.'})
        ip = self.client_ip()
        with CHAT_LOCK:
            held = sum(1 for p in CHAT['peers'] if p.ip == ip)
        if not self.ws_accept():
            return
        peer = ChatPeer(self, ip)
        if held >= CHAT_PER_IP:
            peer.send({'t': 'err', 'code': 'busy', 'msg': 'Too many chat windows open from here.'})
            return
        with CHAT_LOCK:
            CHAT['peers'].add(peer)
            history = [m for (m, _) in CHAT['history']]
            online = len(CHAT['peers'])
            names = sorted({p.shown() for p in CHAT['peers']}, key=str.lower)
        peer.send({'t': 'hello', 'history': history, 'online': online, 'names': names})
        chat_roster()
        try:
            self.chat_pump(peer)
        except Exception:
            pass
        finally:
            peer.alive = False
            with CHAT_LOCK:
                CHAT['peers'].discard(peer)
            chat_roster()

    def chat_pump(self, peer):
        while True:
            frame = ws_read(self.rfile)
            if frame is None:
                return
            opcode, payload = frame
            if opcode == 0x8 or len(payload) > CHAT_FRAME_MAX:
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
            if not isinstance(msg, dict):
                continue
            t = msg.get('t')
            if t == 'say':
                chat_say(peer, msg)
            elif t in ('hi', 'name'):
                chat_rename(peer, msg)
            elif t == 'mod':
                chat_mod(peer, msg)
            elif t == 'ping':
                peer.send({'t': 'pong'})

    def websocket(self):
        if not self.ws_accept():
            return

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
    log('  vault links: %s@%s, saving %s' % (
        LINKS_REPO, LINKS_BRANCH,
        'on' if (DEV_KEY and GITHUB_TOKEN) else
        'OFF (set %s)' % ' and '.join(k for k, v in (('DEV_KEY', DEV_KEY), ('GITHUB_TOKEN', GITHUB_TOKEN)) if not v)))
    threading.Thread(target=links_load, daemon=True).start()
    if not os.environ.get('RENDER'):
        log('  you:        http://localhost:%d' % args.port)
        log('  same wifi:  http://%s:%d' % (lan_ip(), args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log('stopped')


if __name__ == '__main__':
    main()
