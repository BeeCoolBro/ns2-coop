# -*- coding: utf-8 -*-
"""Build neon-siege-2-coop.html from the single-player game.

Run it from anywhere: the paths are relative to this file, which now lives
beside the two things it reads and the one it writes. The single-player file is
never touched, and the coop build is only written once every patch has landed,
so a stale anchor cannot leave half a game on the server.

EVERY failing anchor is reported, not just the first one. The single-player
file is edited constantly and this is run rarely, so a build after a stretch of
work usually has several patches to repair -- and finding them one run at a
time is the slowest possible way to do it.
"""
import io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'neon-siege-2.html')
DST = os.path.join(HERE, 'neon-siege-2-coop.html')

src = io.open(SRC, encoding='utf-8').read()
s = src

_miss = []
_n = [0]


def rep(a, b, n=1):
    global s
    _n[0] += 1
    c = s.count(a)
    if c != n:
        # ascii-escaped: the report goes to a console that is not always utf-8,
        # and a build tool must not fall over on the character it is reporting
        _miss.append((_n[0], 'missing' if c == 0 else 'found %d, wanted %d' % (c, n),
                      a.strip().split('\n')[0][:96].encode('ascii', 'replace').decode()))
        return
    s = s.replace(a, b, n)


# 1. enemies need a stable id to sync by
rep("let towerId = 0, hitstop = 0;", "let towerId = 0, enemyId = 0, hitstop = 0;")
rep("affix:null, bossPhase:0,", "affix:null, bossPhase:0, eid:++enemyId,")

# 2. the net layer, just before BOOT
NET = io.open(os.path.join(HERE, 'net.js'), encoding='utf-8').read()
rep("""// ═══════════════════════════════════════════════════════════
//  BOOT""", NET + """
// ═══════════════════════════════════════════════════════════
//  BOOT""")

# 3. client actions become intents
rep("""function placeTower(x, y, type) {
  const cost = towerCost(type);""",
"""function placeTower(x, y, type) {
  if (isClient()) { NET.link.send({k:'place', x, y, type}); return true; }
  const cost = towerCost(type);""")
# Both of these now open with HARDWARE's ownership guard, so the intent hop goes
# in above it -- a guest has no ally of its own and the host is the one that
# owns the rule anyway.
rep("""function sellTower(t) {
  // His grid, his call.""",
"""function sellTower(t) {
  if (!t) return;
  if (isClient()) { NET.link.send({k:'sell', id:t.id}); return; }
  // His grid, his call.""")
rep("""function buyUpgrade(t, pi, ti) {
  // His grid, his guns, his bill.""",
"""function buyUpgrade(t, pi, ti) {
  if (isClient()) { NET.link.send({k:'upg', id:t.id, pi, ti}); return; }
  // His grid, his guns, his bill.""")
rep("""function fireAbility(i, x, y) {
  const a = slotAbil(i);""",
"""function fireAbility(i, x, y) {
  if (isClient()) { NET.link.send({k:'abil', i, x, y}); G.aiming = -1; refreshAbilities(); return; }
  const a = slotAbil(i);""")
rep("""function startWave() {
  if (G.waveActive || G.mode !== 'play') return;""",
"""function startWave() {
  if (isClient()) { NET.link.send({k:'wave'}); return; }
  if (G.waveActive || G.mode !== 'play') return;""")

# 4. the loop: guests draw, they do not simulate
rep("""  if (G.mode === 'play' && !G.paused) {
    if (hitstop > 0) hitstop -= dt;
    else {
      acc += dt * G.speed;
      let steps = 0;
      // The catch-up budget has to grow with the speed or 4x quietly runs slow:
      // a 30fps frame at 4x already needs eight steps, and the leftover is dropped.
      const cap = G.speed > 2 ? G.speed * 4 : 10;
      while (acc >= STEP && steps < cap) { tick(); acc -= STEP; steps++; }
      if (steps === cap) acc = 0;
    }
    syncHUD();
  }
  render(clamp(acc / STEP, 0, 1));""",
"""  if (isClient()) {                       // guest: no simulation, just interpolate
    netCursor();
    render(netAlpha());
    return;
  }
  if (isHost()) applyIntents();
  if (G.mode === 'play' && !G.paused) {
    if (hitstop > 0) hitstop -= dt;
    else {
      acc += dt * G.speed;
      let steps = 0;
      // The catch-up budget has to grow with the speed or 4x quietly runs slow:
      // a 30fps frame at 4x already needs eight steps, and the leftover is dropped.
      const cap = G.speed > 2 ? G.speed * 4 : 10;
      while (acc >= STEP && steps < cap) { tick(); acc -= STEP; steps++; }
      if (steps === cap) acc = 0;
    }
    syncHUD();
  }
  const _wantSnap = (isHost() && NET.partner) || (CAST.watchers > 0 && !NET.spectate);
  if (_wantSnap && G.time - NET.lastSnap >= NET.snapEvery) {
    NET.lastSnap = G.time; snapshot();
  }
  render(clamp(acc / STEP, 0, 1));""")

