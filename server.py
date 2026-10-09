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
HOME = 'index.html'              # BeeSide Studio's: the way into both
GAME = 'neon-siege-2-coop.html'
VAULT = 'vault.html'
PROJECTS = 'projects.html'        # Other Projects: the smaller ones
ROTFALL = 'rotfall.html'          # the first of them: a survival shooter
ROTFALL2 = 'rotfall-2.html'       # its sequel, a door of its own on the front page
NEONSIEGE1 = 'neon-siege-1.html'  # the first NEON SIEGE, from BeeCoolBro/Neon-Siege (its Vercel site is off)
# ── The off switches ──────────────────────────────────────────────
# Each place can be closed for a while: list its name in the file CLOSED (one
# per line) and deploy. A closed place shows closed.html, a short "closed for a
# moment" page, at its address and at its file's name; its door on the front
# page (and on Other Projects) is greyed out; the vault's chat and the game's
# co-op take no new connections while theirs is closed. Take the line out, or
# put a # in front of it, and deploy to open it again. 'all' closes the whole of
# BeeSide Studio's: the front page as well as every place (/healthz stays up,
# so Render doesn't think the server is down). 'fake' does the same, but every
# page shows fake.html instead: a plain made-up hobby site with nothing on it
# that leads back here, and /api/closed stops answering.
CLOSED_FILE = 'CLOSED'
CLOSED_PAGE = 'closed.html'
FAKE_PAGE = 'fake.html'
PLACES = {   # name in CLOSED: its address, then every file that is that place
    'vault': ('/vault', VAULT),
    'neon-siege': ('/neon-siege', GAME, 'neon-siege-2.html'),
    'rotfall': ('/rotfall', ROTFALL),
    'rotfall-2': ('/rotfall-2', ROTFALL2),
    'neon-siege-1': ('/neon-siege-1', NEONSIEGE1),
    'projects': ('/projects', PROJECTS),
}
ROUTE_PLACE = {}
for _name, (_route, *_files) in PLACES.items():
    ROUTE_PLACE[_route] = ROUTE_PLACE[_route + '/'] = _name
    for _f in _files:
        ROUTE_PLACE['/' + _f] = _name
ROUTE_PLACE['/'] = ROUTE_PLACE['/' + HOME] = 'all'   # the front page closes only with everything
ROUTE_PLACE['/' + CLOSED_PAGE] = 'all'               # and with 'fake', the closed page itself hides too


def closed_places():
    """The places switched off right now. Read on every request, so it is only
    ever as old as the deploy."""
    try:
        with open(os.path.join(HERE, CLOSED_FILE), encoding='utf-8') as f:
            names = [line.split('#', 1)[0].strip().lower() for line in f]
    except OSError:
        return set()
    if 'fake' in names:
        return set(PLACES) | {'all', 'fake'}
    if 'all' in names:
        return set(PLACES) | {'all'}
    return {n for n in names if n in PLACES}


def shut_page(path):
    """The page to show instead of this address, or None when it's open."""
    name = ROUTE_PLACE.get(path.split('?', 1)[0].split('#', 1)[0])
    if not name:
        return None
    shut = closed_places()
    if name not in shut:
        return None
    return FAKE_PAGE if 'fake' in shut else CLOSED_PAGE

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
LINKS = {'list': [], 'sugg': [], 'sha': None, 'at': 0.0, 'ok': False}
LINKS_LOCK = threading.Lock()   # guards LINKS

# ── link suggestions ──────────────────────────────────────────────
# Anyone may suggest a link. It waits in links.json, beside the list, until the
# owner accepts or denies it in the vault; only a request with DEV_KEY is shown
# the waiting ones. Every suggestion is a commit, so they are rationed per
# address and overall. The repo is public, so the form asks for nothing but
# the link and says where it is kept.
SUGG_MAX = 40                   # suggestions waiting at once
SUGG_GAP = 45                   # seconds between two from one address
SUGG_PER_HOUR = 6               # from one address in an hour
SUGG_ALL_PER_HOUR = 40          # from everyone in an hour
SUGG_BODY_MAX = 4096
SUGG_LOG = {}                   # address hash -> deque of when it suggested
SUGG_ALL = collections.deque()  # when anyone suggested
SUGG_LOCK = threading.Lock()

# ── ideas ─────────────────────────────────────────────────────────
# The vault's Ideas tab: anyone may send the owner an idea -- a game to add,
# a feature, a fix. Kept as ideas.json on the data branch like the links, read
# only with DEV_KEY, and rationed like link suggestions. Swearing is masked and
# email addresses removed before anything is stored: the repo is public.
IDEAS_PATH = 'ideas.json'
IDEAS_TTL = 300
IDEAS_MAX = 150                 # ideas waiting at once
IDEA_LEN = 500
IDEA_KINDS = ('broken', 'game', 'feature', 'fix', 'other')   # broken: a game that doesn't work
IDEA_GAP = 60                   # seconds between two from one address
IDEA_PER_HOUR = 5
IDEA_ALL_PER_HOUR = 40
IDEAS_BODY_MAX = 4096
IDEAS = {'list': [], 'sha': None, 'at': 0.0, 'ok': False}
IDEAS_LOCK = threading.Lock()
IDEAS_WRITE = threading.Lock()
IDEA_LOG = {}
IDEA_ALL = collections.deque()

# ── vault lyrics ──────────────────────────────────────────────────
# Timed lyrics for the music player, typed in by the owner in the vault's
# lyrics tool: a map from a track's address to its lines and the second each
# starts. Kept like the links -- lyrics.json on the same branch, read by
# anyone, written only with DEV_KEY.
LYRICS_PATH = 'lyrics.json'
LYRICS_TTL = 300
LYRICS_BODY_MAX = 65536         # one song's lines with their times
LYRICS_TRACKS_MAX = 200
LYRICS_LINES_MAX = 300
LYRICS_LINE_LEN = 160
LYRICS = {'map': {}, 'sha': None, 'at': 0.0, 'ok': False}
LYRICS_LOCK = threading.Lock()
LYRICS_WRITE = threading.Lock()

# ── chat ──────────────────────────────────────────────────────────
# The vault's Chat tab: one room for everyone on the site. Every message and
# every name goes through chat_filter here, before anyone else sees it. History
# is kept in memory only -- the free disk is wiped when the service sleeps, and
# chat logs have no business in a public repository.
CHAT_HISTORY = 80               # messages a newcomer is shown
CHAT_MAX_LEN = 240
CHAT_NAME_LEN = 20
CHAT_FRAME_MAX = 4096           # bytes; anything larger closes the socket...
CHAT_RTC_FRAME_MAX = 16384      # ...except call setup, whose offers run to a few KB
CHAT_PER_IP = 6                 # chat sockets one address may hold open
CHAT_BURST = 5                  # messages allowed at once...
CHAT_REFILL = 1.2               # ...then one every this many seconds
CHAT_DUP_WINDOW = 20            # the same line twice within this is dropped
CHAT_MUTE_SECS = 30 * 60
CHAT_RENAME_GAP = 2.0           # seconds between name changes
CHAT_MENTIONS_MAX = 3           # names one message may mention
CHAT_SALT = os.urandom(16)      # addresses are kept only as salted hashes
CHAT = {'peers': set(), 'history': collections.deque(maxlen=CHAT_HISTORY), 'next': 1, 'muted': {}}

