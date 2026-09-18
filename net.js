// ═══════════════════════════════════════════════════════════
//  CO-OP  ·  two commanders, one grid
//
//  Host-authoritative. The host owns the only simulation there is; the
//  guest sends intents ("place a PULSE here") and draws whatever the host
//  reports back. Nothing is simulated twice, so there is no lockstep to
//  desync — Math.sin and friends are not bit-identical across engines and
//  a shared-seed model would drift apart within a wave.
//
//  One transport: a websocket to the matchmaking server, which pairs you with
//  whoever presses PLAY next and then just forwards bytes between you.
// ═══════════════════════════════════════════════════════════
const EKEYS = Object.keys(ENEMIES);          // TKEYS already exists up in the codex code
const TIDX = {}; TKEYS.forEach((k, i) => TIDX[k] = i);
const EIDX = {}; EKEYS.forEach((k, i) => EIDX[k] = i);

const NET = {
  mode: 'off',              // 'off' | 'host' | 'client'
  link: null,               // transport
  kind: '',                 // 'local' | 'online'
  ready: false,
  intents: [],              // host: queued guest actions
  fxq: [],                  // host: impulse effects since the last snapshot
  peer: null,               // partner cursor {x, y}
  lastSnap: 0,
  snapEvery: 4,             // host: send a snapshot every N sim ticks (15/s)
  recvT: 0,                 // client: performance.now() of the last snapshot
  gap: 66,                  // client: measured ms between snapshots
  partner: false,           // a peer is connected
  name: '',
};
function coop() { return NET.mode !== 'off'; }
function spectating() { return !!NET.spectate; }
function isClient() { return NET.mode === 'client'; }
function isHost() { return NET.mode === 'host'; }

