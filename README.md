# NEON SIEGE 2 — co-op

Deploy to Render (free), send your friend the URL, both press **PLAY**. You get
paired automatically and land in the same match. No codes, no port forwarding.

---

## Deploy

1. Push this repo to GitHub.
2. Render: **New → Blueprint**, pick the repo. `render.yaml` does the rest.
   (By hand: Runtime **Python**, Build Command *blank*, Start Command
   `python server.py`, Plan **Free**.)
3. Open the URL it gives you, e.g. `https://ns2-coop.onrender.com`. That is
   the **BeeSide Studio's** front page; **NEON SIEGE 2** on it opens the game at
   `/neon-siege` (and **Bee's Vault** opens `/vault`).
4. Both players open the game → **👥 CO-OP** → **PLAY**. First one waits, second one
   pairs instantly. Whoever is made host then presses **CHOOSE SECTOR** and
   deploys; the other drops in automatically.

No dependencies. `requirements.txt` is empty on purpose; it only tells Render
this is a Python service.

`/healthz` and `/stats` return `{ok, waiting, live, paired, matches, chat}` if
you want to see who is queued. The front page reads it too: `chat` is how many
vaults are open (each one sits in the chat room) and `matches` how many games
of NEON SIEGE 2 are going, shown on each door when above zero.

## The front page and the openings

**`/` (index.html):** a honeycomb drawn on a canvas that lights up around the
pointer, with pollen drifting up through it and a ripple where you click. On
the first visit of a session a drop of honey falls into the logo and a ripple
runs out through the hive as the page arrives. Each door tilts towards the
pointer. The vault's door turns its dial and spills out what's inside, and
NEON SIEGE 2's door has a small tower-defense fight running in it. Each door
shows who is in there right now, and a ticker lists what is inside. **1** and
**2** pick a door, and picking one opens it out into the next page.

The front page keeps to its two main doors. **Other Projects** is a page of
its own, **`/projects` (projects.html)**. The button under the doors (or
**3**) opens into it the way the doors open into theirs, and an old
`/#projects` link lands there too. It is the front page's room: the same
honeycomb, doors and way out, with a BeeSide button back (or **Esc**). Its
CSS and script are copied from index.html, so a change to the shared look
belongs in both.

First is **ROTFALL** (`rotfall.html`, served at `/rotfall`), a top-down
survival shooter, in its burnt orange; **1** opens it. Behind it, like NEON
SIEGE 2's door, a small live scene of the game plays: the swarm closes in on
the orange orb, which picks them off. The game's menu has a PROJECTS button
back to Other Projects, shown only when it's played at `/rotfall`. Next to it
is an empty dashed door, "More soon", holding the place for the next one. A
new project gets a door like ROTFALL's in its place, and the "More soon" door
moves after it or goes.

**Bee's Vault** opens with a vault door. Its dial cracks a combination while
the page downloads, then the bolts pull back and the door swings open. It sits
right after the favicon, not in `<body>`: the vault's head holds 1.7 MB of
theme images, and until now the screen stayed blank while they arrived.

**NEON SIEGE 2** opens like an arcade cabinet. The CRT powers on, and a
synthwave sun rises over a rushing grid while "BeeSide Studio's presents"
types out. Then the logo slams in with its colour channels split, and it flies
onto the title screen's own logo.

**ROTFALL** opens in the dark with just its orange orb. The swarm's eyes open
all round and creep in, then the orb fires a shockwave that kills them as it
reaches them, and the name slams down letter by letter right where the menu's
logo is. It fades into the menu with the name already in place. The opening
waits for the page to be visible, and a key that skips it doesn't also reach
the game.

All four play in full once per browser session and short after that. The
game's is always short inside Bee's Vault. A click, tap or key skips, reduced
motion gets a fade, and a CSS-only failsafe hides the vault's, the game's or
ROTFALL's opening if its script never runs. The vault's tour and owner-key
popup wait until the door has opened. The game's opening is in
`neon-siege-2.html` like everything else, so `build-coop.py` carries it into
the co-op build.

## What the free plan means

Checked against Render's docs, not assumed:

- **It sleeps.** A free service spins down after **15 minutes** without traffic
  and takes **about a minute** to wake. The first person in waits out a loading
  page — normal, not broken. Playing keeps it awake.
- **750 instance hours/month**, so one always-on free service fits (~730).
- **WebSockets are supported** with no fixed timeout, though they close when the
  instance is replaced on deploy.
- **Outbound bandwidth counts** against your allowance: roughly 130 MB per
  half-hour match.

If the socket drops while you are *searching*, the client retries with backoff.
If it drops *mid-match*, the match ends with a clear message rather than
silently pairing someone with a stranger halfway through a wave.

## Running locally

```bash
python server.py
```

`http://localhost:8765` (the game is `/neon-siege`), plus a `same wifi:` address for someone on your
network. `PORT` is honoured, which is how Render starts it.

## How the co-op works

Host-authoritative. The host runs the only simulation; the guest sends intents
("place a PULSE here") and draws snapshots at 15/s. The server picks who hosts —
whoever waited longer, since their tab is already warm.

Lockstep was rejected deliberately: `Math.sin`, `Math.pow` and friends are not
bit-identical across JavaScript engines, so two copies on the same seed drift
apart within a wave with no cheap way to notice. One authority, nothing to
desync.

Guest intents run through the *same* `placeTower` / `buyUpgrade` / `fireAbility`
the host's own clicks call, so the rules cannot diverge — the host re-validates
placement, cost and cooldowns, and an illegal request is simply refused.

The server never parses a game message; it pairs two sockets and forwards bytes.

**Bandwidth** at 18 towers / 118 enemies: 4.75 KB per snapshot, **71 KB/s**.
Enemy HP travels as a 0–1000 ratio rather than four absolute numbers, since the
guest only draws it as a bar.

**Rewards go to the host only** — both players claiming one match would
double-pay the vault.

## Performance

Profiled on a wave-34 board (20 fully-upgraded towers, ~140 enemies, ~600
particles) rather than guessed at:

- Frame time is **flat from 1 to 12.6 megapixels**, so the frame is draw-call
  bound, not fill bound. Resolution was the wrong lever.
- Enemies were **5.9 ms of a 16.3 ms frame**; `rgba()` was called from 359 sites,
  rebuilding a CSS colour string and re-parsing the hex every time.

Fixed by memoising colours (alpha quantised to 1/128, invisible on screen),
skipping anything outside the view, and capping particles. Same scene now
renders in **13.7 ms with more enemies on screen**. Under sustained load the
game thins particles first, then bloom, and only touches resolution last —
the order that measurement justified.

A later pass found the real heavyweight: **bloom**. Two traps on the way there.
A per-phase profiler blamed `doBloom` for 59% of the frame, but canvas 2D
commands are queued rather than executed where you call them, and `doBloom`
reads back from the main canvas — so it was absorbing the cost of everything
drawn before it. Then the A/B numbers started contradicting each other, because
three other tabs still had the game open and were competing for the GPU.

With those cleared, the actual problem: `ctx.filter = blur(11px)` applied while
drawing to the main canvas runs the kernel at **destination** resolution, so an
11px blur was convolved over all 1.44MP twice a frame; and the tight and wide
halos were each a separate full-canvas additive blend. The blur now runs on a
quarter-scale buffer with radii scaled to match, and the two halos are composited
while still small so only one full-resolution blend happens per frame.

**Bloom cost: 69.6 ms → 19.5 ms, down 72%** (9 interleaved reps, non-overlapping
ranges). Visually checked rather than assumed — against the original on an
identical frozen frame, mean absolute difference **1.8/255** per channel.

## Sector bosses

Sectors 5-8 each close on a boss built around the shape of that map, not around
a bigger number:

| sector | boss | what it does |
|---|---|---|
| 5 · DATA VORTEX | **NEMESIS** | tallies damage by school (kinetic / arc / chem) and every 5s attunes to whichever is hurting it most, taking 60% less from it. Abilities belong to no school and always land in full. |
| 6 · CROSSFIRE | **GEMINI** | halves itself at 62% and 34% and sends the twin down the other braid. Hull and bounty are both split, so the pool is conserved — the problem is that it is in two places. |
| 7 · THE ABYSS | **TYRANT** | suppression pulse every ~6s knocks every tower within 300px fully offline for 3s. Aimed at the single diagonal, where the whole board is strung along one line. |
| 8 · SINGULARITY | **ARCHITECT** | each phase sheds a SHARD down every lane and it rebuilds 0.5%/s per living shard. |

Sectors 5-7 also meet their own boss at the wave-10 marks, so the trick is not
sprung for the first time on the wave that decides the sector.

Hulls from wave 15 ramp to **1.5x** by wave 35, on top of the existing curve.
It starts at 15 rather than 1 because the opening waves are still paying for
your first board.

## Control has limits

Freeze, stun, knockback and slow used to stack with nothing pushing back, so a
control board stopped a wave outright rather than slowing it. Three caps now
apply, and the per-tower numbers were cut to match:

- **Hard CC** holds for up to 60 ticks and leaves the unit immune for 220 —
  about 21% uptime, down from 50%.
- **Knockback** loses 34% of its push each time it lands on the same unit, and
  the resistance bleeds off over roughly six seconds.
- **Slows** cannot take anything below a third of its speed, however many are
  stacked on it.

Measured with one immortal dummy walking a lane past eight fully-upgraded
towers of a single type for 60 seconds — share of that minute spent unable to
move, and how much of the lane it covered:

| board | held still | lane covered |
|---|---|---|
| cryo | 40% → 18.3% | 14.1% → 29.0% |
| seismic | 33.8% → 15.6% | 0.1% → 10.4% |
| tesla | 20% → 5.6% | 48.9% → 57.5% |
| mire | min speed 8% → 34% | 7.2% → 22.3% |
| scatter | — | 4.2% → 59.1% |

Seismic was the worst of them: the dummy covered **0.1% of the lane in a full
minute**. Tower damage was left alone, so the upgrades are still worth buying.

GEMINI's halves also step up a speed stage on each split — 0.60, 0.87, 1.23.

## Economy

Two dials, both near the top of the script:

- `UPGRADE_PRICE` (1.5) multiplies every upgrade. One multiplier rather than a
  hundred edited prices, so the ladder keeps its shape -- a full path on a rail
  runs 7095 instead of 4730. It stacks with the final-wave surcharge.
- `COMBO_MAX` (2) caps the kill-streak bounty multiplier. It used to reach 4x
  off eighteen kills, which on a late wave is most of one spawn group, so it was
  effectively permanent. Over a 200-kill streak the payout falls from 13,720 to
  7,720.

They multiply: upgrades cost half as much again while streak income roughly
halves, so effective upgrade throughput lands near a third of what it was.
Change either line if that reads too harsh.

## Moving a save between machines

A save is two localStorage keys, so it never leaves the browser that made it --
a new machine, a different browser, or a cleared cache all start from zero.
**TRANSFER SAVE** on the main menu packs the whole thing (progress, stars, best
scores, endless bests, flux, owned towers, loadout order, abilities) into one
~640-character code to copy, and the same panel takes a pasted code back.

The code is `NS2-<checksum>-<base64>`. The checksum is there because a
half-copied code is the obvious failure mode: without it a truncated paste
decodes into a partial save and quietly wrecks an armoury. Empty, non-save,
truncated and single-character-corrupted pastes are each refused by name and
leave the existing save untouched.

A code that passes the checksum still cannot inject anything -- the import runs
back through `loadMeta()`, which filters towers and abilities down to ones that
exist and clamps the rest. Fed `flux:-999`, a fake tower, a fake ability and an
out-of-range sector with `stars:9`, it returns 0 flux, real towers only, starter
abilities and `stars:2`.

`navigator.clipboard` needs a secure context, which `file://` is not, so COPY
tries `execCommand` first and says so plainly if neither route works.

## Balance

INFERNO was the strongest tower in the game for a reason invisible in its stat
block: cone towers never reach the cooldown path, so its `cd:3` does nothing and
it applied damage **every frame -- 60x a second -- to every enemy in the arc**.
Fully upgraded down PLASMA that was ~635 armour-ignoring dps to each of them at
once. Base damage is down, the upgrade multipliers are trimmed, and the jet now
covers four targets at full strength and thins beyond that to a 34% floor.
Measured damage per second from one maxed tower:

| targets in the cone | before | after |
|---|---|---|
| 1 | 859 | 234 |
| 6 | 3,376 | 921 |
| 16 | 8,454 | 1,136 |

Bosses summon far harder: every 85 ticks instead of 210 (60 for the ARCHITECT),
6-8 adds per burst plus one more per 10 waves, arriving tighter together. The
four bosses that had no escort at all now have one -- LEVIATHAN launches
skimmers, NEMESIS wraiths, GEMINI runners, TYRANT bulwarks. The existing
320-enemy field cap is what keeps this from outrunning the frame rate.

GEMINI's halves also step up a speed stage on each split: 0.60, 0.87, 1.23,
and it carries `ccRes: .5` -- it shrugs off half of any slow or drag. That is
applied per source before they are summed, so stacking three slows on it is
resisted three times rather than once at the end. Under a lone 30% chill it
keeps 85% of its speed instead of 70%; under a heavy chill + tar + mark stack it
holds 49% where anything else is pinned at the 34% floor; and a second in a
gravity well drags it 31px rather than 59px. Its twins share the definition, so
all four bodies resist.

Note that tower knockback was already at 100% resistance for every boss --
`statusHit` checks `!e.boss`, so seismic and scatter have never shoved one. The
only thing still pushing a boss backwards is the GRAVITY WELL ability.

## Screen shake

Scaled at one point rather than at each call site, so a boss death still lands
harder than a stray explosion -- the whole effect sits lower. Replaying the 648
real shake requests from 90s of wave 30 through both settings: peak 18.1px ->
6.5px, average offset 2.16px -> 0.59px, and the screen is now still 60% of the
time instead of 50%. `SHAKE` and `SHAKE_CAP` are one line if you want more.

## Difficulty corrections

Three things compounded into walls and were pulled back:

**Boss hulls now ramp** — 0.30 of listed HP at wave 10 rising to 0.42 by wave
30, instead of a flat 0.42. A flat increase is the wrong shape: it reads as
pressure at wave 30 and is a wall at wave 10, when the board is three starter
towers and the escort piles up behind a boss you cannot kill. Summon bursts
scale the same way (2-3 early, 6-7 late). NEMESIS resists 50% rather than 60%,
and a TYRANT pulse holds towers for 2.3s rather than 3s.

**The ARCHITECT could not be killed at any HP.** A sweep from 0.50 down to 0.30
leaked every time at a flat ~140s, and cutting its hull made the fight *harder* —
it gained +35% speed per phase, so less HP meant it phased sooner and reached
the core faster than the hull saved. The fight length was set by its speed, not
its health. Phase speed is now +12%, base speed is lower, and the shard regen —
which scaled with max HP and so was eating roughly 44% of a full board's output
on a 1.7M hull — is down sevenfold. It now dies at 18 and 14 towers and survives
at ~4% on a thin 11-tower board.

**THE FOUNDRY's opening.** Starting cash scales with lane count, and it is the
only single-lane sector in its range, so it opens on 575 where its two-lane
neighbours get 683-732 — the tightest opening in the game, right as
`UPGRADE_PRICE` made the same money buy a third less board. It was losing ~70 of
its 90 cores on the first boss wave. `OPENING_GRANT` (1.3) tops up the START
only; income rate is untouched, so the squeeze everywhere else is unchanged.

Measured with an auto-player using starter towers and power-ups. It has real
run-to-run variance, so these are "no longer a wall" rather than finely tuned.

## Dev mode

Off unless you set `DEV_KEY` in the server environment. **There is deliberately
no default.** This repo is public and the client is served to everyone, so a
credential written into the code would be a working backdoor into your own
deployment for anyone who reads the source or opens devtools. Unset means every
admin request is refused outright.

Render -> your service -> Environment -> Add Environment Variable -> `DEV_KEY`.
Pick something other than the passphrase below, which is published in the page.

Typing `BEESCANFLY` anywhere opens the panel **on that machine only** -- it
proves nothing to the server, which checks `DEV_KEY` and nothing else. Enter the
key, and you get a list of live games: watch one to see exactly what its player
sees, then pick an enemy type and a count and drop them into the lane. Injected
units go through the ordinary spawner, so they take damage, pay bounty and die
like anything else in the wave.

**Every game is listed, campaign included.** The first cut only ever saw paired
co-op matches, because a match is what pairing creates -- so a solo campaign
run, which is how the game is mostly played, was invisible and the panel sat
permanently empty. Each game now announces itself on its own socket.

A broadcasting game stays silent until somebody actually watches it. The server
reports the spectator count and nothing is streamed while that is zero;
otherwise every campaign player would upload roughly 70 KB/s into the void and
the free tier's bandwidth would be gone for nothing. Pressing WATCH tells the
game to start, and leaving tells it to stop.

Note the reach of this: it means any campaign game on the deployment can be
watched by whoever holds `DEV_KEY`, not just co-op matches.

Spectating reuses the guest path wholesale: a guest already renders a match from
the host's snapshots without simulating anything, which is what a spectator is.
The only difference is a dead transport, so the intents the guest UI tries to
send go nowhere.

One caveat to the "the server never parses a game message" property above: it
now looks at exactly one field, `m.k`, on host frames. A spectator joining
mid-match missed the `start` that set the map up, so that one frame is
remembered per match and replayed on watch.

Verified against a live server with three real websocket clients: a wrong key is
refused and can neither list nor inject; with `DEV_KEY` unset even the correct
key is refused; a spectator joining mid-match gets the cached start and then
live frames while the guest keeps receiving its own; an injection reaches only
the host; and a player leaving closes the match and releases its spectators.

## Bee's Vault and its Links tab

`vault.html` is served at `/vault`. It has nothing to do with the game and
shares none of its state; it is here because this is the host already wired to
the repo.

Its **Links** tab shows the same list on every machine. Anyone can read it; in
dev mode the tab grows an add form and a remove button on each row, and saving
takes `DEV_KEY` -- the same key the co-op dev panel uses. `BEESCANFLY` opens the
vault's dev mode, but it is written in the page source, so it only ever opens
the form. The server decides who can change the list.

**Where the list lives.** Not on this server: Render's free disk is wiped every
time the service sleeps, which is every fifteen idle minutes. It is kept in this
repo as `links.json` on its own branch, `vault-data`, so saving a link never
redeploys the site -- and every add and remove is a commit, so there is a full
history of the list for free.

**To turn saving on**, the server needs a GitHub token as well as `DEV_KEY`:

1. GitHub -> Settings -> Developer settings -> Fine-grained tokens -> Generate.
2. Repository access: **Only select repositories** -> `ns2-coop`.
3. Permissions -> Repository -> **Contents: Read and write**. Nothing else.
4. Render -> your service -> Environment -> Add Environment Variable ->
   `GITHUB_TOKEN`, paste the token. Render restarts the service.

Reading needs no token at all -- the repo is public -- so the list shows for
everyone even before this is done; the add form just says saving isn't on yet.
The server's startup log prints which of the two keys is missing.

The token can write to this repository's contents, which is why it should be
scoped to this one repository and nothing more. The server only ever writes one
path on one branch, fixed in the code; nothing a visitor sends chooses where.

Details worth knowing:

- **Edits made on GitHub are kept.** Every save re-reads the file first and
  builds on it, and if something changes between the read and the write GitHub
  refuses the stale write and the save is retried on top of the new version.
- Reads are cached for five minutes, so a change made directly on GitHub shows
  up within that; changes made through the vault show up at once.
- Only `http://` and `https://` addresses are accepted, checked by the server
  on the way in and by the page again on the way out, and every name is put on
  the page as text, never as markup.
- With no owner key saved, an **Owner Key** box pops up when dev mode is
  turned on, when the vault loads with dev mode already on, and whenever an
  owner action (a save, a moderation, lyrics) needs a key. That action then
  finishes on its own once the key is in. The key is checked with the server
  before it is kept. Skipping it on load holds for that visit.
- The owner key is remembered in that browser after the first successful save,
  with a **Forget it** button beside the form. Worth pressing on a shared PC.

**Suggestions.** Anyone can press **+ Suggest a link** and send a name, an
address and a line about it. It waits in `links.json` under `"suggested"`,
and only a request carrying `DEV_KEY` is shown the waiting ones
(`GET /api/links` with an `X-Dev-Key` header). In dev mode they sit above the
list: fix the name or description, open the address to check it, then
**Accept** (it goes on the list, one commit) or **Deny**; **Deny all** clears
the lot. The Links tab shows a count, and a new one pops up live while the
owner's vault is open. Adding an address directly also clears its suggestion.
`POST /api/suggest` needs no key, so it is rationed before GitHub is touched:
one per address every 45 s, six an hour, forty an hour from everyone, forty
waiting at most. Names go through the chat filter. The repo is public, so a
suggestion is too -- the form says so and asks for nothing personal.

Verified against a local stand-in for the GitHub API: missing branch created on
first save, wrong or empty key refused, `DEV_KEY` unset refuses everything,
`GITHUB_TOKEN` unset reads fine and refuses writes, an edit landing mid-save is
retried and both survive, a restart reads the list back, a repeat remove makes
no empty commit, oversized bodies are refused, and hostile names render inert.

## The game window's dock (vault)

With a mouse, the dock shows only **Close** until you point at it. Then
**Mute**, **Chat** and **Invite** slide out to its left, one after another. It
also opens out for a moment when a game starts, so the buttons are noticed.
While they're folded away, a small dot on the dock means a ping or an invite is
waiting. With a touch screen there's no pointing, so there the buttons stay
out.

## Muting a game (vault)

The game window's dock has a **Mute** button that silences the game while the
vault's music keeps playing. It is remembered for the next game. The games are
framed from another site (realwork.netlify.app, built from the
`BeeCoolBro/seraph` fork), and a page can't reach into another site's frame. So
the vault asks with `postMessage({type: 'vault-audio', muted})`, and the game
page mutes itself with `storage/js/vault-audio.js` in that fork.

That script suspends every Web Audio context the game uses (and holds it if
the game tries to resume) and mutes audio and video elements. It handles game
frames inside the page too. `cloak.js`, which 521 of the 530 pages load, loads
it; the three game pages that don't load `cloak.js` load it directly. A game
answers `{type: 'vault-audio', ready: true}` when it loads. One that never
answers, like a game from any other site, gets "This game can't be muted from
here" instead of a silent failure.

## The vault's Ideas tab

A small tab after Chat where anyone can send the owner an idea, marked as a
game to add, a feature, something to fix or something else. `POST /api/idea`
needs no key, so it is rationed per address like link suggestions: one a
minute, five an hour, forty an hour from everyone, 150 waiting at most.
Swearing is masked and email addresses are removed before anything is
stored, but site names stay, since "add 1v1.lol" has to survive. Ideas are
kept as `ideas.json` on the `vault-data` branch.

Only `DEV_KEY` reads them (`GET /api/ideas` with `X-Dev-Key`). In dev mode the
inbox sits under the form, newest first, each with a **Done** button, plus
**Clear all**. The tab shows a count, and a new idea pops up live while the
owner's vault is open (`POST /api/ideas`: `{op: "done", id}` or
`{op: "clear"}`).