# ── play together ─────────────────────────────────────────────────
# Requests to watch someone's game or to play one with them. The picture of a
# watched game never comes through here: the two browsers connect directly and
# this server only relays their setup messages, within a session both agreed to.
RQ_TTL = 60                     # seconds a request waits for an answer
RQ_GAP = 15                     # seconds between two requests to the same person
RQ_PER_MIN = 8                  # requests one socket may send in a minute
RTC_PER_MIN = 400               # call-setup messages one socket may send in a minute
WATCH_MAX = 4                   # people who may watch one screen at once
RQ_WHY = ('blocked', 'unsupported', 'cancelled', 'missing', 'busy', 'timeout')
RQ = {}                         # rid -> {'frm', 'to', 'kind', 'game', 'at'}
SESS = {}                       # sid -> {'sharer', 'viewer'}
CHAT_LOCK = threading.Lock()

# ── Popular: how often each vault game gets opened ──────────────────
# The vault tells us when someone opens a game (POST /api/play) and asks for
# the most played ones (GET /api/popular). A play fades with time -- it counts
# half as much two weeks later -- so the list follows what people play now.
# Counts are kept on the vault-data branch as plays.json, saved every few
# minutes when something changed, and read back when the server starts.
# Addresses are only ever hashed, never stored, and each one counts a game
# once per half hour, up to PLAYS_PER_HOUR games an hour.
PLAYS_PATH = 'plays.json'
PLAYS_HALF_LIFE = 14 * 86400
PLAYS_SAVE_EVERY = 300          # seconds between saves when something changed
PLAYS_KEEP = 2000               # games remembered
PLAYS_GAP = 1800                # one address counts a game once per this
PLAYS_PER_HOUR = 40             # games one address can count in an hour
PLAYS_BODY_MAX = 1024
PLAYS_LOCK = threading.Lock()
PLAYS = {'map': {}, 'sha': None, 'loaded': False, 'dirty': False, 'saved_at': 0.0}
PLAY_SEEN = {}                  # (address hash, game) -> when it last counted
PLAY_IP = {}                    # address hash -> deque of when it counted
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


def clean_sugg(x):
    """A waiting suggestion: a link, plus the vault name it was sent under."""
    item = clean_link(x)
    if not item:
        return None
    item['from'] = tidy(x.get('from'), CHAT_NAME_LEN)
    return item


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
        raw = doc.get('suggested', []) if isinstance(doc, dict) else []
        sugg = [c for c in (clean_sugg(x) for x in (raw if isinstance(raw, list) else [])) if c][:SUGG_MAX]
        with LINKS_LOCK:
            LINKS.update(list=items, sugg=sugg, sha=js.get('sha'), at=time.time(), ok=True)
        return True
    if st == 404:
        # no branch or no file yet: that is an empty list, not a failure
        with LINKS_LOCK:
            LINKS.update(list=[], sugg=[], sha=None, at=time.time(), ok=True)
        return True
    return False


def plays_score(entry, now):
    """A game's play score as of now, with every play faded by its age."""
    return entry['s'] * 0.5 ** (max(0.0, now - entry['t']) / PLAYS_HALF_LIFE)


def plays_key(raw):
    """The game a play is for: its address, or 'name:' and its name for a game
    that lives inside the vault itself. None if it's neither."""
    if not isinstance(raw, str):
        return None
    k = raw.strip()
    if not (1 <= len(k) <= 300) or any(ord(c) < 32 for c in k):
        return None
    if k.startswith(('https://', 'http://', 'name:')):
        return k
    return None


def plays_path():
    return '/repos/%s/contents/%s' % (LINKS_REPO, PLAYS_PATH)


def plays_load():
    """Read the counts saved on GitHub, adding them to any made since start."""
    if not GITHUB_TOKEN:
        with PLAYS_LOCK:
            PLAYS['loaded'] = True
        return
    st, js = gh('GET', plays_path() + '?ref=' + urllib.parse.quote(LINKS_BRANCH, safe=''))
    saved = {}
    if st == 200 and isinstance(js, dict) and js.get('type') == 'file':
        try:
            doc = json.loads(base64.b64decode(js.get('content') or '').decode('utf-8'))
            for k, e in (doc.get('plays') or {}).items():
                if plays_key(k) and isinstance(e, dict):
                    saved[k] = {'s': float(e.get('s') or 0), 't': float(e.get('t') or 0), 'n': int(e.get('n') or 0)}
        except Exception:
            log('!! %s on %s is not valid JSON; starting the counts over' % (PLAYS_PATH, LINKS_BRANCH))
    elif st not in (200, 404):
        log('!! could not read %s (%s); counting from zero for now' % (PLAYS_PATH, st))
    now = time.time()
    with PLAYS_LOCK:
        mine = PLAYS['map']
        for k, e in saved.items():
            if k in mine:          # counted since start: add the two together
                m = mine[k]
                m['s'] = plays_score(m, now) + plays_score(e, now)
                m['t'] = now
                m['n'] += e['n']
            else:
                mine[k] = e
        PLAYS['sha'] = js.get('sha') if st == 200 and isinstance(js, dict) else None
        PLAYS['loaded'] = True


def plays_save():
    """Write the counts to GitHub if they changed. Runs on its own thread."""
    with PLAYS_LOCK:
        if not (PLAYS['dirty'] and PLAYS['loaded'] and GITHUB_TOKEN):
            return
        now = time.time()
        items = sorted(PLAYS['map'].items(), key=lambda kv: -plays_score(kv[1], now))[:PLAYS_KEEP]
        doc = {'v': 1, 'half_life_days': PLAYS_HALF_LIFE / 86400,
               'plays': {k: {'s': round(e['s'], 4), 't': int(e['t']), 'n': e['n']} for k, e in items}}
        sha = PLAYS['sha']
        PLAYS['dirty'] = False
    body = {'message': 'Vault play counts', 'branch': LINKS_BRANCH,
            'content': base64.b64encode((json.dumps(doc, separators=(',', ':')) + '\n').encode('utf-8')).decode('ascii')}
    if sha:
        body['sha'] = sha
    st, js = gh('PUT', plays_path(), body)
    with PLAYS_LOCK:
        if st in (200, 201):
            PLAYS['sha'] = ((js or {}).get('content') or {}).get('sha')
            PLAYS['saved_at'] = time.time()
        else:
            PLAYS['dirty'] = True          # try again next time
            if st in (409, 422):
                PLAYS['sha'] = None        # someone else wrote it: fetch its sha below
    if st in (409, 422):
        st2, js2 = gh('GET', plays_path() + '?ref=' + urllib.parse.quote(LINKS_BRANCH, safe=''))
        if st2 == 200 and isinstance(js2, dict):
            with PLAYS_LOCK:
                PLAYS['sha'] = js2.get('sha')
    elif st not in (200, 201):
        log('!! saving %s failed (%s)' % (PLAYS_PATH, st))


def plays_loop():
    plays_load()
    while True:
        time.sleep(PLAYS_SAVE_EVERY)
        try:
            plays_save()
        except Exception as e:          # pragma: no cover
            log('!! plays save: %s' % e)


