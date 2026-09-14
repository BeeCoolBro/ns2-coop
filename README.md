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

## Files

| | |
|---|---|
| `server.py` | matchmaking + serves the game (standard library only) |
| `neon-siege-2-coop.html` | the game |
| `render.yaml` | Render blueprint |

Matchmaking is the only mode: press PLAY, get paired, and the host picks the
sector with **CHOOSE SECTOR** right there in the lobby.