**Names:** a name that looks like a keyboard mash ("hihrhiegrhi", "asdfgh",
"lololol") gets one question before it's used, at first run and in Settings.
The question asks for a name friends will recognise, where a nickname is
fine. Pressing on again uses it anyway. The check was tested against 76 real
names and nicknames (Mimi, Rhys, Siobhan, Dj Khaled...) that must pass and
29 mashes that must not.

## Lyrics in the vault's music player

While a song with lyrics plays, each line pops up at its moment as a
**c00lgui** -- a black box with a thick red border and white text, growing out
from its centre somewhere new on screen each time. The button with the little screen in the
player turns them off (remembered per device).

**Adding them (dev mode):** play the song, open the player, press the pencil.
Paste the words one line per row -- an `.lrc` file's `[mm:ss.xx]` times are
read as they are -- set where to start from, press **Start**, and tap
**Space** (or the big button) as each line begins; **Undo** steps back one.
Then click any time to hear that line, nudge it with **-/+**, and **Save for
everyone**. **Remove** takes a song's lyrics away.

Kept like the links: `lyrics.json` on the `vault-data` branch, a map from a
track's address to its lines and start times. `GET /api/lyrics` is open;
`POST /api/lyrics` takes `DEV_KEY` (`{op: "set", track, title, lines}` or
`{op: "remove", track}`). Lines are cut to 160 characters, 300 a song.