def play_post(ip, raw):
    """Someone opened a game in the vault."""
    try:
        msg = json.loads(raw.decode('utf-8'))
    except Exception:
        return 400, {'ok': False}
    key = plays_key(msg.get('u') if isinstance(msg, dict) else None)
    if not key:
        return 400, {'ok': False}
    who = hashlib.sha256(('plays|' + ip).encode('utf-8')).hexdigest()[:16]
    now = time.time()
    with PLAYS_LOCK:
        last = PLAY_SEEN.get((who, key))
        if last and now - last < PLAYS_GAP:
            return 200, {'ok': True, 'counted': False}
        q = PLAY_IP.setdefault(who, collections.deque())
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= PLAYS_PER_HOUR:
            return 200, {'ok': True, 'counted': False}
        q.append(now)
        PLAY_SEEN[(who, key)] = now
        e = PLAYS['map'].get(key)
        if e:
            e['s'] = plays_score(e, now) + 1
            e['t'] = now
            e['n'] += 1
        else:
            PLAYS['map'][key] = {'s': 1.0, 't': now, 'n': 1}
        PLAYS['dirty'] = True
        # forget old entries so these two can't grow without end
        if len(PLAY_SEEN) > 20000:
            for k in [k for k, t in PLAY_SEEN.items() if now - t > PLAYS_GAP]:
                del PLAY_SEEN[k]
        if len(PLAY_IP) > 5000:
            for k in [k for k, d in PLAY_IP.items() if not d or now - d[-1] > 3600]:
                del PLAY_IP[k]
    return 200, {'ok': True, 'counted': True}


def popular_list(limit=60):
    now = time.time()
    with PLAYS_LOCK:
        ranked = sorted(((k, plays_score(e, now), e['n']) for k, e in PLAYS['map'].items()), key=lambda x: -x[1])
    return [{'u': k, 'score': round(sc, 3), 'n': n} for k, sc, n in ranked[:limit] if sc >= 0.05]


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


def links_commit(items, sugg, sha, message):
    """Write the list and the waiting suggestions as one commit.
    ('ok'|'conflict'|'fail', message)."""
    doc = json.dumps({'v': 1, 'links': items, 'suggested': sugg}, indent=2, ensure_ascii=False) + '\n'
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
                LINKS.update(list=items, sugg=sugg, sha=new_sha, at=time.time(), ok=True)
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
    """Apply change(items, sugg) -> (new_items, new_sugg, message) | None on top
    of the newest list and commit it. Re-reads first, so a save made on another
    machine a second ago is built on rather than overwritten."""
    with LINKS_WRITE:
        for _ in range(3):
            if not links_load(force=True):
                return 502, {'ok': False, 'error': "Couldn't read the current list from GitHub. Try again."}
            with LINKS_LOCK:
                items = [dict(x) for x in LINKS['list']]
                sugg = [dict(x) for x in LINKS['sugg']]
                sha = LINKS['sha']
            try:
                result = change(items, sugg)
            except ValueError as e:
                return 400, {'ok': False, 'error': str(e)}
            if result is None:          # nothing to do: say so without a commit
                return 200, {'ok': True, 'links': items, 'suggested': sugg}
            new_items, new_sugg, message = result
            st, err = links_commit(new_items, new_sugg, sha, message)
            if st == 'ok':
                if len(new_sugg) != len(sugg):
                    sugg_notify(len(new_sugg))
                return 200, {'ok': True, 'links': new_items, 'suggested': new_sugg}
            if st == 'fail':
                return 502, {'ok': False, 'error': err}
        return 409, {'ok': False, 'error': 'The list kept changing underneath the save. Try again.'}


def clean_song(track, entry):
    """One song's lyrics as stored -- lines in time order -- or None."""
    if not safe_url(str(track or '')) or not isinstance(entry, dict):
        return None
    lines = []
    for x in (entry.get('lines') if isinstance(entry.get('lines'), list) else [])[:LYRICS_LINES_MAX]:
        if not isinstance(x, dict):
            continue
        try:
            t = round(float(x.get('t')), 2)
        except (TypeError, ValueError):
            continue
        text = tidy(x.get('text'), LYRICS_LINE_LEN)
        if text and 0 <= t <= 3600:
            lines.append({'t': t, 'text': text})
    if not lines:
        return None
    lines.sort(key=lambda l: l['t'])
    try:
        updated = max(0, int(entry.get('updated') or 0))
    except (TypeError, ValueError):
        updated = 0
    return {'title': tidy(entry.get('title'), 80), 'lines': lines, 'updated': updated}


def lyrics_path():
    return '/repos/%s/contents/%s' % (LINKS_REPO, LYRICS_PATH)


def lyrics_load(force=False):
    """Refresh the cache from GitHub when it is stale; False if GitHub could
    not be read (the old cache stands)."""
    with LYRICS_LOCK:
        if not force and LYRICS['ok'] and time.time() - LYRICS['at'] < LYRICS_TTL:
            return True
    st, js = gh('GET', lyrics_path() + '?ref=' + urllib.parse.quote(LINKS_BRANCH, safe=''))
    if st == 200 and isinstance(js, dict) and js.get('type') == 'file':
        try:
            doc = json.loads(base64.b64decode(js.get('content') or '').decode('utf-8'))
        except Exception:
            log('!! %s on %s is not valid JSON; keeping the cached lyrics' % (LYRICS_PATH, LINKS_BRANCH))
            return False
        raw = doc.get('songs', {}) if isinstance(doc, dict) else {}
        songs = {}
        for track, entry in (raw.items() if isinstance(raw, dict) else []):
            c = clean_song(track, entry)
            if c:
                songs[track] = c
        with LYRICS_LOCK:
            LYRICS.update(map=songs, sha=js.get('sha'), at=time.time(), ok=True)
        return True
    if st == 404:
        with LYRICS_LOCK:
            LYRICS.update(map={}, sha=None, at=time.time(), ok=True)
        return True
    return False


def lyrics_commit(songs, sha, message):
    doc = json.dumps({'v': 1, 'songs': songs}, indent=2, ensure_ascii=False) + '\n'
    body = {'message': message[:120], 'branch': LINKS_BRANCH,
            'content': base64.b64encode(doc.encode('utf-8')).decode('ascii')}
    if sha:
        body['sha'] = sha
    for first in (True, False):
        st, js = gh('PUT', lyrics_path(), body)
        said = str((js or {}).get('message', '')).lower() if isinstance(js, dict) else ''
        if st in (200, 201):
            with LYRICS_LOCK:
                LYRICS.update(map=songs, sha=((js or {}).get('content') or {}).get('sha'), at=time.time(), ok=True)
            return 'ok', ''
        if st in (404, 422) and 'branch' in said and first:
            if make_branch():
                continue
            return 'fail', "Couldn't create the %s branch on GitHub." % LINKS_BRANCH
        if st == 409 or (st == 422 and 'sha' in said):
            return 'conflict', ''
        if st in (401, 403):
            return 'fail', 'GitHub refused the token. It needs Contents: read and write on %s.' % LINKS_REPO
        return 'fail', "Couldn't reach GitHub (%s). Try again." % (st or 'no answer')
    return 'fail', "Couldn't save to GitHub."


