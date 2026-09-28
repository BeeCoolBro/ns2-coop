# -*- coding: utf-8 -*-
"""The chat's word filter. Heavy on purpose.

Runs on the server, never in the page: a filter in the page is a suggestion
anyone can delete in devtools. Everything a client sends is filtered here
before anyone else sees it.

What it looks through, before matching:
  * letters from other alphabets that look like latin ones (Cyrillic "а",
    Greek "ο"), accents, full-width text, invisible characters
  * leet: 0 1 3 4 5 7 8 9 @ $ ! | stand in for letters
  * letters repeated to stretch a word out (f-u-u-u-u-c-k)
  * punctuation dropped between letters (f.u.c.k, s-h-i-t)
  * a letter swapped for * or # (f*ck, sh#t)
  * a word spelled out a letter at a time (f u c k)

And what it deliberately leaves alone: the classic false positives. "class",
"assassin", "cockpit", "grape", "therapist", "Scunthorpe", "shiitake",
"cucumber", "title", "analysis", "raccoon", "spice", "Essex", "hello", "shell",
"this hit", "wash it". Words that only become rude with the right ending are
matched as whole words with a listed set of endings; words that are rude
wherever they appear are matched anywhere, with a short list of exceptions.

Matches are masked with asterisks of the same length. Links and email
addresses are removed outright.
"""
import re
import unicodedata

__all__ = ['clean', 'mask', 'is_clean']

# ── seeing through disguises ─────────────────────────────────────────────
INVISIBLE = set('­͏؜ᅟᅠ឴឵᠎​‌‍‎‏'
                '‪‫‬‭‮⁠⁡⁢⁣⁤⁦⁧⁨'
                '⁩⁪⁫⁬⁭⁮⁯ㅤ﻿ﾠ')

# letters from other scripts that pass for latin ones
CONFUSABLE = {
    'а': 'a', 'в': 'b', 'е': 'e', 'ё': 'e', 'к': 'k', 'м': 'm', 'н': 'h', 'о': 'o', 'р': 'p',
    'с': 'c', 'т': 't', 'у': 'y', 'х': 'x', 'ѕ': 's', 'і': 'i', 'ї': 'i', 'ј': 'j', 'ԁ': 'd',
    'ɡ': 'g', 'һ': 'h', 'ӏ': 'l', 'ո': 'n', 'ս': 'u', 'ց': 'g', 'υ': 'u', 'α': 'a', 'β': 'b',
    'ε': 'e', 'η': 'n', 'ι': 'i', 'κ': 'k', 'ν': 'v', 'ο': 'o', 'ρ': 'p', 'τ': 't', 'χ': 'x',
    'ω': 'w', 'ƒ': 'f', 'ß': 's', 'æ': 'a', 'ø': 'o', 'ł': 'l', 'đ': 'd', 'ħ': 'h', 'ı': 'i',
}
LEET = {'0': 'o', '1': 'i', '2': 'z', '3': 'e', '4': 'a', '5': 's', '6': 'g', '7': 't',
        '8': 'b', '9': 'g', '@': 'a', '$': 's', '!': 'i', '|': 'i', '+': 't', '€': 'e',
        '£': 'l', '¢': 'c', '§': 's'}
WILD = '?'                       # what * and # become: a stand-in for any one letter
LETTERS = 'abcdefghijklmnopqrstuvwxyz'

# a letter in a pattern also accepts the letters people swap in for it
ALSO = {'s': 'sz', 'l': 'li', 'u': 'uv', 'c': 'ck', 'g': 'gq', 'i': 'iy'}
SEP = r'[^a-z?\s]{0,3}'          # up to three punctuation marks between letters


def normalize(text):
    """(normalised text, index of each normalised character in the original)."""
    out, idx = [], []
    for i, ch in enumerate(text):
        if ch in INVISIBLE:
            continue
        d = unicodedata.normalize('NFKD', ch)
        base = ''.join(c for c in d if not unicodedata.combining(c)) or ch
        c = base.casefold()[:1] or ' '
        c = CONFUSABLE.get(c, c)
        c = LEET.get(c, c)
        if c in '*#':
            c = WILD
        out.append(c)
        idx.append(i)
    # A run of one character longer than two becomes two, the second standing
    # for the rest of the run so a mask still covers all of it. "fuuuuuck"
    # still reads as fuuck -- and a line of 240 asterisks can no longer hand
    # every pattern an astronomical number of ways to match. That line hung
    # the filter for over eight seconds before this.
    run_out, run_idx = [], []
    for k, c in enumerate(out):
        if len(run_out) >= 2 and run_out[-1] == c and run_out[-2] == c:
            run_idx[-1] = idx[k]
            continue
        run_out.append(c)
        run_idx.append(idx[k])
    return ''.join(run_out), run_idx