## The vault's Chat tab

One room for everyone on the site, live over a websocket at `/chat` on this
server. The vault joins as soon as it loads (so people can reach you for
*Play together*, below); plain messages stay silent until you have opened the
Chat tab once. A copy opened from a file still waits for the Chat tab.

**The filter runs here, not in the page** (`chat_filter.py`): a filter in the
page is a suggestion anyone can delete in devtools. Every message and every
name is filtered before anyone else sees it. It is heavy on purpose and sees
through the usual disguises -- look-alike letters from other alphabets,
accents, full-width text, invisible characters, leet (`sh1t`, `a$$`), stretched
words (`fuuuuck`), punctuation between letters (`f.u.c.k`), a letter swapped
for `*` (`f*ck`) and words typed a letter at a time (`f u c k`). Slurs, sexual
terms and "kill yourself"-type phrases are filtered too. Matches are masked
with asterisks; links and email addresses are removed outright.

It deliberately leaves the classic false positives alone -- *class, assassin,
cockpit, grape, therapist, Scunthorpe, shiitake, cucumber, title, analysis,
raccoon, Essex, hello, shell, "this hit"* -- and a number on its own (a score of
455) is never masked. Tested against 112 disguised forms that must be caught
and 113 innocent words that must pass: all of both. Its patterns are bounded,
so no message can make it slow: a line of 240 asterisks once hung it for over
eight seconds, and now takes under a millisecond.