def lyrics_post(key, raw):
    """One owner request to set or remove a song's lyrics."""
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
    op, track = msg.get('op'), str(msg.get('track') or '')
    if op == 'set':
        song = clean_song(track, {'title': msg.get('title'), 'lines': msg.get('lines'), 'updated': int(time.time())})
        if not song:
            return 400, {'ok': False, 'error': 'Those lyrics have no lines with times.'}
    elif op == 'remove':
        song = None
        if not safe_url(track):
            return 400, {'ok': False, 'error': 'Unknown track.'}
    else:
        return 400, {'ok': False, 'error': 'Unknown request.'}
    with LYRICS_WRITE:
        for _ in range(3):
            if not lyrics_load(force=True):
                return 502, {'ok': False, 'error': "Couldn't read the current lyrics from GitHub. Try again."}
            with LYRICS_LOCK:
                songs = dict(LYRICS['map'])
                sha = LYRICS['sha']
            if song is None:
                if track not in songs:
                    return 200, {'ok': True, 'lyrics': songs}
                songs.pop(track)
                message = 'vault lyrics: remove %s' % (tidy(msg.get('title'), 60) or track.rsplit('/', 1)[-1])
            else:
                if track not in songs and len(songs) >= LYRICS_TRACKS_MAX:
                    return 400, {'ok': False, 'error': 'Too many songs have lyrics already.'}
                songs[track] = song
                message = 'vault lyrics: %s' % (song['title'] or track.rsplit('/', 1)[-1])
            st, err = lyrics_commit(songs, sha, message)
            if st == 'ok':
                return 200, {'ok': True, 'lyrics': songs}
            if st == 'fail':
                return 502, {'ok': False, 'error': err}
        return 409, {'ok': False, 'error': 'The lyrics kept changing underneath the save. Try again.'}


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

        def add(items, sugg):
            if any(x['url'] == item['url'] for x in items):
                raise ValueError('That address is already on the list.')
            if len(items) >= LINKS_MAX:
                raise ValueError('The list is full (%d links).' % LINKS_MAX)
            # adding what someone suggested answers the suggestion too
            return (items + [item], [x for x in sugg if x['url'] != item['url']],
                    'vault links: add %s' % item['name'])
        return links_mutate(add)

    if op == 'remove':
        lid = str(msg.get('id') or '')

        def remove(items, sugg):
            gone = [x for x in items if x['id'] == lid]
            if not gone:
                return None             # already removed, maybe from another machine
            return [x for x in items if x['id'] != lid], sugg, 'vault links: remove %s' % gone[0]['name']
        return links_mutate(remove)

    if op == 'accept':
        sid = str(msg.get('id') or '')
        # the owner may tidy the name and description on the way in
        name = tidy(msg.get('name'), 60)
        desc = tidy(msg.get('desc'), 140) if 'desc' in msg else None

        def accept(items, sugg):
            hit = [x for x in sugg if x['id'] == sid]
            if not hit:
                raise ValueError('That suggestion isn\'t waiting any more.')
            s = hit[0]
            rest = [x for x in sugg if x['id'] != sid]
            if any(x['url'] == s['url'] for x in items):
                # it went on the list some other way: just clear it
                return items, rest, 'vault links: %s was already listed' % s['name']
            if len(items) >= LINKS_MAX:
                raise ValueError('The list is full (%d links).' % LINKS_MAX)
            item = clean_link({'id': s['id'], 'name': name or s['name'], 'url': s['url'],
                               'desc': s['desc'] if desc is None else desc, 'added': int(time.time())})
            return items + [item], rest, 'vault links: accept %s' % item['name']
        return links_mutate(accept)

    if op == 'deny':
        sid = str(msg.get('id') or '')

        def deny(items, sugg):
            hit = [x for x in sugg if x['id'] == sid]
            if not hit:
                return None             # already answered, maybe from another machine
            return items, [x for x in sugg if x['id'] != sid], 'vault links: deny %s' % hit[0]['name']
        return links_mutate(deny)

    if op == 'deny-all':
        def deny_all(items, sugg):
            if not sugg:
                return None
            return items, [], 'vault links: deny %d suggestion%s' % (len(sugg), '' if len(sugg) == 1 else 's')
        return links_mutate(deny_all)

    return 400, {'ok': False, 'error': 'Unknown request.'}


def suggest_post(ip, raw):
    """Anyone suggesting a link. Returns (http status, reply); the reply never
    carries the list or anyone else's suggestions."""
    try:
        msg = json.loads(raw.decode('utf-8'))
    except Exception:
        return 400, {'ok': False, 'error': 'That request was not JSON.'}
    if not isinstance(msg, dict):
        return 400, {'ok': False, 'error': 'That request was not an object.'}
    if not GITHUB_TOKEN:
        return 503, {'ok': False, 'error': 'Suggestions aren\'t switched on yet.'}
    name, desc, frm = tidy(msg.get('name'), 60), tidy(msg.get('desc'), 140), tidy(msg.get('from'), CHAT_NAME_LEN)
    if chat_filter is not None:
        if name and chat_filter.clean(name)[1]:
            return 400, {'ok': False, 'error': 'Keep the name clean.'}
        desc = chat_filter.clean(desc)[0] if desc else ''
        if frm and chat_filter.clean(frm)[1]:
            frm = ''
    if CHAT_RESERVED.search(frm):
        frm = ''
    now = time.time()
    item = clean_sugg({'name': name, 'url': msg.get('url'), 'desc': desc, 'from': frm, 'added': int(now)})
    if not item:
        return 400, {'ok': False, 'error': 'A link needs a name and an http:// or https:// address.'}

    # rationed before GitHub is touched at all
    with SUGG_LOCK:
        for q in list(SUGG_LOG.values()) + [SUGG_ALL]:
            while q and now - q[0] > 3600:
                q.popleft()
        for k in [k for k, q in SUGG_LOG.items() if not q]:
            del SUGG_LOG[k]
        mine = SUGG_LOG.get(ip) or collections.deque()
        if mine and now - mine[-1] < SUGG_GAP:
            return 429, {'ok': False, 'error': 'Give it a minute before suggesting another.'}
        if len(mine) >= SUGG_PER_HOUR:
            return 429, {'ok': False, 'error': 'That\'s plenty for now. Try again in a while.'}
        if len(SUGG_ALL) >= SUGG_ALL_PER_HOUR:
            return 429, {'ok': False, 'error': 'Lots of suggestions came in just now. Try again later.'}
        mine.append(now)
        SUGG_LOG[ip] = mine
        SUGG_ALL.append(now)

    def add(items, sugg):
        if any(x['url'] == item['url'] for x in items):
            raise ValueError('That one is already on the list.')
        if any(x['url'] == item['url'] for x in sugg):
            raise ValueError('Someone already suggested that one. It\'s waiting for the owner.')
        if len(sugg) >= SUGG_MAX:
            raise ValueError('Lots of suggestions are waiting already. Try again later.')
        return items, sugg + [item], 'vault links: suggested %s' % item['name']
    code, reply = links_mutate(add)
    if code == 200 and reply.get('ok'):
        return 200, {'ok': True}
    # one that did not go through does not use up their allowance
    with SUGG_LOCK:
        for q in (SUGG_LOG.get(ip), SUGG_ALL):
            if q and now in q:
                q.remove(now)
    return code, {'ok': False, 'error': reply.get('error') or 'Couldn\'t send that. Try again.'}