def letters(word):
    """A word as a pattern: each letter may be doubled (longer runs were
    already squeezed to two), swapped for its usual stand-ins or a wildcard,
    and followed by punctuation. Bounded repeats keep every pattern linear."""
    parts = []
    for ch in word:
        cls = ALSO.get(ch, ch)
        parts.append('[%s?]{1,2}' % cls)
    return SEP.join(parts)


# ── what is filtered ─────────────────────────────────────────────────────
# Rude wherever they appear, inside other words included (motherf..., bulls...).
ANYWHERE = [
    'fuck', 'fuk', 'fuq', 'fck', 'fcuk', 'phuck', 'phuk', 'fawk', 'motherf',
    'shit', 'shyt', 'cunt', 'nigg', 'niga', 'nigr', 'bitch', 'biatch', 'biotch', 'beotch',
    'whore', 'slut', 'twat', 'wank', 'dildo', 'porn', 'jizz', 'bastard', 'fagg', 'fagot',
    'penis', 'vagina', 'orgasm', 'masturbat', 'blowjob', 'handjob', 'rimjob', 'hentai',
    'retard', 'pedophil', 'paedophil', 'cocksuck', 'onlyfans', 'jackoff', 'jerkoff',
    'clitoris', 'kkk', 'douchebag',
]
# ...except inside these words
ANYWHERE_OK = {
    'shiitake', 'shiitakes', 'shitake', 'scunthorpe', 'retardant', 'retardants', 'retardation',
    'penistone', 'cockatoo', 'matsushita', 'snigger', 'sniggers', 'sniggered', 'sniggering',
    'niggle', 'niggles', 'niggled', 'niggling',
}

# Rude only as whole words, with the endings listed. "ass" is rude, "class" is
# not; "hell" is filtered, "hello" and "shell" are not.
WHOLE = {
    'ass': ['', 'es', 'hole', 'holes', 'hat', 'hats', 'wipe', 'wipes', 'face', 'clown', 'lick',
            'licker', 'kisser', 'ed'],
    'dumbass': ['', 'es'], 'jackass': ['', 'es'], 'badass': ['', 'es'], 'smartass': ['', 'es'],
    'fatass': ['', 'es'], 'lardass': ['', 'es'], 'kickass': [''], 'arse': ['', 's', 'hole', 'holes'],
    'damn': ['', 's', 'ed', 'it', 'n'], 'dammit': [''], 'goddamn': ['', 'it', 'ed'], 'goddam': [''],
    'hell': ['', 'hole'], 'crap': ['', 's', 'py', 'pier', 'ped', 'ping'],
    'piss': ['', 'ed', 'es', 'ing', 'er', 'y', 'off'],
    'dick': ['', 's', 'head', 'heads', 'hole', 'ish', 'wad', 'weed'],
    'cock': ['', 's', 'head', 'heads'], 'pussy': ['', 'cat'], 'pussies': [''],
    'tit': ['', 's', 'ty', 'ties'], 'boob': ['', 's', 'ies', 'y'],
    'cum': ['', 's', 'shot', 'ming', 'med'], 'sex': ['', 'y', 't', 'ts', 'ting', 'ual', 'ually'],
    'anal': [''], 'anus': [''], 'horny': [''], 'nude': ['', 's'], 'nudes': [''],
    'hoe': ['', 's'], 'thot': ['', 's'], 'milf': ['', 's'], 'dilf': ['', 's'], 'xxx': [''],
    'clit': ['', 's'], 'boner': ['', 's'], 'shat': [''], 'sht': [''], 'prick': ['', 's'],
    'douche': ['', 's'], 'skank': ['', 's', 'y'], 'bollock': ['', 's'], 'bugger': ['', 's', 'ed'],
    'tosser': ['', 's'], 'bellend': ['', 's'], 'wtf': [''], 'stfu': [''], 'gtfo': [''],
    'omfg': [''], 'lmfao': [''], 'ffs': [''], 'fml': [''], 'mofo': ['', 's'], 'kys': [''],
    'kms': [''], 'rape': ['', 's', 'd', 'r', 'rs'], 'raping': [''], 'rapist': ['', 's'],
    'pedo': ['', 's', 'phile', 'philes'], 'nazi': ['', 's'], 'tard': ['', 's'],
    # slurs
    'coon': ['', 's'], 'chink': ['', 's'], 'gook': ['', 's'], 'spic': ['', 's', 'k', 'ks'],
    'kike': ['', 's'], 'wetback': ['', 's'], 'beaner': ['', 's'], 'towelhead': ['', 's'],
    'raghead': ['', 's'], 'tranny': [''], 'trannies': [''], 'dyke': ['', 's'], 'fag': ['', 's'],
    'homo': ['', 's'], 'paki': ['', 's'], 'jap': ['', 's'], 'negro': ['', 'es', 's'],
    'honky': [''], 'gypo': ['', 's'],
}
# Phrases, matched with anything between the words.
PHRASES = [('kill', 'yourself'), ('kill', 'urself'), ('kill', 'ur', 'self'), ('kill', 'yoself'),
           ('go', 'die'), ('neck', 'yourself'), ('suck', 'my'), ('blow', 'me')]