**Keeping one person from ruining it:** five messages at once then one every
1.2 s; the same line twice in 20 s is dropped; 240 characters at most; frames
over 4 KB close the socket; six chat sockets per address. Names the filter
would touch, or that claim to be staff (*owner, admin, mod...*), become
`Guest-1234`.

**Names, who's online, and @mentions.** The chat goes by the name set in the
vault -- at first run, or later in Settings -> Your Name -- and follows a
change live: the page tells the server its name on connecting and whenever it
changes, and the server answers with the name actually shown (a guest name if
it could not be used) and tells everyone the new list of who is online.
Type `@` and the names of people online come up to pick from. Mentions are
worked out on the server against that list -- `@Cool Bee` is one name even
with its space, the longest name wins where two overlap, only people online
count, and three at most per message. Mentioned while you are not on the Chat
tab and a card slides in with who and what they said; click it to jump to the
message. With the browser tab in the background the page title shows a count,
and desktop alerts can be switched on from the chat's bell (secure pages only).

**Chat in a game.** A game is left alone: the chat stays shut, and plain
messages neither show nor make a sound. Only a message that @mentions you
floats up over the game, and the dock's **Chat** button counts those. The
button opens a small panel with everything: the same room, filter and limits,
with the @ name picker. Drag it by its header, and double-click the header to
put it back where it started. It remembers where you put it, and every game
starts with it shut.

