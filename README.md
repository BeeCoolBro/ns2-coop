# NEON SIEGE 2 — co-op

Deploy to Render (free), send your friend the URL, both press **PLAY**. You get
paired automatically and land in the same match. No codes, no port forwarding.

---

## Deploy

1. Push this repo to GitHub.
2. Render: **New → Blueprint**, pick the repo. `render.yaml` does the rest.
   (By hand: Runtime **Python**, Build Command *blank*, Start Command
   `python server.py`, Plan **Free**.)
3. Open the URL it gives you, e.g. `https://ns2-coop.onrender.com`.
4. Both players open it → **👥 CO-OP** → **PLAY**. First one waits, second one
   pairs instantly. Whoever is made host then presses **CHOOSE SECTOR** and
   deploys; the other drops in automatically.

No dependencies. `requirements.txt` is empty on purpose; it only tells Render
this is a Python service.

`/healthz` and `/stats` return `{ok, waiting, live, paired}` if you want to see
who is queued.

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

`http://localhost:8765`, plus a `same wifi:` address for someone on your
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

## Files

| | |
|---|---|
| `server.py` | matchmaking + serves the game (standard library only) |
| `neon-siege-2-coop.html` | the game |
| `render.yaml` | Render blueprint |

Matchmaking is the only mode: press PLAY, get paired, and the host picks the
sector with **CHOOSE SECTOR** right there in the lobby.