def sugg_notify(n):
    """Tell the owner's open vaults how many suggestions are waiting."""
    owners_send({'t': 'sugg', 'n': n})


def owners_send(obj):
    with CHAT_LOCK:
        owners = [p for p in CHAT['peers'] if p.owner]
    for p in owners:
        p.send(obj)


# ── ideas ─────────────────────────────────────────────────────────
def clean_idea(x):
    """An idea as stored, or None."""
    if not isinstance(x, dict):
        return None
    text = tidy(x.get('text'), IDEA_LEN)
    if len(text) < 3:
        return None
    kind = x.get('kind') if x.get('kind') in IDEA_KINDS else 'other'
    iid = ''.join(ch for ch in str(x.get('id') or '') if ch.isalnum() or ch in '-_')[:24]
    try:
        at = max(0, int(x.get('at') or 0))
    except (TypeError, ValueError):
        at = 0
    return {'id': iid or new_link_id(), 'kind': kind, 'text': text,
            'from': tidy(x.get('from'), CHAT_NAME_LEN), 'at': at}


def ideas_path():
    return '/repos/%s/contents/%s' % (LINKS_REPO, IDEAS_PATH)


def ideas_load(force=False):
    """Refresh the cache from GitHub when stale; False if it could not be read."""
    with IDEAS_LOCK:
        if not force and IDEAS['ok'] and time.time() - IDEAS['at'] < IDEAS_TTL:
            return True
    st, js = gh('GET', ideas_path() + '?ref=' + urllib.parse.quote(LINKS_BRANCH, safe=''))
    if st == 200 and isinstance(js, dict) and js.get('type') == 'file':
        try:
            doc = json.loads(base64.b64decode(js.get('content') or '').decode('utf-8'))
        except Exception:
            log('!! %s on %s is not valid JSON; keeping the cached ideas' % (IDEAS_PATH, LINKS_BRANCH))
            return False
        raw = doc.get('ideas', []) if isinstance(doc, dict) else []
        items = [c for c in (clean_idea(x) for x in (raw if isinstance(raw, list) else [])) if c][:IDEAS_MAX]
        with IDEAS_LOCK:
            IDEAS.update(list=items, sha=js.get('sha'), at=time.time(), ok=True)
        return True
    if st == 404:
        with IDEAS_LOCK:
            IDEAS.update(list=[], sha=None, at=time.time(), ok=True)
        return True
    return False


def ideas_commit(items, sha, message):
    doc = json.dumps({'v': 1, 'ideas': items}, indent=2, ensure_ascii=False) + '\n'
    body = {'message': message[:120], 'branch': LINKS_BRANCH,
            'content': base64.b64encode(doc.encode('utf-8')).decode('ascii')}
    if sha:
        body['sha'] = sha
    for first in (True, False):
        st, js = gh('PUT', ideas_path(), body)
        said = str((js or {}).get('message', '')).lower() if isinstance(js, dict) else ''
        if st in (200, 201):
            with IDEAS_LOCK:
                IDEAS.update(list=items, sha=((js or {}).get('content') or {}).get('sha'), at=time.time(), ok=True)
            return 'ok', ''
        if st in (404, 422) and 'branch' in said and first:
            if make_branch():
                continue
            return 'fail', "Couldn't create the %s branch on GitHub." % LINKS_BRANCH
        if st == 409 or (st == 422 and 'sha' in said):
            return 'conflict', ''
        if st in (401, 403):
            return 'fail', 'GitHub refused the token. It needs Contents: read and write on %s.' % LINKS_REPO
        return 'fail', "Couldn't reach GitHub (%s). Try again." % (st or 'no answer')
    return 'fail', "Couldn't save to GitHub."


def ideas_mutate(change):
    """Apply change(items) -> (new_items, message) | None on the newest list
    and commit it; the owner's open vaults hear the new count."""
    with IDEAS_WRITE:
        for _ in range(3):
            if not ideas_load(force=True):
                return 502, {'ok': False, 'error': "Couldn't read the ideas from GitHub. Try again."}
            with IDEAS_LOCK:
                items = [dict(x) for x in IDEAS['list']]
                sha = IDEAS['sha']
            try:
                result = change(items)
            except ValueError as e:
                return 400, {'ok': False, 'error': str(e)}
            if result is None:
                return 200, {'ok': True, 'ideas': items}
            new_items, message = result
            st, err = ideas_commit(new_items, sha, message)
            if st == 'ok':
                if len(new_items) != len(items):
                    owners_send({'t': 'ideas', 'n': len(new_items)})
                return 200, {'ok': True, 'ideas': new_items}
            if st == 'fail':
                return 502, {'ok': False, 'error': err}
        return 409, {'ok': False, 'error': 'The ideas kept changing underneath the save. Try again.'}


def idea_post(ip, raw):
    """Anyone sending an idea. The reply never carries anyone's ideas."""
    try:
        msg = json.loads(raw.decode('utf-8'))
    except Exception:
        return 400, {'ok': False, 'error': 'That request was not JSON.'}
    if not isinstance(msg, dict):
        return 400, {'ok': False, 'error': 'That request was not an object.'}
    if not GITHUB_TOKEN:
        return 503, {'ok': False, 'error': 'Reports aren\'t switched on yet.'}
    text = tidy(msg.get('text'), IDEA_LEN)
    frm = tidy(msg.get('from'), CHAT_NAME_LEN)
    if len(text) < 3:
        return 400, {'ok': False, 'error': 'Write a little more than that.'}
    if chat_filter is not None:
        text = chat_filter.mask(text)[0]
        if frm and chat_filter.clean(frm)[1]:
            frm = ''
    if CHAT_RESERVED.search(frm):
        frm = ''
    now = time.time()
    item = clean_idea({'text': text, 'kind': msg.get('kind'), 'from': frm, 'at': int(now)})
    if not item:
        return 400, {'ok': False, 'error': 'Write a little more than that.'}

    # rationed before GitHub is touched at all
    with SUGG_LOCK:
        for q in list(IDEA_LOG.values()) + [IDEA_ALL]:
            while q and now - q[0] > 3600:
                q.popleft()
        for k in [k for k, q in IDEA_LOG.items() if not q]:
            del IDEA_LOG[k]
        mine = IDEA_LOG.get(ip) or collections.deque()
        if mine and now - mine[-1] < IDEA_GAP:
            return 429, {'ok': False, 'error': 'Give it a minute before sending another.'}
        if len(mine) >= IDEA_PER_HOUR:
            return 429, {'ok': False, 'error': 'That\'s plenty for now. Try again in a while.'}
        if len(IDEA_ALL) >= IDEA_ALL_PER_HOUR:
            return 429, {'ok': False, 'error': 'Lots of reports came in just now. Try again later.'}
        mine.append(now)
        IDEA_LOG[ip] = mine
        IDEA_ALL.append(now)

    def add(items):
        if any(x['text'].lower() == item['text'].lower() for x in items):
            raise ValueError('That idea is already waiting for the owner.')
        if len(items) >= IDEAS_MAX:
            raise ValueError('Lots of ideas are waiting already. Try again later.')
        return items + [item], 'vault ideas: a %s idea' % item['kind']
    code, reply = ideas_mutate(add)
    if code == 200 and reply.get('ok'):
        return 200, {'ok': True}
    with SUGG_LOCK:
        for q in (IDEA_LOG.get(ip), IDEA_ALL):
            if q and now in q:
                q.remove(now)
    return code, {'ok': False, 'error': reply.get('error') or 'Couldn\'t send that. Try again.'}