Messages near the 240-character limit show a counter instead of the box
silently refusing more letters.

**Moderation:** in the vault's dev mode each message gets Delete and Mute (30
minutes), and the header gets **Muted** and Clear chat. **Muted** lists who is
muted -- the name and the line they were muted for, and the minutes left -- with
**Unmute** on each; the person is told they can chat again. A mute goes by
connection, so it covers everyone on that network, which is what Unmute is
for. All of it is checked here against `DEV_KEY`, the same key the Links tab
uses. The owner's own messages carry an
OWNER badge, and only the owner can use a staff-sounding name.

**Privacy:** history is kept in memory only -- the last 80 messages -- and is
gone when the service sleeps. It is never written to disk or to the repo.
Addresses are held only as salted hashes, in memory, for the flood limits and
mutes, and are never sent to anyone.

## Play together (vault)

Beside the chat, **People here** lists everyone with the vault open and what
each is playing. Every row has two buttons:

- **Invite** -- ask them to play a game with you. In a game, it invites them
  to that game (the game window also has a **+ invite** tab under *close*);
  otherwise it opens a game picker. They get a card with **Play** / **No
  thanks**; a yes opens the game for them, and for you if you are not in it.
  A game only ever opens if it is in the receiver's own vault list.
- **Watch** -- ask to watch someone who is in a game. Saying yes has their
  browser ask what to share (the vault tab), and the picture goes **straight
  between the two browsers** (WebRTC, Google's public STUN servers to find a
  route). This server only relays the setup messages, and only inside a
  session the sharer agreed to. The viewer gets a window they can drag,
  resize, mute or make full screen; the sharer gets a red **LIVE** bar with
  **Stop**. Closing the game stops the sharing too.