// ── transport ────────────────────────────────────────────────────
// Matchmaking transport. Press PLAY, wait, get paired with whoever presses it
// next. The server decides who hosts (whoever waited longer), so the role is
// assigned on pairing rather than chosen up front.
function serverURL() {
  if (location.protocol.startsWith('http')) {
    return (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
  }
  return 'ws://localhost:8765/ws';           // opened from disk: assume a local server
}
function mmLink(url) {
  const addr = url || serverURL();
  const L = {onmsg: null, ws: null, tries: 0, dead: false,
    send(o) {
      if (L.ws && L.ws.readyState === 1) { try { L.ws.send(JSON.stringify({t: 'msg', m: o})); } catch (e) {} }
    },
    close() { L.dead = true; try { L.ws.close(); } catch (e) {} }};

  function open() {
    const ws = new WebSocket(addr);
    L.ws = ws;
    ws.onopen = () => { L.tries = 0; netStatus('looking for a partner…'); ws.send(JSON.stringify({t: 'find'})); };
    ws.onmessage = ev => {
      let d;
      try { d = JSON.parse(ev.data); } catch (e) { return; }
      if (d.t === 'waiting') { netStatus('waiting for someone else to press PLAY…'); return; }
      if (d.t === 'idle') { netStatus(''); return; }
      if (d.t === 'paired') {
        NET.mode = d.role === 'host' ? 'host' : 'client';
        NET.partner = true;
        if (NET.mode === 'host') { wireHost(); if (G.mode === 'play') sendStart(); }
        else wireClient();
        netStatus(NET.mode === 'host' ? 'partner found — you are hosting'
                                      : 'partner found — they are hosting');
        return;
      }
      if (d.t === 'gone') { NET.partner = false; netStatus('your partner left'); return; }
      if (d.t === 'msg' && L.onmsg) L.onmsg(d.m);
    };
    ws.onerror = () => {};
    // While still searching a dropped socket is worth retrying. Once a match is
    // running the host owns the simulation, so a drop ends it rather than
    // silently pairing someone with a stranger mid-wave.
    ws.onclose = () => {
      const wasPlaying = NET.partner;
      NET.partner = false;
      if (L.dead) { netStatus(''); return; }
      if (wasPlaying) { netStatus('connection lost — press PLAY to find someone new'); NET.mode = 'off'; return; }
      L.tries++;
      if (L.tries > 6) { netStatus('cannot reach the server — press PLAY to retry'); NET.mode = 'off'; return; }
      netStatus('reconnecting… (' + L.tries + ')');
      setTimeout(open, Math.min(8000, 700 * L.tries));
    };
  }
  open();
  return L;
}
// Once paired, the host needs an obvious way into a match. Without this the
// lobby is a dead end: the only route in was BACK -> CAMPAIGN, which nobody
// would guess, so it looked like the game had no launch button at all.
function coopUI() {
  const go = $('coopGo');
  if (!go) return;
  const paired = NET.partner;
  go.style.display = (paired && isHost()) ? 'inline-flex' : 'none';
  const find = $('btnCoopFind'), stop = $('btnCoopStop'), wait = $('coopWait');
  if (find) find.style.display = paired ? 'none' : 'inline-flex';
  if (stop) stop.style.display = (!paired && NET.mode === 'searching') ? 'inline-flex' : 'none';
  if (wait) wait.style.display = (paired && isClient()) ? 'block' : 'none';
}
function coopFind() {
  if (NET.link) { try { NET.link.close(); } catch (e) {} }
  NET.mode = 'searching'; NET.kind = 'server'; NET.partner = false;
  NET.link = mmLink(($('coopServer').value || '').trim() || undefined);
  netStatus('connecting…');
}

// ── lobby ────────────────────────────────────────────────────────
function netStatus(s) {
  const el = $('coopState');
  if (!el) return;
  const txt = {waiting: 'waiting for your partner…', linked: 'LINKED', lost: 'partner disconnected',
               offer: 'send your partner the code above', answer: 'paste their reply below'};
  el.textContent = txt[s] || s;
  coopUI();
  const tag = $('coopTag');
  if (tag) {
    tag.style.display = NET.partner ? 'flex' : 'none';
    tag.textContent = (NET.mode === 'host' ? '◆ HOSTING' : '◆ GUEST') + (NET.partner ? '' : ' · solo');
  }
}





function coopLeave() {
  if (NET.link) NET.link.close();
  NET.mode = 'off'; NET.link = null; NET.partner = false; NET.peer = null;
  NET.intents.length = 0; NET.fxq.length = 0;
  netStatus('');
}

// ── host side ────────────────────────────────────────────────────
function wireHost() {
  NET.link.onmsg = m => {
    if (!m) return;
    if (m.k === 'join' || m.k === 'hello') {
      NET.partner = true; netStatus('linked');
      if (G.mode === 'play') sendStart();
      return;
    }
    if (m.k === 'cursor') { NET.peer = {x: m.x, y: m.y}; return; }
    if (m.k === 'dev') { devApply(m); return; }
    NET.intents.push(m);
  };
  if (NET.link.onopen !== undefined) NET.link.onopen = () => { if (G.mode === 'play') sendStart(); };
}
function sendStart() {
  if (!isHost() || !NET.link) return;
  NET.link.send({k: 'start', map: G.map, diff: G.diff, endless: G.endless,
                 load: META.loadout.slice(), abils: META.abils.slice()});
}
// Apply whatever the guest asked for. Every intent goes through the same
// functions the host's own clicks do, so the rules cannot diverge.
function applyIntents() {
  for (const m of NET.intents) {
    if (m.k === 'place') placeTower(m.x, m.y, m.type);
    else if (m.k === 'sell') { const t = towerById(m.id); if (t) sellTower(t); }
    else if (m.k === 'upg') { const t = towerById(m.id); if (t) buyUpgrade(t, m.pi, m.ti); }
    else if (m.k === 'abil') fireAbility(m.i, m.x, m.y);
    else if (m.k === 'wave') startWave();
    else if (m.k === 'mode') { const t = towerById(m.id); if (t) t.targetMode = m.v; }
  }
  NET.intents.length = 0;
}
function towerById(id) { for (const t of G.towers) if (t.id === id) return t; return null; }

// The guest never runs endGame itself: progress, flux and the vault payout all
// belong to the host's match, and paying them twice from one account would be
// wrong. It gets the result screen, not the rewards.
function sendOver(won) {
  if (!isHost() || !NET.link) return;
  NET.link.send({k: 'over', won: !!won, wave: G.wave, score: G.score, kills: G.kills,
                 leaked: G.leaked, cores: G.cores, maxCores: G.maxCores,
                 endless: !!G.endless, map: G.map, diff: G.diff});
}

const R2 = v => Math.round(v * 100) / 100;
function snapshot() {
  const T = [];
  for (const t of G.towers)
    T.push(t.id, TIDX[t.type], Math.round(t.x), Math.round(t.y), Math.round(t.ang * 100),
           t.tiers[0], t.tiers[1], t.flash | 0, t.targetMode | 0, t.firing ? 1 : 0,
           Math.round((t.heat || 0) * 100), Math.round(t.spent),
           Math.round((t.accGlow || 0) * 100));
  const E = [];
  // hp and shield travel as 0-1000 ratios: the guest only ever draws them as
  // bars, and two ratios are a lot fewer bytes than four absolute values
  for (const e of G.enemies)
    E.push(e.eid, EIDX[e.type], Math.round(e.x), Math.round(e.y), Math.round(e.ang * 100),
           Math.round(clamp(e.hp / e.maxHp, 0, 1) * 1000),
           e.maxShield > 0 ? Math.round(clamp(e.shield / e.maxShield, 0, 1) * 1000) : 0,
           (e.air ? 1 : 0) | (e.cloak ? 2 : 0) | (e.revealed ? 4 : 0) | (e.boss ? 8 : 0) |
           (e.hitFlash > 0 ? 16 : 0) | (e.freeze > 0 || e.shock > 0 ? 32 : 0) | (e.burn > 0 ? 64 : 0),
           Math.round(e.r));
  const P = [];
  for (const p of G.projs)
    if (p.delay <= 0) P.push(Math.round(p.x), Math.round(p.y), Math.round(p.r * 10),
                             TIDX[p.src.type] | 0, Math.round(p.z || 0));
  const L = [];
  for (const pl of G.pools)
    L.push(Math.round(pl.x), Math.round(pl.y), Math.round(pl.r),
           pl.haste ? 2 : (pl.tar ? 1 : 0), pl.life | 0);
  const Wl = [];
  for (const w of G.wells) Wl.push(Math.round(w.x), Math.round(w.y), Math.round(w.r), w.life | 0);
  const Mn = [];
  for (const m of G.mines) Mn.push(Math.round(m.x), Math.round(m.y), m.arm | 0);
  const Dr = [];
  for (const d of G.drones) Dr.push(Math.round(d.x), Math.round(d.y),
                                    Math.round(d.ang * 100), TIDX[d.src.type] | 0);
  // rigs: the guest draws them, so it needs the hull bar and whether the
  // turret is fitted -- both come from the depot, sent as a tower index
  const Rg = [];
  for (const r of G.rigs) Rg.push(Math.round(r.x), Math.round(r.y), Math.round(r.ang * 100),
    Math.round(clamp(r.hp / Math.max(1, r.maxHp), 0, 1) * 255),
    (r.src && r.src.rigCannon ? 2 : 0) | (r.src && r.src.rigGun ? 1 : 0));
  // gunships: heading and rotor phase so they read as flying, plus one bar
  // that is ammunition while hunting and the rearm filling back up on the pad
  const Hl = [];
  for (const h of G.helis) {
    const t = h.src, re = h.rearm > 0;
    const fill = re ? clamp(1 - h.rearm / Math.max(1, t.heliRearm), 0, 1)
                    : clamp(h.ammo / Math.max(1, t.heliAmmo), 0, 1);
    Hl.push(Math.round(h.x), Math.round(h.y), Math.round(h.ang * 100), Math.round(h.rot * 100),
            Math.round(fill * 255), (re ? 1 : 0) | (h.fire > 0 ? 2 : 0), TIDX[t.type] | 0);
  }
  const X = [];
  for (const f of G.fx)
    X.push([f.k, Math.round(f.x), Math.round(f.y), Math.round(f.x2 || 0), Math.round(f.y2 || 0),
            Math.round(f.r || 0), Math.round(f.R || 0), f.life, f.max, f.c, Math.round(f.w || 0)]);

  const s = {
    k: 'snap', t: G.time,
    m: [G.wave, G.waveActive ? 1 : 0, G.cores, G.maxCores, Math.round(G.cash), Math.round(G.score),
        G.kills, G.leaked, Math.round(G.combo * 100), G.finale ? 1 : 0, G.stasis, G.overclock,
        G.aegis, Math.round(G.prepT), G.mode === 'play' ? 1 : 0, G.paused ? 1 : 0],
    a: G.abilCd.slice(),
    // How many numbers each tower occupies in T. Sent so a guest reading a host
    // older than itself still lines up. A guest OLDER than the host cannot be
    // helped after the fact, which is exactly why this goes in before the next
    // field is added rather than after.
    T, TS: 13, E, P, L, W: Wl, N: Mn, D: Dr, G: Rg, H: Hl, X,
    f: NET.fxq.splice(0, NET.fxq.length),
    c: G.hover ? [Math.round(G.hover.x), Math.round(G.hover.y)] : null,
  };
  if (NET.link && isHost() && NET.partner) NET.link.send(s);
  if (CAST.ws && CAST.ws.readyState === 1 && CAST.watchers > 0) {
    try { CAST.ws.send(JSON.stringify({t: 'msg', m: s})); } catch (e) {}
  }
}

// ── client side ──────────────────────────────────────────────────
function wireClient() {
  NET.link.onmsg = m => {
    if (!m) return;
    if (m.k === 'hello') { NET.partner = true; netStatus('linked'); NET.link.send({k: 'join'}); return; }
    if (m.k === 'start') {
      NET.partner = true; netStatus('linked');
      META.loadout = m.load; META.abils = m.abils;
      const keep = NET.mode;
      NET._starting = true;                  // let this one through the guard
      startGame(m.map, m.diff, m.endless);
      NET._starting = false;
      NET.mode = keep;                       // startGame must not clear our role
      G.enemies.length = 0; G.towers.length = 0; G.groups.length = 0;
      closeAll();
      return;
    }
    if (m.k === 'over') { netEnd(m); return; }
    if (m.k === 'snap') applySnap(m);
  };
  if (NET.link.onopen !== undefined) NET.link.onopen = () => NET.link.send({k: 'join'});
}

const _cTow = new Map(), _cEn = new Map();
function applySnap(s) {
  const now = performance.now();
  if (NET.recvT) NET.gap = Math.max(16, Math.min(400, now - NET.recvT));
  NET.recvT = now;
  NET.partner = true;

  const m = s.m;
  G.wave = m[0]; G.waveActive = !!m[1]; G.cores = m[2]; G.maxCores = m[3]; G.cash = m[4];
  G.score = m[5]; G.kills = m[6]; G.leaked = m[7]; G.combo = m[8] / 100; G.finale = !!m[9];
  G.stasis = m[10]; G.overclock = m[11]; G.aegis = m[12]; G.prepT = m[13];
  G.paused = !!m[15];
  G.abilCd = s.a;
  NET.peer = s.c ? {x: s.c[0], y: s.c[1]} : null;

  // towers — rebuilt through makeTower so the inspector has real stats
  const seen = new Set();
  const TS = s.TS || 12;
  for (let i = 0; i < s.T.length; i += TS) {
    const id = s.T[i], type = TKEYS[s.T[i + 1]];
    let t = _cTow.get(id);
    if (!t || t.type !== type) {
      t = makeTower(s.T[i + 2], s.T[i + 3], type);
      t.id = id; t.tiers = [0, 0];
      _cTow.set(id, t);
    }
    t.x = s.T[i + 2]; t.y = s.T[i + 3]; t.ang = s.T[i + 4] / 100; t.tAng = t.ang;
    // replay any upgrades we have not applied yet so displayed stats match
    for (const pi of [0, 1]) {
      const want = s.T[i + 5 + pi];
      while (t.tiers[pi] < want) {
        const up = t.def.paths[pi].ups[t.tiers[pi]];
        if (up && up.f) up.f(t);
        t.tiers[pi]++;
      }
    }
    t.flash = s.T[i + 7]; t.targetMode = s.T[i + 8]; t.firing = s.T[i + 9];
    t.heat = s.T[i + 10] / 100; t.spent = s.T[i + 11];
    t.accGlow = TS > 12 ? s.T[i + 12] / 100 : 0;
    seen.add(id);
  }
  for (const id of [..._cTow.keys()]) if (!seen.has(id)) _cTow.delete(id);
  G.towers = [..._cTow.values()];
  if (G.selTower && !seen.has(G.selTower.id)) { G.selTower = null; closeInspector(); }
  else if (G.selTower) G.selTower = _cTow.get(G.selTower.id) || null;

  // enemies — px/py hold the previous position so the existing renderer lerps
  const es = new Set();
  for (let i = 0; i < s.E.length; i += 9) {
    const id = s.E[i], type = EKEYS[s.E[i + 1]];
    let e = _cEn.get(id);
    if (!e) {
      const d = ENEMIES[type];
      e = {type, def: d, name: d.name, shape: d.shape, color: d.color, eid: id,
           x: s.E[i + 2], y: s.E[i + 3], px: s.E[i + 2], py: s.E[i + 3], ang: 0,
           d: 0, seg: 0, route: G.lanes[0], dead: false, affix: null,
           chill: 0, chillF: 0, tar: 0, venom: 0, venomN: 0, mark: 0, wob: Math.random() * TAU};
      _cEn.set(id, e);
    } else { e.px = e.x; e.py = e.y; }
    e.x = s.E[i + 2]; e.y = s.E[i + 3]; e.ang = s.E[i + 4] / 100;
    e.hp = s.E[i + 5]; e.maxHp = 1000;                 // ratios, see snapshot()
    e.shield = s.E[i + 6]; e.maxShield = s.E[i + 6] > 0 ? 1000 : 0;
    const fl = s.E[i + 7];
    e.air = !!(fl & 1); e.cloak = !!(fl & 2); e.revealed = !!(fl & 4); e.boss = !!(fl & 8);
    e.hitFlash = (fl & 16) ? 4 : 0; e.freeze = (fl & 32) ? 4 : 0; e.burn = (fl & 64) ? 4 : 0;
    e.r = s.E[i + 8]; e.phase += .12;
    es.add(id);
  }
  for (const id of [..._cEn.keys()]) if (!es.has(id)) _cEn.delete(id);
  G.enemies = [..._cEn.values()];

  G.projs = [];
  for (let i = 0; i < s.P.length; i += 5) {
    const src = TOWERS[TKEYS[s.P[i + 3]]];
    G.projs.push({x: s.P[i], y: s.P[i + 1], px: s.P[i], py: s.P[i + 1], r: s.P[i + 2] / 10,
                  color: src ? src.color : '#fff', z: s.P[i + 4], kind: 'bolt', delay: 0,
                  src: {color: src ? src.color : '#fff'}});
  }
  G.pools = [];
  for (let i = 0; i < s.L.length; i += 5)
    G.pools.push({x: s.L[i], y: s.L[i + 1], r: s.L[i + 2],
                  tar: s.L[i + 3] === 1 ? 1 : 0, haste: s.L[i + 3] === 2 ? .55 : 0,
                  life: s.L[i + 4], dps: 0, src: null});
  G.wells = [];
  for (let i = 0; i < s.W.length; i += 4)
    G.wells.push({x: s.W[i], y: s.W[i + 1], r: s.W[i + 2], life: s.W[i + 3], spin: G.time * .09});
  G.mines = [];
  for (let i = 0; i < s.N.length; i += 3)
    G.mines.push({x: s.N[i], y: s.N[i + 1], arm: s.N[i + 2], life: 999, pulse: G.time * .07, rot: 0});
  G.drones = [];
  for (let i = 0; i < s.D.length; i += 4) {
    const src = TOWERS[TKEYS[s.D[i + 3]]];
    G.drones.push({x: s.D[i], y: s.D[i + 1], ang: s.D[i + 2] / 100,
                   src: {color: src ? src.color : '#fff'}});
  }
  G.rigs.length = 0;
  const RG = s.G || [];
  for (let i = 0; i < RG.length; i += 5) {
    const fl = RG[i + 4] | 0;
    G.rigs.push({x: RG[i], y: RG[i + 1], ang: RG[i + 2] / 100,
                 hp: RG[i + 3], maxHp: 255, flash: 0, wob: (RG[i] + RG[i + 1]) * .01,
                 src: {color: TOWERS.lance ? TOWERS.lance.color : '#7dffd4',
                       rigGun: fl & 1, rigCannon: fl & 2}});
  }
  // the fake src carries 255 as its full scale, so one byte drives the bar
  G.helis.length = 0;
  const HL = s.H || [];
  for (let i = 0; i < HL.length; i += 7) {
    const fl = HL[i + 5] | 0, src = TOWERS[TKEYS[HL[i + 6]]];
    G.helis.push({x: HL[i], y: HL[i + 1], ang: HL[i + 2] / 100, rot: HL[i + 3] / 100,
                  ammo: HL[i + 4], rearm: (fl & 1) ? 255 - HL[i + 4] : 0, fire: (fl & 2) ? 2 : 0,
                  src: {color: src ? src.color : '#ffb03d', heliAmmo: 255, heliRearm: 255}});
  }
  G.fx = [];
  for (const f of s.X)
    G.fx.push({k: f[0], x: f[1], y: f[2], x2: f[3], y2: f[4], r: f[5], R: f[6],
               life: f[7], max: f[8], c: f[9], w: f[10]});

  // impulses: replayed locally so particles and audio feel native
  for (const ev of s.f) {
    const t = ev[0];
    if (t === 'b') burst(ev[1], ev[2], ev[3], ev[4], ev[5]);
    else if (t === 'k') spark(ev[1], ev[2], ev[3]);
    else if (t === 'f') float(ev[1], ev[2], ev[3], ev[4], ev[5]);
    else if (t === 's') sfx(ev[1]);
    else if (t === 'B') banner(ev[1], ev[2], ev[3]);
    else if (t === 'T') toast(ev[1], ev[2], ev[3], ev[4]);
    else if (t === 'q') shake(ev[1], ev[2]);
    else if (t === 'l') flash(ev[1], ev[2]);
  }
  if (m[14] === 0 && G.mode === 'play') { /* host left play; hold the last frame */ }
  syncHUD();
}
function netEnd(m) {
  G.mode = m.won ? 'win' : 'lose';
  stopMusic();
  const map = MAPS[m.map];
  const eT = $('endT'), eS = $('endS');
  eT.textContent = m.endless ? 'ENDLESS OVER' : (m.won ? 'SECTOR SECURED' : 'CORE BREACHED');
  eT.style.color = m.won ? 'var(--g)' : 'var(--m)';
  eS.textContent = (m.won ? map.name + ' · ' + DIFFS[m.diff].name
                          : 'Overrun on wave ' + m.wave + ' · ' + map.name)
                 + '  —  your partner was hosting';
  $('endStars').innerHTML = '';
  $('endFlux').innerHTML = '';
  $('endFluxBreak').textContent = 'Rewards are credited to the host of this match.';
  const hp = $('endHoney'); if (hp) hp.style.display = 'none';
  const grid = $('endGrid');
  if (grid) grid.innerHTML =
    [['WAVE', m.wave], ['KILLS', m.kills], ['LEAKED', m.leaked],
     ['SCORE', fmt(m.score)], ['CORES', m.cores + '/' + m.maxCores]]
    .map(r => '<div class="res"><b>' + r[1] + '</b><span>' + r[0] + '</span></div>').join('');
  sfx(m.won ? 'victory' : 'defeat');
  closeAll();
  $('ovEnd').classList.add('on');
}

// interpolation factor between the last two snapshots
function netAlpha() {
  if (!NET.recvT) return 1;
  return clamp((performance.now() - NET.recvT) / NET.gap, 0, 1.4);
}

// ── impulse capture on the host ──────────────────────────────────
// burst/float/sfx and friends are called from deep inside the sim; wrapping
// them is far less invasive than threading an event list through every call.
function netCapture() {
  const _burst = burst, _spark = spark, _float = float, _sfx = sfx,
        _banner = banner, _toast = toast, _shake = shake, _flash = flash;
  // PV is set while the armoury preview is running the real tick on a world of
  // its own. Without it a host reading a tower's card would stream that card's
  // explosions, floats and sounds onto their partner's board.
  const send = () => isHost() && !PV;
  burst = (x, y, c, n, sp) => { if (send()) NET.fxq.push(['b', Math.round(x), Math.round(y), c, n, sp]); return _burst(x, y, c, n, sp); };
  spark = (x, y, c) => { if (send()) NET.fxq.push(['k', Math.round(x), Math.round(y), c]); return _spark(x, y, c); };
  float = (x, y, t, c, s) => { if (send()) NET.fxq.push(['f', Math.round(x), Math.round(y), t, c, s]); return _float(x, y, t, c, s); };
  sfx = k => { if (send()) NET.fxq.push(['s', k]); return _sfx(k); };
  banner = (t, s, c) => { if (send()) NET.fxq.push(['B', t, s, c]); return _banner(t, s, c); };
  toast = (i, t, d, c) => { if (send()) NET.fxq.push(['T', i, t, d, c]); return _toast(i, t, d, c); };
  shake = (a, c) => { if (send()) NET.fxq.push(['q', a, c]); return _shake(a, c); };
  flash = (c, a) => { if (send()) NET.fxq.push(['l', c, a]); return _flash(c, a); };
}

// ── partner cursor ───────────────────────────────────────────────
let _curT = 0;
function netCursor() {
  if (!coop() || !NET.link || !G.hover) return;
  const n = performance.now();
  if (n - _curT < 90) return;
  _curT = n;
  if (isClient()) NET.link.send({k: 'cursor', x: Math.round(G.hover.x), y: Math.round(G.hover.y)});
}
function drawPeer() {
  if (!coop() || !NET.peer) return;
  const p = NET.peer, T = G.time;
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.strokeStyle = '#ffd633'; ctx.lineWidth = 2;
  ctx.globalAlpha = .75 + Math.sin(T * .12) * .2;
  ctx.beginPath(); ctx.arc(p.x, p.y, 13, 0, TAU); ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(p.x - 20, p.y); ctx.lineTo(p.x - 7, p.y);
  ctx.moveTo(p.x + 7, p.y); ctx.lineTo(p.x + 20, p.y);
  ctx.moveTo(p.x, p.y - 20); ctx.lineTo(p.x, p.y - 7);
  ctx.moveTo(p.x, p.y + 7); ctx.lineTo(p.x, p.y + 20);
  ctx.stroke();
  ctx.restore();
}


// ═══════════════════════════════════════════════════════════
//  DEV MODE
//
//  Type the passphrase anywhere to open the panel. That only unlocks the UI on
//  this machine -- it proves nothing. The server checks its own DEV_KEY, which
//  lives in the environment and has no default, so if you have not set one on
//  the deployment then nothing below can do anything at all.
//
//  Spectating reuses the guest path wholesale: a guest already renders a match
//  from the host's snapshots without simulating anything, which is exactly what
//  a spectator is. The only difference is a dead transport, so the intents the
//  guest UI tries to send go nowhere.
// ═══════════════════════════════════════════════════════════
// ── broadcasting ─────────────────────────────────────────────────
// Dev mode could only ever see a paired co-op match, because a match is what
// pairing creates -- so a campaign run, which is how the game is mostly played,
// was invisible. Every game now announces itself on its own socket. It stays
// silent until somebody actually watches: the server reports the spectator
// count and nothing is streamed while that is zero, so a solo player is not
// uploading 15 snapshots a second into the void.
const CAST = {ws: null, id: 0, watchers: 0, tries: 0, dead: false};

function castStart() {
  if (isClient()) return;                 // a guest has nothing of its own to show
  castOpen();
  castAnnounce();
}
function castOpen() {
  if (CAST.ws && (CAST.ws.readyState === 0 || CAST.ws.readyState === 1)) return;
  let ws;
  try { ws = new WebSocket(serverURL()); } catch (e) { return; }
  CAST.ws = ws;
  ws.onopen = () => { CAST.tries = 0; ws.send(JSON.stringify({t: 'session'})); castAnnounce(); };
  ws.onclose = () => {
    CAST.watchers = 0;
    // a broadcast is a nicety, so retry quietly a few times and then give up
    if (!CAST.dead && CAST.tries++ < 4 && G.mode === 'play') setTimeout(castOpen, 2000 * CAST.tries);
  };
  ws.onerror = () => {};
  ws.onmessage = ev => {
    let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (d.t === 'session') { CAST.id = d.id; CAST.watchers = d.n | 0; castAnnounce(); return; }
    if (d.t === 'watchers') {
      const was = CAST.watchers;
      CAST.watchers = d.n | 0;
      if (!was && CAST.watchers) castAnnounce();   // resend the map to a new arrival
      return;
    }
    if (d.t === 'msg' && d.m && d.m.k === 'dev') devApply(d.m);
  };
}
// The map, so a spectator arriving mid-run draws the right sector. The server
// keeps the last one and replays it to anyone who starts watching.
function castAnnounce() {
  if (!CAST.ws || CAST.ws.readyState !== 1 || G.mode !== 'play') return;
  try {
    CAST.ws.send(JSON.stringify({t: 'msg', m: {k: 'start', map: G.map, diff: G.diff,
      endless: !!G.endless, load: META.loadout.slice(), abils: META.abils.slice()}}));
  } catch (e) {}
}
function castStop() {
  CAST.dead = true;
  CAST.watchers = 0;
  try { if (CAST.ws) CAST.ws.close(); } catch (e) {}
  CAST.ws = null;
}

const DEV_WORD = 'BEESCANFLY';
const DEV = {open: false, ws: null, auth: false, watching: null, rows: [], el: null};

// The passphrase goes through the shared code table in the base game, so it
// cannot fight the other codes over the "BEE" prefix they have in common.
addCode(DEV_WORD, devOpen);

function devEl() {
  if (DEV.el) return DEV.el;
  const d = document.createElement('div');
  d.id = 'devPanel';
  d.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:60;' +
    'width:min(94vw,560px);padding:13px 15px;border-radius:11px;display:none;' +
    'background:rgba(8,12,24,.95);border:1px solid rgba(180,107,255,.5);' +
    'box-shadow:0 18px 50px rgba(0,0,0,.7);backdrop-filter:blur(12px);font-family:var(--f2)';
  d.innerHTML =
    '<div style="display:flex;align-items:center;gap:9px;margin-bottom:9px">' +
      '<span style="font-family:var(--f1);font-weight:900;font-size:12px;letter-spacing:.18em;color:#b46bff">DEV MODE</span>' +
      '<span id="devState" style="font-size:11.5px;color:var(--txm);font-weight:600;flex:1"></span>' +
      '<button class="btn" id="devClose" style="padding:5px 11px;font-size:9.5px">CLOSE</button>' +
    '</div>' +
    '<div id="devAuth" style="display:flex;gap:7px;align-items:center">' +
      '<input id="devKey" type="password" placeholder="server DEV_KEY" autocomplete="off" ' +
        'style="flex:1;padding:8px 10px;border-radius:7px;border:1px solid var(--line);' +
        'background:rgba(0,0,0,.45);color:var(--tx);font-family:var(--f1);font-size:11px">' +
      '<button class="btn pri" id="devGo" style="padding:8px 14px;font-size:10px">UNLOCK</button>' +
    '</div>' +
    '<div id="devBody" style="display:none">' +
      '<div id="devList" style="display:flex;flex-direction:column;gap:5px;max-height:190px;overflow-y:auto"></div>' +
      '<div id="devTools" style="display:none;gap:7px;align-items:center;margin-top:10px;' +
           'padding-top:10px;border-top:1px solid var(--line)">' +
        '<select id="devType" style="flex:1;padding:7px;border-radius:7px;border:1px solid var(--line);' +
           'background:rgba(0,0,0,.45);color:var(--tx);font-family:var(--f1);font-size:10.5px"></select>' +
        '<input id="devN" type="number" min="1" max="40" value="6" ' +
           'style="width:64px;padding:7px;border-radius:7px;border:1px solid var(--line);' +
           'background:rgba(0,0,0,.45);color:var(--tx);font-family:var(--f1);font-size:10.5px">' +
        '<button class="btn" id="devSpawn" style="padding:8px 14px;font-size:10px;' +
           'border-color:#ff2d9b;color:#ff2d9b">SUMMON</button>' +
        '<button class="btn" id="devStop" style="padding:8px 12px;font-size:10px">STOP WATCHING</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(d);
  DEV.el = d;

  const sel = d.querySelector('#devType');
  for (const k of EKEYS) {
    const o = document.createElement('option');
    o.value = k; o.textContent = ENEMIES[k].name;
    sel.appendChild(o);
  }
  d.querySelector('#devClose').onclick = () => devClose();
  d.querySelector('#devGo').onclick = () => devAuth();
  d.querySelector('#devKey').onkeydown = ev => { if (ev.key === 'Enter') devAuth(); };
  d.querySelector('#devSpawn').onclick = () => devSpawn();
  d.querySelector('#devStop').onclick = () => devStopWatch();
  return d;
}
function devSay(t) { const e = document.getElementById('devState'); if (e) e.textContent = t; }
function devOpen() { DEV.open = true; devEl().style.display = 'block'; document.getElementById('devKey').focus(); }
function devClose() { DEV.open = false; if (DEV.el) DEV.el.style.display = 'none'; }

function devAuth() {
  const key = (document.getElementById('devKey').value || '').trim();
  if (!key) { devSay('enter the key set on the server'); return; }
  try { if (DEV.ws) DEV.ws.close(); } catch (e) {}
  devSay('connecting…');
  const ws = new WebSocket(serverURL());
  DEV.ws = ws;
  ws.onopen = () => ws.send(JSON.stringify({t: 'admin', key}));
  ws.onclose = () => { DEV.auth = false; devSay('disconnected'); };
  ws.onerror = () => devSay('cannot reach the server');
  ws.onmessage = ev => {
    let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (d.t === 'admin') {
      DEV.auth = !!d.ok;
      devSay(d.ok ? 'unlocked' : 'refused — wrong key, or DEV_KEY is not set on the server');
      document.getElementById('devAuth').style.display = d.ok ? 'none' : 'flex';
      document.getElementById('devBody').style.display = d.ok ? 'block' : 'none';
      if (d.ok) devRefresh();
      return;
    }
    if (d.t === 'matches') { DEV.rows = d.rows || []; devDraw(); return; }
    if (d.t === 'watch') {
      if (d.ok) { devSay('watching match ' + d.id); DEV.watching = d.id; devBeginSpectate(); }
      else { devSay('that match has ended'); devStopWatch(true); }
      document.getElementById('devTools').style.display = d.ok ? 'flex' : 'none';
      return;
    }
    // a game frame from the match being watched -- hand it to the guest path
    if (d.t === 'msg' && NET.link && NET.link.onmsg) NET.link.onmsg(d.m);
  };
}
function devRefresh() {
  if (DEV.ws && DEV.ws.readyState === 1 && DEV.auth) DEV.ws.send(JSON.stringify({t: 'list'}));
}
setInterval(() => { if (DEV.open && DEV.auth) devRefresh(); }, 3000);

function devDraw() {
  const list = document.getElementById('devList');
  if (!list) return;
  if (!DEV.rows.length) { list.innerHTML = '<div style="font-size:12px;color:var(--txm);font-weight:600">no matches running</div>'; return; }
  list.innerHTML = '';
  for (const r of DEV.rows) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:9px;align-items:center;padding:7px 9px;border-radius:7px;' +
      'background:rgba(255,255,255,.04);border:1px solid ' +
      (r.id === DEV.watching ? 'rgba(180,107,255,.6)' : 'rgba(255,255,255,.07)');
    row.innerHTML = '<span style="font-family:var(--f1);font-size:11px;color:#b46bff">#' + r.id + '</span>' +
      '<span style="flex:1;font-size:11.5px;color:var(--txm);font-weight:600">' +
        (r.solo ? 'solo' : 'co-op') + ' · ' + r.mins + ' min · ' +
        r.spectators + ' watching' + (r.ready ? '' : ' · no map yet') + '</span>';
    const b = document.createElement('button');
    b.className = 'btn';
    b.style.cssText = 'padding:5px 11px;font-size:9.5px';
    b.textContent = r.id === DEV.watching ? 'WATCHING' : 'WATCH';
    b.onclick = () => DEV.ws.send(JSON.stringify({t: 'watch', id: r.id}));
    row.appendChild(b);
    list.appendChild(row);
  }
}