def ideas_owner_post(key, raw):
    """The owner marking ideas done: {op: 'done', id} or {op: 'clear'}."""
    if not owner_ok(key):
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
    if op == 'done':
        iid = str(msg.get('id') or '')

        def done(items):
            if not any(x['id'] == iid for x in items):
                return None             # already done, maybe on another machine
            return [x for x in items if x['id'] != iid], 'vault ideas: one done'
        return ideas_mutate(done)
    if op == 'clear':
        def clear(items):
            if not items:
                return None
            return [], 'vault ideas: clear %d' % len(items)
        return ideas_mutate(clear)
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
        self.id = os.urandom(5).hex()   # how others address it; names are not unique
        self.game = None                # {'name', 'url'} of the game it has open
        self.share = False              # whether its browser can share a screen
        self.status_at = 0.0
        self.roster_due = False
        self.rq_log = collections.deque()
        self.rq_last = {}               # target id -> when it was last asked
        self.rtc_log = collections.deque()
        self.owner = False              # said the owner key; told about suggestions

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


def chat_people():
    """Everyone here, each with an id to address them by and what they are
    playing. `names` stays alongside for pages from before this existed."""
    with CHAT_LOCK:
        peers = list(CHAT['peers'])
    people = [{'id': p.id, 'name': p.shown(), 'game': p.game['name'] if p.game else None, 'share': p.share}
              for p in peers]
    people.sort(key=lambda x: (x['name'].lower(), x['id']))
    return people


def chat_roster():
    """Tell everyone who is here."""
    with CHAT_LOCK:
        names = sorted({p.shown() for p in CHAT['peers']}, key=str.lower)
        online = len(CHAT['peers'])
    chat_broadcast({'t': 'roster', 'names': names, 'online': online, 'people': chat_people()})


def chat_find(pid):
    with CHAT_LOCK:
        for p in CHAT['peers']:
            if p.id == pid:
                return p
    return None


def chat_game(raw):
    """A game as a page describes it: a filtered name and, for a web game, its
    address. Anything else -- a data: game, a bad address -- travels as a name."""
    if not isinstance(raw, dict):
        return None
    name = tidy(raw.get('name'), 60)
    if not name or chat_filter.clean(name)[1]:
        return None
    url = str(raw.get('url') or '')
    if not url.startswith(('https://', 'http://')) or len(url) > 400 or any(c.isspace() for c in url):
        url = ''
    return {'name': name, 'url': url}


def chat_status(peer, msg):
    """A page saying what game it has open. The roster goes out at most once a
    second per socket, so opening and closing games fast cannot flood anyone."""
    game = chat_game(msg.get('game'))
    share = msg.get('share') is True
    if game == peer.game and share == peer.share:
        return
    peer.game, peer.share = game, share
    now = time.time()
    if now - peer.status_at >= 1.0:
        peer.status_at = now
        chat_roster()
    elif not peer.roster_due:
        peer.roster_due = True

        def later():
            peer.roster_due = False
            peer.status_at = time.time()
            if peer.alive:
                chat_roster()
        t = threading.Timer(1.0, later)
        t.daemon = True
        t.start()


def chat_request(peer, msg):
    kind = msg.get('kind')
    if kind not in ('watch', 'play'):
        return
    now = time.time()
    if chat_muted(peer.ip, now) > 0:
        peer.send({'t': 'err', 'code': 'muted', 'msg': 'You are muted, so you can\'t send requests right now.'})
        return
    target = chat_find(str(msg.get('to') or ''))
    if target is peer:
        return
    if target is None or not target.alive:
        peer.send({'t': 'err', 'code': 'rq-gone', 'msg': 'They aren\'t online any more.'})
        return
    while peer.rq_log and now - peer.rq_log[0] > 60:
        peer.rq_log.popleft()
    if len(peer.rq_log) >= RQ_PER_MIN or now - peer.rq_last.get(target.id, 0) < RQ_GAP:
        peer.send({'t': 'err', 'code': 'rq-slow', 'msg': 'Give them a moment before asking again.'})
        return
    if kind == 'play':
        game = chat_game(msg.get('game'))
        if not game:
            peer.send({'t': 'err', 'code': 'rq-game', 'msg': 'That game can\'t be sent.'})
            return
    else:
        if not target.game:
            peer.send({'t': 'err', 'code': 'rq-idle', 'msg': target.shown() + ' isn\'t playing anything right now.'})
            return
        if not target.share:
            peer.send({'t': 'err', 'code': 'rq-noshare', 'msg': target.shown() + '\'s device can\'t share its screen.'})
            return
        game = target.game
    peer.rq_log.append(now)
    peer.rq_last[target.id] = now
    rid = os.urandom(6).hex()
    with CHAT_LOCK:
        for k in [k for k, r in RQ.items() if now - r['at'] > RQ_TTL]:
            del RQ[k]
        RQ[rid] = {'frm': peer, 'to': target, 'kind': kind, 'game': game, 'at': now}
    target.send({'t': 'rq', 'rid': rid, 'kind': kind, 'game': game,
                 'from': {'id': peer.id, 'name': peer.shown()}})
    peer.send({'t': 'rq-sent', 'rid': rid, 'kind': kind, 'game': game,
               'to': {'id': target.id, 'name': target.shown()}})


def chat_reply(peer, msg):
    """The person asked, answering. Only they can; a yes to a watch opens a
    session the two browsers may then pass setup messages through."""
    rid = str(msg.get('rid') or '')
    ok = msg.get('ok') is True
    why = msg.get('why') if msg.get('why') in RQ_WHY else None
    now = time.time()
    with CHAT_LOCK:
        r = RQ.get(rid)
        if not r or r['to'] is not peer:
            return
        del RQ[rid]
        frm = r['frm']
        late = now - r['at'] > RQ_TTL
        gone = not frm.alive or frm not in CHAT['peers']
        if ok and r['kind'] == 'watch' and not late and not gone:
            if sum(1 for x in SESS.values() if x['sharer'] is peer) >= WATCH_MAX:
                ok, why = False, 'busy'
            else:
                SESS[rid] = {'sharer': peer, 'viewer': frm}
    if late or gone:
        peer.send({'t': 'rq-gone', 'rid': rid})
        return
    reply = {'t': 'rq-reply', 'rid': rid, 'kind': r['kind'], 'ok': ok, 'game': r['game'],
             'by': {'id': peer.id, 'name': peer.shown()}}
    if why:
        reply['why'] = why
    frm.send(reply)
    if r['kind'] == 'watch':
        if ok:
            peer.send({'t': 'watch-go', 'sid': rid, 'viewer': {'id': frm.id, 'name': frm.shown()}})
        elif why == 'busy':
            peer.send({'t': 'watch-no', 'sid': rid, 'why': 'busy'})