# 5. the partner's cursor, drawn over the board
# HARDWARE's cursor joined this list between the overlay and the floats, so the
# partner's goes in above both of them rather than at the old offset.
rep("""  drawProjs(alpha);
  drawDrones();
  drawRigs();
  drawHelis();
  drawAimOverlay();
  drawAllyCursor();
  drawFloats();""",
"""  drawProjs(alpha);
  drawDrones();
  drawRigs();
  drawHelis();
  drawPeer();
  drawAimOverlay();
  drawAllyCursor();
  drawFloats();""")

# 6. the host tells the guest which sector it picked
rep("""  initAudio(); startMusic();""", """  initAudio(); startMusic();
  if (isHost()) sendStart();
  CAST.dead = false; castStart();""")

# 6b. only the host picks the sector
rep("""function startGame(mapIdx, diffIdx, endless) {""",
"""function startGame(mapIdx, diffIdx, endless) {
  if (isClient() && !NET._starting) {
    toast('\N{BUSTS IN SILHOUETTE}', 'YOUR PARTNER IS HOSTING',
          'The host picks the sector and difficulty.', '#ffd633');
    return;
  }""")

# 6c. tell the guest when the match ends
# endGame now opens with the scripted sector's rescue branch, which returns
# before the run is really over. The guest is told after that, not before it --
# a core breach that HARDWARE answers is not a loss to report.
rep("""    grailRescue();
    return;
  }
  G.mode = won ? 'win' : 'lose';""",
"""    grailRescue();
    return;
  }
  if (isHost()) sendOver(won);
  G.mode = won ? 'win' : 'lose';""")

# 7. lobby overlay
rep("""<!-- ══════════ MAP SELECT ══════════ -->""",
"""<!-- ══════════ CO-OP ══════════ -->
<style>
/* this build has four modes, so they sit two by two instead of three and a stray */
#modeGrid{grid-template-columns:repeat(2,1fr)}
@media (max-width:520px){#modeGrid{grid-template-columns:1fr}}
</style>
<div class="ov" id="ovCoop">
  <div class="ovBox" style="max-width:760px">
    <div class="ovT" style="font-size:clamp(20px,3.4vw,32px);color:var(--c)">CO-OP</div>
    <div class="ovS">Two commanders, one grid. Shared credits, shared cores.</div>

    <div style="font-size:12.5px;color:var(--txd);line-height:1.9;margin-bottom:16px">
      Press PLAY and you go into the queue. The moment anyone else presses it,
      you are paired and dropped into the same match together.
    </div>
    <div class="ovBtns" style="margin-bottom:12px">
      <button class="btn pri" id="btnCoopFind" style="font-size:14px;padding:14px 40px">👥 PLAY</button>
      <button class="btn" id="btnCoopStop" style="display:none">CANCEL</button>
      <button class="btn pri" id="coopGo" style="display:none;font-size:14px;padding:14px 40px">▶ CHOOSE SECTOR</button>
    </div>
    <div id="coopWait" style="display:none;font-size:12.5px;color:var(--txd);line-height:1.8;margin-bottom:10px">
      Your partner is picking the sector … you will drop in automatically.
    </div>
    <details style="margin-bottom:6px">
      <summary style="font-size:11px;color:var(--txd);cursor:pointer;letter-spacing:.1em">server address</summary>
      <input id="coopServer" class="coopIn" placeholder="wss://your-app.onrender.com/ws"
             style="width:100%;margin-top:8px">
      <div style="font-size:11px;color:var(--txd);line-height:1.7;margin-top:6px">
        Leave blank when you opened this page from the server itself.
      </div>
    </details>

    <div id="coopState" style="margin-top:18px;font-size:12.5px;letter-spacing:.1em;color:var(--c);font-weight:700"></div>
    <div class="ovBtns" style="margin-top:20px">
      <button class="btn" id="btnCoopBack">BACK</button>
      <button class="btn" id="btnCoopLeave">DISCONNECT</button>
    </div>
  </div>
</div>

<!-- ══════════ MAP SELECT ══════════ -->""")