Limits, enforced by the server: a request goes to one person by an id (names
are not unique) and runs out after a minute; one person can be asked by the
same sender at most every 15 seconds, and a sender can ask at most 8 times a
minute; muted chatters cannot ask; at most 4 people can watch one screen.
Setup messages are cut down to the two shapes WebRTC needs.

What can stop watching from working: phones cannot share a screen (their
**Watch** button stays grey for others); a school-managed device may block
screen sharing (the viewer is told); and some networks -- school or work
Wi-Fi especially -- block direct connections, since there is no relay server
(TURN) to fall back on. The viewer is told that too.

## THE ABYSS, wave 30

The TYRANT silenced **every tower on the board at once** there. Its pulse has a
300px radius and THE ABYSS is one long diagonal, so all sixteen towers sat
inside it -- an auto-played run went from 70 cores to 0 on that single wave. The
mechanic was meant to punish stringing a defence along one line, and it punished
it absolutely.

Only the nearest `SUPPRESS_MAX` (35%) of your towers now overload, so at least
two thirds of the line keeps firing however tightly it is packed:

| | cores after wave 30 | silenced |
|---|---|---|
| before | 0 | 16/16 |
| after | 60 | 6/16 |

Still open: CROSSFIRE dies at wave 20 to the LEVIATHAN, an air boss that ignores
the lane entirely. Different cause, not chased yet.

## Upgrade paths

Five towers shipped with a half-length second path -- HIVE/PAYLOAD,
VENOM/DISPERSAL, HALO/EDGE, MIRE/CAUSTIC and SEISMIC/RESONANCE each had two
upgrades where every other path has four. Those towers could not be taken past
tier 2 down their second path, and the tier bar, hardcoded to four pips,
reported "2 of 4" with nothing left to buy. Checked against the pre-roster-trim
commit: they were always short.