def chat_cancel(peer, msg):
    """The asker taking a request back, or giving up waiting."""
    rid = str(msg.get('rid') or '')
    with CHAT_LOCK:
        r = RQ.get(rid)
        if not r or r['frm'] is not peer:
            return
        del RQ[rid]
    r['to'].send({'t': 'rq-cancel', 'rid': rid})


def rtc_clean(data):
    """Only the two shapes call setup needs: a description or a candidate."""
    if not isinstance(data, dict):
        return None
    d = data.get('sdp')
    if isinstance(d, dict) and d.get('type') in ('offer', 'answer') and isinstance(d.get('sdp'), str) \
            and len(d['sdp']) <= 14000:
        return {'sdp': {'type': d['type'], 'sdp': d['sdp']}}
    if 'c' in data:
        c = data['c']
        if c is None:
            return {'c': None}
        if isinstance(c, dict) and isinstance(c.get('candidate'), str) and len(c['candidate']) <= 1000:
            mid = c.get('sdpMid')
            line = c.get('sdpMLineIndex')
            return {'c': {'candidate': c['candidate'],
                          'sdpMid': mid if isinstance(mid, str) and len(mid) <= 64 else None,
                          'sdpMLineIndex': line if isinstance(line, int) and 0 <= line < 64 else None}}
    return None


def sess_other(sid, peer):
    with CHAT_LOCK:
        x = SESS.get(sid)
    if not x:
        return None
    if x['sharer'] is peer:
        return x['viewer']
    if x['viewer'] is peer:
        return x['sharer']
    return None


def chat_rtc(peer, msg):
    sid = str(msg.get('sid') or '')
    data = rtc_clean(msg.get('data'))
    if data is None:
        return
    now = time.time()
    while peer.rtc_log and now - peer.rtc_log[0] > 60:
        peer.rtc_log.popleft()
    if len(peer.rtc_log) >= RTC_PER_MIN:
        return
    peer.rtc_log.append(now)
    other = sess_other(sid, peer)
    if other is not None:
        other.send({'t': 'rtc', 'sid': sid, 'data': data})


def chat_end(peer, msg):
    sid = str(msg.get('sid') or '')
    other = sess_other(sid, peer)
    if other is None:
        return
    with CHAT_LOCK:
        SESS.pop(sid, None)
    other.send({'t': 'rtc-end', 'sid': sid})


def chat_left(peer):
    """A socket closed: end its watch sessions and settle its requests."""
    with CHAT_LOCK:
        ended = [(sid, x) for sid, x in SESS.items() if x['sharer'] is peer or x['viewer'] is peer]
        for sid, _ in ended:
            del SESS[sid]
        open_rq = [(rid, r) for rid, r in RQ.items() if r['frm'] is peer or r['to'] is peer]
        for rid, _ in open_rq:
            del RQ[rid]
    for sid, x in ended:
        (x['viewer'] if x['sharer'] is peer else x['sharer']).send({'t': 'rtc-end', 'sid': sid})
    for rid, r in open_rq:
        if r['to'] is peer:
            r['frm'].send({'t': 'rq-reply', 'rid': rid, 'kind': r['kind'], 'ok': False, 'why': 'left',
                           'game': r['game'], 'by': {'id': peer.id, 'name': peer.shown()}})
        else:
            r['to'].send({'t': 'rq-cancel', 'rid': rid})


def chat_rename(peer, msg):
    """A page saying what it is called -- on connecting, and whenever the
    vault's name changes. Filtered like a message; answered with the name
    actually shown, which may be a guest name."""
    now = time.time()
    peer.owner = owner_ok(msg.get('key'))
    if peer.name is not None and now - peer.named_at < CHAT_RENAME_GAP:
        peer.send({'t': 'you', 'name': peer.shown(), 'id': peer.id})
        return
    wanted = tidy(msg.get('name'), CHAT_NAME_LEN)
    name = chat_name(wanted, peer, peer.owner)
    changed = name != peer.shown() or peer.name is None
    peer.name, peer.named_at = name, now
    peer.send({'t': 'you', 'name': name, 'asked': wanted, 'id': peer.id})
    if changed:
        chat_roster()


def chat_muted(ip, now):
    """Seconds this address stays muted for; 0 when it is not."""
    with CHAT_LOCK:
        m = CHAT['muted'].get(ip)
    return max(0.0, m['until'] - now) if m else 0.0