rep("""      </button>
    </div>

    <div class="sect">ACCOUNT</div>""",
"""      </button>
      <button class="modeCard" id="btnCoop" style="--ac:#5cff9d">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.4 19.6v-1.8a3.6 3.6 0 0 0-3.6-3.6H6.6A3.6 3.6 0 0 0 3 17.8v1.8"/><circle cx="9.2" cy="7.3" r="3.6"/><path d="M21 19.6v-1.8a3.6 3.6 0 0 0-2.7-3.5"/><path d="M15.8 4.1a3.6 3.6 0 0 1 0 7"/></svg>
        <span><span class="mn">CO-OP</span><span class="mz">Two commanders, one grid</span></span>
      </button>
    </div>

    <div class="sect">ACCOUNT</div>""")

# 7b. resolution: the single biggest cost in the frame
rep("""function resize() {
  const st = document.getElementById('stage');
  const cw = st.clientWidth || 1280, chh = st.clientHeight || 720;
  dpr = Math.min(window.devicePixelRatio || 1, 2);""",
"""// Rendering at full device resolution is what actually costs: a 1920x1080
// window at devicePixelRatio 2 is an 8.3 megapixel canvas, and the frame time
// roughly doubles against the same window at dpr 1 (measured: 4.8ms -> 9.7ms
// with 118 enemies on screen). Cap the backing store by PIXEL COUNT instead of
// by dpr, so one number holds on every screen size, and let adaptQuality trim
// it further on a slow machine. The canvas is CSS-sized, so the browser simply
// scales whatever we hand it.
const MAXPX = 2600000;                  // ~1970x1320, past which nothing looks better
let RSCALE = 1;                         // adaptive multiplier, lowered under load
function resize() {
  const st = document.getElementById('stage');
  const cw = st.clientWidth || 1280, chh = st.clientHeight || 720;
  const want = Math.min(window.devicePixelRatio || 1, 2);
  const fit = Math.sqrt(MAXPX / Math.max(1, cw * chh));
  dpr = Math.max(.55, Math.min(want, fit) * RSCALE);""")

rep("""  if (fps < 34) { lowFrames++; if (lowFrames > 3 && BLOOM) { BLOOM = false; toast('⚙️', 'PERFORMANCE', 'Bloom disabled to keep the frame rate up.', '#ffd633'); } }
  else if (fps > 52) lowFrames = 0;""",
"""  // Resolution first: it is the only lever that scales the whole frame at once.
  // Bloom only goes as a last resort, because losing it changes how the game looks.
  if (fps < 48) {
    lowFrames++; hiFrames = 0;
    // Measured: frame time is flat from 1 to 12.6 megapixels on this scene, so
    // the frame is draw-call bound, not fill bound. Thin the entity work first
    // and only touch resolution as a last resort, where it costs clarity.
    if (lowFrames > 1 && PARTMAX > 260) PARTMAX = Math.max(260, PARTMAX - 220);
    else if (lowFrames > 2 && BLOOM) { BLOOM = false; toast('⚙️', 'PERFORMANCE', 'Bloom disabled to keep the frame rate up.', '#ffd633'); }
    else if (lowFrames > 4 && RSCALE > .62) { RSCALE = Math.max(.62, RSCALE - .16); resize(); }
  } else if (fps > 57) {
    lowFrames = 0;
    if (++hiFrames > 8) {
      if (RSCALE < 1) { RSCALE = Math.min(1, RSCALE + .12); resize(); }
      else if (PARTMAX < 900) PARTMAX = Math.min(900, PARTMAX + 160);
      hiFrames = 0;
    }
  } else { lowFrames = 0; hiFrames = 0; }""")

rep("let acc = 0, last = 0, fpsAcc = 0, fpsN = 0, fps = 60, lowFrames = 0;",
    "let acc = 0, last = 0, fpsAcc = 0, fpsN = 0, fps = 60, lowFrames = 0, hiFrames = 0;")