The missing tier 3 and 4 are written, and the tier bar now counts the path
rather than assuming four. Each effect uses a field the relevant tower kind
actually reads -- orbit blades ignore `crit`, tar pools ignore `burn`, and HALO
already flies, so three obvious-looking upgrades would have done nothing and are
not in there.

## Keyboard

The game binds bare letters -- C codex, F fast-forward, 1-6 tower select, SPACE
wave -- and its handler had no guard for a focused text field. Two things fell
out of that:

- Typing `BEESCANFLY` was also typing those shortcuts. The C in it opened the
  codex straight over the board and paused the game, which reads exactly like
  the game breaking. Each key of the passphrase is now swallowed by a
  capture-phase listener while it is still a valid prefix of the word; a key
  that is not continuing the word passes through untouched, so ordinary
  shortcuts are unaffected.
- Pasting or typing a save code into the transfer box was firing the same
  shortcuts underneath it. A focused input, textarea, select or contenteditable
  now owns the keyboard (Escape excepted), which fixes that independently of
  dev mode -- it is in the single-player file too.

Worth knowing when testing a deploy: a cached page will happily pretend a fix
did not land. The first verification run here was against a stale build and
looked like a failure.

## Sectors

Twelve now. Four were added this round, two NORMAL between DATA VORTEX and
CROSSFIRE, two HARD/EXTREME between THE ABYSS and SINGULARITY:

| | sector | lanes | shortest track |
|---|---|---|---|
| 5 | COOLANT RUN | 1 | 3535 |
| 6 | THE LATTICE | 2 | 3322 |
| 9 | VOLTAIC SPINE | 2 | 1873 |
| 10 | THE MAW | 3 | 1673 |

Geometry is the difficulty lever: a lane that wanders spends longer inside tower
range, so the run to the core shortens as sectors get harder. THE MAW first came
out at 1673 only after a correction -- its drop-in lanes measured 1466, shorter
than SINGULARITY's 1508, which would have made it harder than the final sector.

`mul` is now written per sector rather than derived from the index. It used to
be `1 + id * .035`, which meant inserting a sector in the middle silently made
every sector above it harder -- CROSSFIRE, THE ABYSS and SINGULARITY would each
have gained about 6% for no reason.

### Save migration

Progress, cleared flags and endless bests are keyed by sector index, so every
insert moves them. `SECTOR_MOVES` records each insert and a save walks whichever
steps it has not seen: a pre-everything save takes both shifts, a save from
between them takes only the second. Save-transfer codes carry their own version
and are migrated on import. Without this a save would show the new sectors as
already cleared and lose the ones above them.

### SINGULARITY, wave 12

Reported as far too hard, and I could not verify a fix. Two candidates were
ruled out by measurement: the per-lane cash bonus (0.22 / 0.4 / 0.6 made no
consistent difference) and the hull multiplier (1.245 down to 0.78 moved it from
wave 11 to 16 and did nothing for THE MAW). The auto-player is not trustworthy
on these maps -- the three lanes converge near the core and a person stacks that
junction, while the harness spreads towers evenly down each lane.

What was clearly stale: core pools were written when sectors had one or two
lanes. SINGULARITY asked you to hold three fronts out of the same 70 cores as
single-lane THE ABYSS. Three-front sectors now start with more (SINGULARITY 95,
THE MAW 92, VOLTAIC SPINE 82), which buys time to build rather than changing
what you fight. Treat this as unverified.

## TESLA

Buffed at the base so both paths benefit: `dmg 34->41`, `cd 58->52`,
`chains 3->4`, `chainFall .72->.78`, `range 215->230`. Its OVERLOAD path was
built around stun and lost the most in the control pass, and this puts that back
without handing the stun back.

| maxed, damage/sec | before | after |
|---|---|---|
| ARC STORM, 1 target | 233 | 281 |
| ARC STORM, 8 packed | 1,867 | 2,251 |
| OVERLOAD, 1 target | 596 | 763 |
| OVERLOAD, 8 packed | 1,555 | 2,467 |

## LANCE

A sixteenth tower. The gimmick came from Tower Defense Simulator's Military
Base -- a unit launched from the core end that drives the lane against traffic
and body-blocks -- but the tower around it is its own. A forge that prints a
wedge of hard light, not a motor pool: in a game of PULSE, PRISM and MIRE, tanks
and airstrikes read as a guest from somewhere else.

Its own idea is that **a lance feeds**. A share of every hull it breaks comes
back as mass, capped so it reaches a terminal size rather than growing forever.
That inverts the unit: it is not a tank wearing down, it is a snowball that
either gets fat or meets the one thing bigger than it has become.

The feed is a share of damage *dealt* while mass lost is damage divided by the
impact multiplier, so growth only turns net-positive once MASS is invested in.
Twenty-four drones fed to one lance:

| build | impact | feed | result |
|---|---|---|---|
| base | 1.0x | 35% | 900 -> 536, bleeds slower |
| Momentum | 2.2x | 35% | 1665 -> 1606, near break-even |
| AVALANCHE | 3.96x | 70% | 4163 -> 4413, **grows** |