def chat_mute_rows(now):
    """The mutes still running, newest first, for the owner's list. Addresses
    stay on the server; the owner sees a name, the line, and an id."""
    with CHAT_LOCK:
        CHAT['muted'] = {ip: m for ip, m in CHAT['muted'].items() if m['until'] > now}
        rows = sorted(CHAT['muted'].values(), key=lambda m: -m['until'])
    return [{'id': m['id'], 'name': m['name'], 'text': m['text'],
             'mins': max(1, int(-(-(m['until'] - now) // 60)))} for m in rows]


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
    left = chat_muted(peer.ip, now)
    if left > 0:
        mins = max(1, int(-(-left // 60)))
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
        # RONIN ALPHA: the page says its theme is Decayed Winter. Only this
        # one title is accepted, so nobody can name themselves anything else.
        if msg.get('title') == 'ronin':
            m['title'] = 'ronin'
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
    peer.owner = True
    op, mid = msg.get('op'), msg.get('id')
    now = time.time()
    extra = {}
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
                    m, ip = hit[0]
                    was = CHAT['muted'].get(ip)
                    # muting again keeps the id, so a list already on screen still works
                    CHAT['muted'][ip] = {'until': now + CHAT_MUTE_SECS, 'name': m['name'], 'text': m['text'][:80],
                                         'id': was['id'] if was else os.urandom(4).hex()}
        if hit:
            chat_broadcast({'t': 'del', 'id': mid})
    elif op == 'muted':
        peer.send({'t': 'muted', 'rows': chat_mute_rows(now)})
        return
    elif op == 'unmute':
        with CHAT_LOCK:
            hit = [(ip, m) for ip, m in CHAT['muted'].items() if m['id'] == mid]
            if hit:
                del CHAT['muted'][hit[0][0]]
                freed = [p for p in CHAT['peers'] if p.ip == hit[0][0]]
            else:
                freed = []
        for p in freed:
            p.send({'t': 'unmuted'})
        if hit:
            extra['name'] = hit[0][1]['name']
    else:
        return
    peer.send(dict({'t': 'mod-ok', 'op': op}, **extra))
    if op in ('mute', 'unmute'):
        peer.send({'t': 'muted', 'rows': chat_mute_rows(now)})


class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    # Set while serving a file off disk, so the cache header lands on the game
    # and not on the websocket handshake or the health endpoint.
    revalidate = False

    def translate_path(self, path):
        # A place that is switched off shows its closed page instead (see CLOSED),
        # or with 'fake' on, the decoy site.
        page = shut_page(path)
        if page:
            return SimpleHTTPRequestHandler.translate_path(self, '/' + page)
        # The front door picks between the two sites; the game lives one step in.
        if path in ('/', '/index.html'):
            path = '/' + HOME
        elif path == '/neon-siege':
            path = '/' + GAME
        # Bee's Vault rides along as its own page. It is nothing to do with the
        # game and shares none of its state; it is here because this is the
        # host that is already wired to the repo.
        elif path in ('/vault', '/vault/'):
            path = '/' + VAULT
        # Other Projects, a page of their own off the front door
        elif path in ('/projects', '/projects/'):
            path = '/' + PROJECTS
        elif path in ('/rotfall', '/rotfall/'):
            path = '/' + ROTFALL
        elif path in ('/rotfall-2', '/rotfall-2/'):
            path = '/' + ROTFALL2
        elif path in ('/neon-siege-1', '/neon-siege-1/'):
            path = '/' + NEONSIEGE1
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
            if 'neon-siege' in closed_places():
                return self.send_json(503, {'ok': False, 'error': 'NEON SIEGE 2 is closed for a moment.'})
            return self.websocket()
        if route == '/chat':
            if 'vault' in closed_places():
                return self.send_json(503, {'ok': False, 'error': "Bee's Vault is closed for a moment."})
            return self.chat_socket()
        if route == '/api/popular':
            # the vault's Popular tab: the most played games, freshest plays counting most
            return self.send_json(200, {'popular': popular_list(), 'ready': PLAYS['loaded']})
        if route == '/api/closed':
            # which doors the front page should grey out; nothing to say while faking
            shut = closed_places()
            if 'fake' in shut:
                return self.send_error(404)
            return self.send_json(200, {'closed': sorted(shut)})
        if route == '/neon-siege/':
            # the game fetches its voice lines by relative URL, and under a
            # trailing slash those would resolve to /neon-siege/<file> and 404
            return self.redirect('/neon-siege' + self.path[len(route):])
        if route == '/api/ideas':
            # the owner's list; nobody else is shown anyone's ideas
            if not owner_ok(self.headers.get('X-Dev-Key') or ''):
                return self.send_json(403, {'ok': False, 'owner': False, 'error': 'That owner key was refused.'})
            if not ideas_load():
                with IDEAS_LOCK:
                    ok = IDEAS['ok']
                if not ok:
                    return self.send_json(502, {'ok': False, 'owner': True, 'error': "Couldn't read the ideas from GitHub."})
            with IDEAS_LOCK:
                items = list(IDEAS['list'])
            return self.send_json(200, {'ok': True, 'owner': True, 'ideas': items})
        if route == '/api/lyrics':
            fresh = lyrics_load()
            with LYRICS_LOCK:
                ok, songs = LYRICS['ok'], dict(LYRICS['map'])
            if not fresh and not ok:
                return self.send_json(502, {'lyrics': {}, 'error': "Couldn't read the lyrics from GitHub."})
            return self.send_json(200, {'lyrics': songs, 'writable': bool(DEV_KEY and GITHUB_TOKEN)})
        if route == '/api/links':
            # a failed refresh with an older list in hand serves the older list;
            # with nothing in hand it says so, rather than claiming there are none
            fresh = links_load()
            with LINKS_LOCK:
                ok, items, sugg = LINKS['ok'], list(LINKS['list']), list(LINKS['sugg'])
            if not fresh and not ok:
                return self.send_json(502, {'links': [], 'error': "Couldn't read the links from GitHub."})
            reply = {'links': items, 'writable': bool(DEV_KEY and GITHUB_TOKEN)}
            # the waiting suggestions go only to a request with the owner key
            key = self.headers.get('X-Dev-Key')
            if key is not None:
                reply['owner'] = owner_ok(key)
                if reply['owner']:
                    reply['suggested'] = sugg
            return self.send_json(200, reply)
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

    def redirect(self, where):
        self.send_response(301)
        self.send_header('Location', where)
        self.send_header('Content-Length', '0')
        self.end_headers()

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
        if self.path.split('?')[0] in ('/api/links', '/api/lyrics', '/api/suggest', '/api/idea', '/api/ideas', '/api/play'):
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
        route = self.path.split('?')[0]
        if route == '/api/play':
            try:
                n = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                n = -1
            if n <= 0 or n > PLAYS_BODY_MAX:
                self.close_connection = True
                return self.send_json(400, {'ok': False})
            code, reply = play_post(self.client_ip(), self.rfile.read(n))
            return self.send_json(code, reply)
        if route not in ('/api/links', '/api/lyrics', '/api/suggest', '/api/idea', '/api/ideas'):
            self.close_connection = True
            return self.send_json(404, {'ok': False, 'error': 'Not found.'})
        cap = {'/api/lyrics': LYRICS_BODY_MAX, '/api/suggest': SUGG_BODY_MAX,
               '/api/idea': IDEAS_BODY_MAX, '/api/ideas': IDEAS_BODY_MAX}.get(route, LINKS_BODY_MAX)
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if n <= 0 or n > cap:
            # the body was not read, so this connection cannot be reused
            self.close_connection = True
            return self.send_json(413 if n > cap else 400,
                                  {'ok': False, 'error': 'Bad request size.'})
        if route == '/api/idea':
            code, reply = idea_post(self.client_ip(), self.rfile.read(n))
            return self.send_json(code, reply)
        if route == '/api/ideas':
            code, reply = ideas_owner_post(self.headers.get('X-Dev-Key') or '', self.rfile.read(n))
            return self.send_json(code, reply)
        if route == '/api/suggest':
            code, reply = suggest_post(self.client_ip(), self.rfile.read(n))
            return self.send_json(code, reply)
        handler = lyrics_post if route == '/api/lyrics' else links_post
        code, reply = handler(self.headers.get('X-Dev-Key') or '', self.rfile.read(n))
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
        peer.send({'t': 'hello', 'history': history, 'online': online, 'names': names, 'id': peer.id})
        chat_roster()
        try:
            self.chat_pump(peer)
        except Exception:
            pass
        finally:
            peer.alive = False
            with CHAT_LOCK:
                CHAT['peers'].discard(peer)
            chat_left(peer)
            chat_roster()

    def chat_pump(self, peer):
        while True:
            frame = ws_read(self.rfile)
            if frame is None:
                return
            opcode, payload = frame
            if opcode == 0x8 or len(payload) > CHAT_RTC_FRAME_MAX:
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
            if len(payload) > CHAT_FRAME_MAX and t != 'rtc':
                return
            if t == 'say':
                chat_say(peer, msg)
            elif t in ('hi', 'name'):
                chat_rename(peer, msg)
            elif t == 'mod':
                chat_mod(peer, msg)
            elif t == 'ping':
                peer.send({'t': 'pong'})
            elif t == 'status':
                chat_status(peer, msg)
            elif t == 'rq':
                chat_request(peer, msg)
            elif t == 'rq-reply':
                chat_reply(peer, msg)
            elif t == 'rq-cancel':
                chat_cancel(peer, msg)
            elif t == 'rtc':
                chat_rtc(peer, msg)
            elif t == 'rtc-end':
                chat_end(peer, msg)

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
    threading.Thread(target=plays_loop, daemon=True).start()
    if not os.environ.get('RENDER'):
        log('  you:        http://localhost:%d' % args.port)
        log('  same wifi:  http://%s:%d' % (lan_ip(), args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log('stopped')


if __name__ == '__main__':
    main()