# 8. styles + the in-match badge
rep("""/* armoury */""",
"""/* co-op */
.coopIn{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.16);border-radius:8px;
  color:var(--txm);font-family:var(--f1);font-size:14px;font-weight:800;padding:10px 12px}
#coopTag{display:none;position:absolute;top:62px;left:50%;transform:translateX(-50%);z-index:40;
  gap:8px;align-items:center;padding:5px 14px;border-radius:20px;font-family:var(--f1);font-size:10.5px;
  font-weight:900;letter-spacing:.18em;color:#ffd633;background:rgba(255,214,51,.10);
  border:1px solid rgba(255,214,51,.35);pointer-events:none}

/* armoury */""")
rep("""<canvas id="gc"></canvas>""", """<canvas id="gc"></canvas>
<div id="coopTag"></div>""")

# 8b. the HUD wrote every field to the DOM 60 times a second; only write changes
rep("""function syncHUD() {""",
"""// Each of these writes is a style recalc even when the value is identical, and
// syncHUD runs every frame. Caching the last value written turns most frames
// into no DOM work at all.
const _hudV = {};
function hudTxt(id, v) { if (_hudV[id] !== v) { _hudV[id] = v; $(id).textContent = v; } }
function hudW(id, v) { const k = id + '|w'; if (_hudV[k] !== v) { _hudV[k] = v; $(id).style.width = v; } }
function hudBg(id, v) { const k = id + '|b'; if (_hudV[k] !== v) { _hudV[k] = v; $(id).style.background = v; } }
function syncHUD() {""")

rep("""  $('sCore').textContent = Math.max(0, G.cores);
  $('sCoreBar').style.width = (cf * 100) + '%';
  $('sCoreBar').style.background = cf > .5 ? 'var(--m)' : cf > .25 ? 'var(--y)' : '#ff3d3d';""",
"""  hudTxt('sCore', String(Math.max(0, G.cores)));
  hudW('sCoreBar', (cf * 100) + '%');
  hudBg('sCoreBar', cf > .5 ? 'var(--m)' : cf > .25 ? 'var(--y)' : '#ff3d3d');""")

# The wave readout grew two story branches and HARDWARE's panel landed in the
# middle of this run of writes, so it is two patches now instead of one.
rep("""  $('sWave').textContent = (G.story && G.story.fixed) ? G.wave + '/' + G.story.fixed
    : (G.story && G.story.glitch) ? glitchWave()
    : G.endless ? G.wave + '/∞' : G.wave + '/' + MAPS[G.map].waves;
  $('sScore').textContent = fmt(G.score);""",
"""  hudTxt('sWave', (G.story && G.story.fixed) ? G.wave + '/' + G.story.fixed
    : (G.story && G.story.glitch) ? glitchWave()
    : G.endless ? G.wave + '/∞' : G.wave + '/' + MAPS[G.map].waves);
  hudTxt('sScore', fmt(G.score));""")
rep("""  const pu = powerUsed(), pm = powerMax();
  $('sGrid').textContent = pu + '/' + pm;
  $('sGridBar').style.width = clamp(pu / pm * 100, 0, 100) + '%';
  $('sGridBar').style.background = pu / pm > .92 ? 'var(--m)' : pu / pm > .75 ? 'var(--y)' : 'var(--v)';""",
"""  const pu = powerUsed(), pm = powerMax();
  hudTxt('sGrid', pu + '/' + pm);
  hudW('sGridBar', clamp(pu / pm * 100, 0, 100) + '%');
  hudBg('sGridBar', pu / pm > .92 ? 'var(--m)' : pu / pm > .75 ? 'var(--y)' : 'var(--v)');""")