**SUPERNOVA** turns everything a dying lance has eaten into a detonation, and is
the only part of the tower that reaches air -- an explosion does not care what
flies. Verified at 5,880 into an airborne gunship.

Otherwise unchanged from the original mechanic: collisions trade mass and ignore
armour so nothing walks through a living lance, the arc and pulse weapons cannot
touch air, and selling the forge destroys its lances.

An unlock survives the rename -- `TOWER_RENAMES` maps `convoy` to `lance` before
loadMeta's filters drop unknown keys, which would otherwise have silently eaten
the unlock for anyone who bought it.

## Typed codes

| code | effect |
|---|---|
| `BEEZAP247?!` | 50,000 flux, saved immediately. Stacks. |
| `BEESCANFLY` | opens the dev panel (co-op build only) |

Both run through one shared code table, deliberately. They have "BEE" in common,
and each has to swallow its keystrokes -- the game binds bare letters and digits,
so an unswallowed code also fires the codex, fast-forward and tower select as it
is typed. With two separate listeners whichever ran first would eat the shared
prefix and starve the other, silently breaking one of the codes.

A key is only swallowed while it is still building a code, so ordinary shortcuts
are untouched, and nothing fires while a text field has focus.

## Sandbox

A button next to ENDLESS on the sector screen. Every tower in the roster is
offered regardless of what the armoury has unlocked, credits refill, the core
cannot break, and ability cooldowns are cleared every tick. A small dock gives
WAVE -/+ and CLEAR, which is the actual point of the mode: looking at wave 40
without playing thirty-nine of them first.

**It pays nothing and records nothing** -- no flux, no stars, no progress, no
vault payout, and no endless best. Infinite money that also paid out would leave
the campaign with no reason to exist, so a sandbox run is sealed off from all of
it. The end screen says SANDBOX ENDED rather than claiming a result.

Sandbox is solo only. In co-op the host would be handing the guest a free run,
so the flag is cleared whenever a partner is connected.

The controls live inside `#waveDock` rather than being pinned over it, so the
column that already spaces the wave preview and SEND WAVE spaces them too, and
`#buildDock` reserves room for the ability dock and the wave dock on either
side -- sixteen towers otherwise run straight under both.

Verified: all 16 towers offered against a 3-tower loadout, cash and cores refill
from zero, abilities reset, wave jumps land, CLEAR empties the field, flux is
unchanged across a sandbox ending while a normal run still pays, and a normal
run afterwards shows only the equipped 3 with the dock hidden.

## Balance pass

Every tower measured one at a time, each path maxed alone (the path lock stops
you taking both past tier 2), against pinned dummies on the lane. Placement was
normalised out by trying several distances and keeping the best, because the
first two passes were measuring positioning rather than towers -- CRYO is a
short-splash pulse that reads zero past 160px, and MORTAR lobs at where a target
*will* be, so dummies whose lane position was never set made it aim at the lane
start. Dummy `maxHp` is realistic too: VENOM deals a share of max health, and
immortal dummies with 1e9 gave nine-figure nonsense.

Four outliers came out of it, and all four were adjusted:

| | was | now |
|---|---|---|
| pulse RAPID FIRE | 281 dmg per 1k credits -- best in the game, on the free starter | 93 |
| mire CAUSTIC | 264, and 15,759 against a crowd, from an "Area Denial" tower | 53, crowd 4,448 |
| cryo ABSOLUTE ZERO | 9, last place | 19 alone, **1.62x lift** on a neighbour |
| lance CHARGE | 0 kills -- units died before the weapons mattered | 59, matching MASS |

PULSE is free and needs no unlock, so its ceiling has to sit under the towers
you spend flux on. MIRE's corrosion and slow are what it is for; four stacked
damage multipliers had quietly made an area-denial tower the biggest number on
the board, and pools overlap so a crowd took it several times over.

CRYO's capstone is the interesting one. It measured last because a single-tower
test cannot see what it does: it now freezes harder and opens anything caught up
to +45% from *every* source, so its value is the lift it gives the rest of the
board -- verified as 458 -> 743 dps on a neighbouring TESLA. LANCE's CHARGE path
now carries its own mass, since without the MASS path its wedges were spent on
the first thing they touched and never fired.

These are lab numbers for one tower in isolation. They do not capture targeting
priority, synergy, or how a real wave actually arrives.

## Files

| | |
|---|---|
| `server.py` | matchmaking + serves the pages (standard library only) |
| `index.html` | the BeeSide Studio's front page at `/`: the hive, a door into each site with who is in there, and back -- the vault's header and the game's title screen each have a BeeSide button |
| `projects.html` | Other Projects at `/projects`: the front page's look, a door for each of the smaller projects |
| `rotfall.html` | ROTFALL, the first of the Other Projects, at `/rotfall` |
| `neon-siege-2-coop.html` | the game, at `/neon-siege` |
| `vault.html` | Bee's Vault, at `/vault` |
| `chat_filter.py` | the vault chat's word filter |
| `render.yaml` | Render blueprint |

Matchmaking is the only mode: press PLAY, get paired, and the host picks the
sector with **CHOOSE SECTOR** right there in the lobby.