// Become a guest with a dead transport: renders the match, sends nothing.
function devBeginSpectate() {
  castStop();
  NET.spectate = true;
  NET.mode = 'client';
  NET.partner = true;
  NET.link = {send() {}, close() {}, onmsg: null, onopen: undefined};
  wireClient();
  netStatus('spectating');
}
function devStopWatch(quiet) {
  if (DEV.ws && DEV.ws.readyState === 1 && !quiet) DEV.ws.send(JSON.stringify({t: 'unwatch'}));
  DEV.watching = null;
  NET.spectate = false;
  const tools = document.getElementById('devTools');
  if (tools) tools.style.display = 'none';
  coopLeave();
  quitToMenu();
  devDraw();
}
function devSpawn() {
  if (!DEV.auth || !DEV.watching) return;
  const type = document.getElementById('devType').value;
  const n = clamp(parseInt(document.getElementById('devN').value, 10) || 1, 1, 40);
  DEV.ws.send(JSON.stringify({t: 'inject', id: DEV.watching, op: 'spawn', type, n}));
  devSay('sent ' + n + ' \u00d7 ' + (ENEMIES[type] ? ENEMIES[type].name : type));
}

// ── the host end: obey, but only within the rules of the sim ──
// Injected units are ordinary enemies built by the ordinary spawner, so they
// take damage, pay bounty and die exactly like anything else in the wave.
function devApply(m) {
  if (!m || m.op !== 'spawn') return;
  const type = ENEMIES[m.type] ? m.type : 'drone';
  const n = clamp(m.n | 0, 1, 40);
  const hs = hpScale(Math.max(1, G.wave));
  for (let i = 0; i < n; i++) {
    const e = spawnEnemy(type, hs, i % Math.max(1, G.lanes.length), null);
    if (!e) continue;
    e.d = Math.max(0, 6 + i * 9);
    const p = routeAt(e.route, e.d, e);
    e.x = e.px = p.x; e.y = e.py = p.y;
  }
}