# 8c. the actual hot spots, found by profiling a wave-34 board:
#     enemies 5.9ms of a 16.3ms frame, and rgba() is called from 359 sites,
#     rebuilding a CSS colour string (and re-parsing the hex) every single time.
rep("""function hexToRgb(h) {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgba(h, a) { const c = hexToRgb(h); return `rgba(${c[0]},${c[1]},${c[2]},${a})`; }""",
"""const _hexC = new Map(), _rgbaC = new Map();
function hexToRgb(h) {
  let v = _hexC.get(h);
  if (v) return v;
  const n = parseInt(h.slice(1), 16);
  v = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  _hexC.set(h, v);
  return v;
}
// Alpha is usually driven by a sine, so it never repeats exactly and an
// unquantised cache would grow without bound. 1/128 steps are indistinguishable
// on screen and make the cache hit almost every time.
function rgba(h, a) {
  const q = a <= 0 ? 0 : a >= 1 ? 128 : (a * 128) | 0;
  const k = h + q;
  let s = _rgbaC.get(k);
  if (s === undefined) {
    const c = hexToRgb(h);
    s = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + (q / 128) + ')';
    if (_rgbaC.size > 6000) _rgbaC.clear();
    _rgbaC.set(k, s);
  }
  return s;
}""")

# skip anything outside the view: enemies walk in from well off-map
rep("""  // ground units first, then air (so air reads as above)
  for (const t of G.towers) drawTower(t, false);
  for (const e of G.enemies) if (!e.air) drawEnemy(e, alpha);
  for (const e of G.enemies) if (e.air) drawEnemy(e, alpha);""",
"""  // ground units first, then air (so air reads as above). Anything outside the
  // view is skipped -- units spawn well off-map and walk in.
  const vl = viewL - 70, vr = viewR + 70, vt = viewT - 70, vb = viewB + 70;
  const onView = o => o.x > vl && o.x < vr && o.y > vt && o.y < vb;
  for (const t of G.towers) drawTower(t, false);
  for (const e of G.enemies) if (!e.air && onView(e)) drawEnemy(e, alpha);
  for (const e of G.enemies) if (e.air && onView(e)) drawEnemy(e, alpha);""")

# particles are the third cost; keep a budget and let adaptQuality tighten it
rep("""function burst(x, y, c, n, sp) {""",
"""let PARTMAX = 900;
function burst(x, y, c, n, sp) {
  if (G.parts.length > PARTMAX) return;
  n = G.parts.length > PARTMAX * .7 ? Math.ceil(n * .5) : n;""")

# 9. wire the lobby, and capture impulses for the guest
rep("""document.addEventListener('pointerdown', () => initAudio(), {once:true});""",
"""netCapture();
$('btnCoop').onclick = () => { closeAll(); $('ovCoop').classList.add('on'); netStatus(''); coopUI(); };
$('btnCoopBack').onclick = () => { closeAll(); $('ovTitle').classList.add('on'); };
$('btnCoopLeave').onclick = () => { coopLeave(); netStatus('disconnected'); };
$('btnCoopFind').onclick = () => coopFind();
$('btnCoopStop').onclick = () => {
  if (NET.link && NET.mode === 'searching') { try { NET.link.ws.send(JSON.stringify({t:'cancel'})); } catch (e) {} }
  coopLeave();
};
$('coopGo').onclick = () => openSectors('campaign');

document.addEventListener('pointerdown', () => initAudio(), {once:true});""")

rep("""  for (const id of ['ovTitle', 'ovMaps', 'ovPause', 'ovEnd', 'ovCodex', 'ovArmoury']) document.getElementById(id).classList.remove('on');""",
"""  for (const id of ['ovTitle', 'ovMaps', 'ovPause', 'ovEnd', 'ovCodex', 'ovArmoury', 'ovCoop']) document.getElementById(id).classList.remove('on');""")

# 10. cursor sharing from the host too
rep("""cv.addEventListener('pointermove', ev => {
  if (G.mode !== 'play') return;
  G.hover = worldPoint(ev);
});""",
"""cv.addEventListener('pointermove', ev => {
  if (G.mode !== 'play') return;
  G.hover = worldPoint(ev);
  netCursor();
});""")

# write only once everything above succeeded, so a failed patch cannot
# leave a half-built file behind
if _miss:
    print('%d of %d patches did not apply:\n' % (len(_miss), _n[0]))
    for i, why, frag in _miss:
        print('  #%-2d  %-20s %s' % (i, why, frag))
    print('\nNothing written. Repair these against the current single-player file.')
    sys.exit(1)

tmp = DST + '.tmp'
io.open(tmp, 'w', encoding='utf-8', newline='').write(s)
if os.path.exists(DST):
    os.remove(DST)
os.rename(tmp, DST)
print('built %s  (+%d lines, %d patches applied)'
      % (os.path.basename(DST), s.count('\n') - src.count('\n'), _n[0]))
