# NEON SIEGE 2 — co-op server

Deploy this to Render (free), send your friend the URL, and play from anywhere.
One of you presses **HOST** and reads out four letters; the other types them in.

No port forwarding, no tunnels, no codes to paste.

---

## Deploy

1. Push this folder to a new GitHub repo.
2. On Render: **New → Blueprint**, pick the repo. `render.yaml` sets everything
   up. (Or **New → Web Service** by hand: Runtime **Python**, Build Command
   *blank*, Start Command `python server.py`, Plan **Free**.)
3. Wait for the first deploy. You get a URL like
   `https://ns2-coop.onrender.com`.
4. Both of you open that URL. **👥 CO-OP → ROOM CODE → HOST**, read out the
   four letters, the other types them and presses **JOIN**.

The page serves itself from the same service, so the game figures out the
websocket address on its own — nothing to configure.

There are no dependencies. `requirements.txt` is empty on purpose; it just tells
Render this is a Python service.

## What the free plan actually means

Checked against Render's docs rather than assumed:

- **It sleeps.** A free web service spins down after **15 minutes** with no
  inbound traffic, and takes **about a minute** to wake. So the first person to
  open the URL after a quiet spell waits out a loading page. Open it, wait for
  the title screen, *then* press HOST and share the code. While you are playing
  the traffic keeps it awake.
- **750 instance hours/month** per workspace — one service running continuously
  is about 730, so a single free service fits.
- **WebSockets are supported** and, per Render's docs, have no fixed timeout.
  They do close when the instance is replaced, which happens on every deploy.
- **Outbound bandwidth counts** against your workspace allowance. A busy match
  pushes about 71 KB/s to the guest, so roughly 130 MB per half-hour session.

Because instance replacement drops sockets, the client reconnects with backoff
and the host **reclaims its own room code** on the way back in — so a redeploy
mid-session puts you back together without anyone retyping anything. A room is
held for 15 minutes after both sides vanish, then forgotten.

## Running it locally instead

```bash
python server.py
```

Serves on `http://localhost:8765` and prints a `same wifi:` address for someone
on your network. `PORT` is honoured if set, which is how Render starts it.

## How the co-op works

Host-authoritative. The host runs the only simulation; the guest sends intents
("place a PULSE here") and draws the snapshots that come back at 15/s.

This was chosen over lockstep deliberately: `Math.sin`, `Math.pow` and friends
are not bit-identical across JavaScript engines, so two copies running the same
seed drift apart within a wave with no cheap way to notice. With one authority
there is nothing to desync.

Every guest intent is applied by calling the *same* `placeTower` / `buyUpgrade` /
`fireAbility` that the host's own clicks call, so the rules cannot diverge — the
host re-validates placement, cost and cooldowns, and an illegal request is
simply refused.

The server never parses a game message. It pairs two sockets by code and
forwards bytes.

**Rewards go to the host only.** The guest sees the result screen but no flux or
vault payout: both players awarding themselves from one match would double-pay.

## Files

| | |
|---|---|
| `server.py` | room pairing + serves the game (standard library only) |
| `neon-siege-2-coop.html` | the game |
| `render.yaml` | Render blueprint |
| `requirements.txt` | empty; marks this as a Python service |

The lobby also still has **SAME COMPUTER** (two tabs, no server) and a
**DIRECT** peer-to-peer option if you ever want them.