def _compile():
    pats = []
    for w in ANYWHERE:
        pats.append(('any', re.compile(letters(w))))
    for w, ends in WHOLE.items():
        alts = '|'.join(re.escape(e) for e in sorted(set(ends), key=len, reverse=True) if e)
        tail = '(?:%s)?' % alts if alts else ''
        pats.append(('whole', re.compile(r'(?<![a-z?])' + letters(w) + tail + r'(?![a-z?])')))
    for words in PHRASES:
        body = r'[^a-z?]+'.join(letters(w) for w in words)
        pats.append(('whole', re.compile(r'(?<![a-z?])' + body + r'(?![a-z?])')))
    return pats


PATTERNS = _compile()

URL = re.compile(
    r'(?i)(?:https?://|www\.)\S+'
    r'|\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|gg|me|co|xyz|app|dev|tv|ly|link|'
    r'site|online|info|us|uk|ru|cc|to|be|gl|shop|store|live|club|fun|top|lol|gay|sex|porn|xxx)\b(?:/\S*)?')
EMAIL = re.compile(r'(?i)\b[\w.+-]+@[\w-]+\.[\w.-]+\b')


def _token_at(norm, a, b):
    """The whole run of letters a match sits inside."""
    while a > 0 and norm[a - 1] in LETTERS + WILD:
        a -= 1
    while b < len(norm) and norm[b] in LETTERS + WILD:
        b += 1
    return norm[a:b]


def _spelled_out(norm):
    """Words typed one letter at a time -- "f u c k" -- joined back together,
    with each letter's place in the normalised text."""
    runs = []
    for m in re.finditer(r'(?<![a-z?])[a-z?](?:[^a-z?]{1,3}[a-z?](?![a-z?])){2,}', norm):
        pos = [m.start() + i for i, c in enumerate(m.group(0)) if c in LETTERS + WILD]
        runs.append((''.join(norm[p] for p in pos), pos))
    return runs


def _spans(text):
    """Character ranges of the original text to mask."""
    norm, idx = normalize(text)
    hits = []

    def consider(kind, s, e, view, where):
        segment = view[s:e]
        if sum(1 for c in segment if c in LETTERS) < 2:      # "***" alone is not a word
            return
        if text[where(s):where(e - 1) + 1].isdigit():         # a score of 455 is a score
            return
        if kind == 'any' and _token_at(view, s, e) in ANYWHERE_OK:
            return
        hits.append((where(s), where(e - 1)))

    for kind, pat in PATTERNS:
        for m in pat.finditer(norm):
            consider(kind, m.start(), m.end(), norm, lambda k: idx[k])
    for joined, pos in _spelled_out(norm):
        for kind, pat in PATTERNS:
            for m in pat.finditer(joined):
                consider(kind, m.start(), m.end(), joined, lambda k, pos=pos: idx[pos[k]])
    return hits


def clean(text):
    """(text as others will see it, whether anything was changed)."""
    if not text:
        return '', False
    out = EMAIL.sub('[removed]', text)          # before links, or the domain goes first
    out = URL.sub('[link removed]', out)
    changed = out != text
    spans = _spans(out)
    if spans:
        chars = list(out)
        for a, b in spans:
            for k in range(a, b + 1):
                if not chars[k].isspace():
                    chars[k] = '*'
        out = ''.join(chars)
        changed = True
    return out, changed


def mask(text):
    """(text, changed) with swearing masked and email addresses removed, but
    links left alone -- for text only the owner reads, like ideas, where
    "add 1v1.lol" has to survive."""
    if not text:
        return '', False
    out = EMAIL.sub('[email removed]', text)
    changed = out != text
    spans = _spans(out)
    if spans:
        chars = list(out)
        for a, b in spans:
            for k in range(a, b + 1):
                if not chars[k].isspace():
                    chars[k] = '*'
        out = ''.join(chars)
        changed = True
    return out, changed


def is_clean(text):
    return not clean(text)[1]
