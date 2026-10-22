/* BeeSide's openings: Bee's Vault, NEON SIEGE 2 and ROTFALL.

   The front page plays them. Pick a door and the opening starts at once over
   the front page, while the place loads in the front page's frame underneath.
   For the opening's last second the place shows through, and the opening
   lands on it: NEON SIEGE 2's logo on its title screen, ROTFALL's name on its
   menu's name, the vault's card swinging past you into it. Opened any other way
   (BeeSide's single-file copy, a file on disk, the game inside Bee's Vault) a
   page plays its own opening over itself, from this same file.

   BSOpenings[name](o) plays one and returns { skip(), cancel() }. o:
     host      the document to play in (default: this one)
     target()  the place's document once it exists, or null
     ready()   true once the place is loaded enough to be shown
     reveal()  let the place show through (the last second)
     done()    the opening is over
     quick     the short version (already seen this session)
     calm      less motion: the name, then a fade
     silent    no sound
   Sound comes from beeside-sound.js (window.BSND), in the host's window. */
(function () {
  if (window.BSOpenings) return;
  var O = window.BSOpenings = {};
  var TAU = Math.PI * 2;
  function rnd(a, b) { return a + Math.random() * (b - a); }
  function eio(k) { return k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2; }
  function eout(k) { return 1 - Math.pow(1 - k, 3); }
  function ein(k) { return k * k * k; }
  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function css(doc, id, text) {
    if (!doc || doc.getElementById(id)) return;
    var s = doc.createElement('style');
    s.id = id; s.textContent = text;
    (doc.head || doc.documentElement).appendChild(s);
  }
  function fine(win) { try { return win.matchMedia('(hover: hover) and (pointer: fine)').matches; } catch (e) { return true; } }

  // ── one opening's lifetime: its element, timers, frames, sound, its end ──
  function Run(o, id, markup) {
    var doc = o.host || document, win = doc.defaultView || window;
    var el = doc.createElement('div');
    el.id = id;
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = markup;
    (doc.body || doc.documentElement).appendChild(el);
    var R = { doc: doc, win: win, el: el, quick: !!o.quick, calm: !!o.calm, over: false, revealed: false, timers: [] };
    R.SN = o.silent ? null : (win.BSND || window.BSND || null);
    if (R.SN) R.SN.start();
    R.live = function () { return !!(R.SN && R.SN.live()); };
    R.later = function (fn, ms) { var t = setTimeout(function () { if (!R.over) fn(); }, ms); R.timers.push(t); return t; };
    R.target = function () { try { return (o.target && o.target()) || null; } catch (e) { return null; } };
    R.ready = function () { try { return !o.ready || !!o.ready(); } catch (e) { return true; } };
    // wait for the place, at most ms, then go on regardless
    R.whenReady = function (fn, ms) {
      var t0 = Date.now();
      (function w() { if (R.over) return; if (R.ready() || Date.now() - t0 > (ms || 14000)) fn(); else R.later(w, 90); })();
    };
    R.reveal = function () { if (R.revealed) return; R.revealed = true; try { if (o.reveal) o.reveal(); } catch (e) {} };
    function unhook() { win.removeEventListener('keydown', onKey, true); }
    R.end = function () {
      if (R.over) return;
      R.over = true;
      R.timers.forEach(clearTimeout);
      unhook();
      if (el.parentNode) el.parentNode.removeChild(el);
      R.reveal();
      try { if (o.done) o.done(); } catch (e) {}
    };
    R.cancel = function () {
      if (R.over) return;
      R.over = true;
      R.timers.forEach(clearTimeout);
      unhook();
      if (el.parentNode) el.parentNode.removeChild(el);
    };
    // a click or a key skips (after a moment, so the click that opened it does not);
    // while it plays, keys go no further
    var skipFn = null, armAt = Date.now() + 450;
    function onKey(e) { if (R.over) return; e.stopPropagation(); if (Date.now() > armAt && skipFn) skipFn(); }
    el.addEventListener('pointerdown', function () { if (Date.now() > armAt && skipFn) skipFn(); });
    win.addEventListener('keydown', onKey, true);
    R.onSkip = function (fn) { skipFn = fn; };
    var sk = el.querySelector('.bso-skip');
    if (sk) sk.textContent = fine(win) ? 'CLICK TO SKIP' : 'TAP TO SKIP';
    R.api = { skip: function () { if (skipFn) skipFn(); }, cancel: R.cancel };
    return R;
  }

  // ════════════════════════════════════════════════════════════════════
  //  BEE'S VAULT: the front page's Bee's Vault card comes forward. It lifts
  //  out of its place on the front page (or rises in the middle, opened any
  //  other way), its gold dial turns to each of six locks while the lamps in
  //  its pill light up, it greets you by name, the vault spills out what is
  //  inside as it does when you point at the card, and the card swings past
  //  you into the vault. Gold on ink, like the card: no glare.
  // ════════════════════════════════════════════════════════════════════
  var VAULT_CSS = [
    '#bsoVault{position:fixed;inset:0;z-index:2147483000;overflow:hidden;cursor:pointer;-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent;',
    '  color:#eef0ff;font-family:Rajdhani,Montserrat,system-ui,sans-serif;animation:bsoFailsafe .4s linear 30s forwards}',
    '@keyframes bsoFailsafe{to{opacity:0;visibility:hidden;pointer-events:none}}',
    '#bsoVault .bv-bg{position:absolute;inset:0;background:radial-gradient(ellipse 80% 70% at 50% 46%,#0b0d18,#05060c 70%);opacity:0;transition:opacity .35s ease}',
    '#bsoVault .bv-bg::after{content:"";position:absolute;inset:-60px;background-image:url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'56\' height=\'100\'%3E%3Cpath d=\'M28 66 0 50V16L28 0l28 16v34L28 66v34M28 0v34L0 50v34l28 16 28-16V50L28 34\' fill=\'none\' stroke=\'%23ffd633\' stroke-opacity=\'.07\' stroke-width=\'1\'/%3E%3C/svg%3E");',
    '  background-size:56px 100px;-webkit-mask-image:radial-gradient(ellipse 55% 50% at 50% 46%,#000 20%,transparent 75%);mask-image:radial-gradient(ellipse 55% 50% at 50% 46%,#000 20%,transparent 75%)}',
    '#bsoVault.bv-on .bv-bg{opacity:1}',
    '#bsoVault.out{opacity:0;pointer-events:none;transition:opacity .8s cubic-bezier(.4,0,.2,1)}',
    // the card: the front page's Bee's Vault door, larger
    '#bsoVault .bv-card{position:absolute;left:50%;top:46%;width:clamp(300px,40vw,540px);min-height:clamp(290px,44vh,400px);box-sizing:border-box;margin:0;',
    '  translate:-50% -50%;display:flex;flex-direction:column;justify-content:flex-end;gap:8px;padding:30px 30px 28px;border-radius:24px;overflow:hidden;isolation:isolate;',
    '  background:linear-gradient(160deg,#0a0c16,#070810 70%);border:1px solid #1b1f33;box-shadow:0 1px 0 rgba(255,255,255,.04) inset,0 30px 70px rgba(0,0,0,.6);',
    '  opacity:0;transform-origin:50% 50%}',
    '#bsoVault .bv-card::before{content:"";position:absolute;inset:0;z-index:-3;background:radial-gradient(120% 90% at 100% 0%,rgba(255,214,51,.16),transparent 60%),radial-gradient(90% 70% at 0% 100%,rgba(255,159,28,.10),transparent 65%)}',
    '#bsoVault .bv-card::after{content:"";position:absolute;inset:0;z-index:-1;border-radius:inherit;padding:1px;pointer-events:none;background:linear-gradient(135deg,#ffd633,transparent 40%,transparent 60%,#ff9f1c);',
    '  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask:linear-gradient(#000 0 0) content-box exclude,linear-gradient(#000 0 0);opacity:.55}',
    '#bsoVault .bv-idx{position:absolute;top:24px;left:30px;font-family:Orbitron,"Arial Black",sans-serif;font-weight:900;font-size:14px;letter-spacing:.22em;color:rgba(255,214,51,.55)}',
    '#bsoVault .bv-art{position:absolute;width:76%;aspect-ratio:1;right:-17%;top:-17%;z-index:-2;opacity:.6;transition:opacity .5s ease}',
    '#bsoVault .bv-art svg{width:100%;height:100%;display:block;overflow:visible}',
    '#bsoVault .bv-ring{transform-origin:100px 100px;animation:bvSpin 40s linear infinite}',
    '@keyframes bvSpin{to{transform:rotate(360deg)}}',
    '#bsoVault .bv-dial,#bsoVault .bv-dial-in{transform-origin:100px 100px;transform-box:view-box}',
    '#bsoVault .bv-dial{transition:transform .9s cubic-bezier(.16,1,.3,1)}',
    '#bsoVault .bv-dial-in{transition:transform .2s cubic-bezier(.34,1.56,.64,1)}',
    '#bsoVault.bv-named .bv-art{opacity:.9}',
    '#bsoVault.bv-granted .bv-dial{transform:rotate(90deg)}',
    '#bsoVault .bv-icon{width:54px;height:54px;border-radius:15px;display:grid;place-items:center;margin-bottom:12px;background:#1a1810;border:1px solid rgba(255,214,51,.4);box-shadow:0 4px 12px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.08)}',
    '#bsoVault .bv-icon svg{width:28px;height:28px}',
    '#bsoVault .bv-name{font-family:Orbitron,"Arial Black",sans-serif;font-weight:900;font-size:clamp(24px,3vw,34px);letter-spacing:.03em;line-height:1.1;color:#ffd633}',
    '#bsoVault .bv-sub{font-size:clamp(16px,1.5vw,19px);font-weight:600;color:#8a90b8;letter-spacing:.02em}',
    // the pill where the card has its Enter button: what the vault is doing, and six lamps
    '#bsoVault .bv-pill{margin-top:16px;align-self:flex-start;display:inline-flex;align-items:center;gap:12px;padding:10px 16px 10px 20px;border-radius:999px;',
    '  font-family:Orbitron,"Arial Black",sans-serif;font-weight:700;font-size:12.5px;letter-spacing:.16em;text-transform:uppercase;color:#05060c;white-space:nowrap;',
    '  background:linear-gradient(135deg,#ffe680,#ffd633);box-shadow:0 4px 12px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.5),inset 0 -2px 0 rgba(0,0,0,.14)}',
    '#bsoVault .bv-msg{min-width:0;overflow:hidden;text-overflow:ellipsis}',
    '#bsoVault .bv-leds{display:flex;gap:5px}',
    '#bsoVault .bv-leds i{width:7px;height:7px;border-radius:50%;background:rgba(5,6,12,.22);box-shadow:inset 0 1px 1px rgba(0,0,0,.25);transition:background .15s}',
    '#bsoVault .bv-leds i.ok{background:#05060c}',
    '#bsoVault.bv-sync .bv-msg{animation:bvPulse 1.4s ease-in-out infinite}',
    '@keyframes bvPulse{0%,100%{opacity:.5}50%{opacity:1}}',
    // what spills out of the vault: a game, music and chat, as on the front page
    '#bsoVault .bv-fan{position:absolute;right:21%;top:21%;width:0;height:0;z-index:0}',
    '#bsoVault .bv-fc{position:absolute;width:52px;height:64px;left:-26px;top:-32px;border-radius:12px;display:grid;place-items:center;',
    '  background:linear-gradient(160deg,#11131f,#0a0b14);border:1px solid var(--c);box-shadow:0 8px 18px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.07);',
    '  opacity:0;transform:scale(.5);transition:transform .7s cubic-bezier(.34,1.56,.64,1) var(--dl),opacity .35s ease var(--dl)}',
    '#bsoVault .bv-fc svg{width:26px;height:26px}',
    '#bsoVault.bv-granted .bv-fc{opacity:1;transform:translate(var(--tx),var(--ty)) rotate(var(--r)) scale(1)}',
    '#bsoVault .bso-skip{position:absolute;left:0;right:0;bottom:max(20px,env(safe-area-inset-bottom));text-align:center;font-family:"Share Tech Mono",ui-monospace,monospace;',
    '  font-size:11px;letter-spacing:.3em;color:#3d4256;opacity:0;animation:bvFade .6s ease-out 1.2s forwards}',
    '#bsoVault.bv-quick .bso-skip,#bsoVault.bv-through .bso-skip{display:none}',
    '@keyframes bvFade{to{opacity:1}}',
    '@media (max-width:560px){#bsoVault .bv-card{width:88vw;padding:24px 22px 22px}#bsoVault .bv-idx{left:22px;top:18px}}'
  ].join('\n');

  O.vault = function (o) {
    var host = o.host || document;
    css(host, 'bso-vault-css', VAULT_CSS);
    var G = '#ffd633';
    var R = Run(o, 'bsoVault',
      '<div class="bv-bg"></div>' +
      '<div class="bv-card">' +
        '<div class="bv-art"><svg viewBox="0 0 200 200" fill="none" stroke="' + G + '">' +
          '<circle cx="100" cy="100" r="92" stroke-opacity=".22" stroke-width="2"/>' +
          '<circle class="bv-ring" cx="100" cy="100" r="74" stroke-opacity=".3" stroke-width="6" stroke-dasharray="4 10"/>' +
          '<g class="bv-dial"><g class="bv-dial-in">' +
            '<circle cx="100" cy="100" r="46" stroke-opacity=".45" stroke-width="3"/>' +
            '<path d="M100 54v92M54 100h92M67.5 67.5l65 65M132.5 67.5l-65 65" stroke-opacity=".36" stroke-width="3" stroke-linecap="round"/>' +
            '<circle cx="100" cy="100" r="14" stroke-opacity=".6" stroke-width="4"/>' +
          '</g></g></svg></div>' +
        '<div class="bv-fan">' +
          '<span class="bv-fc" style="--c:rgba(255,214,51,.55);--tx:-170px;--ty:30px;--r:-16deg;--dl:.04s"><svg viewBox="0 0 24 24" fill="none" stroke="#ffd633" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 8h11a4 4 0 0 1 3.9 4.9l-1 4.4a2.2 2.2 0 0 1-3.8 1l-2.1-2.3H9.5l-2.1 2.3a2.2 2.2 0 0 1-3.8-1l-1-4.4A4 4 0 0 1 6.5 8Z"/><path d="M8 11v3M6.5 12.5h3"/><circle cx="15.5" cy="11.6" r=".6" fill="#ffd633"/><circle cx="17.2" cy="13.4" r=".6" fill="#ffd633"/></svg></span>' +
          '<span class="bv-fc" style="--c:rgba(255,45,120,.55);--tx:-122px;--ty:88px;--r:-5deg;--dl:.1s"><svg viewBox="0 0 24 24" fill="none" stroke="#ff2d78" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5.5l11-2v12.5"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/></svg></span>' +
          '<span class="bv-fc" style="--c:rgba(34,230,255,.55);--tx:-62px;--ty:128px;--r:9deg;--dl:.16s"><svg viewBox="0 0 24 24" fill="none" stroke="#22e6ff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5.5h16v10H10l-4.5 3.5v-3.5H4Z"/><path d="M8 10.5h.01M12 10.5h.01M16 10.5h.01"/></svg></span>' +
        '</div>' +
        '<div class="bv-idx">01</div>' +
        '<div class="bv-icon"><svg viewBox="0 0 24 24" fill="none" stroke="' + G + '" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="12" cy="12" r="4.2"/><path d="M12 7.8v1.4M12 14.8v1.4M7.8 12h1.4M14.8 12h1.4"/><path d="M6.5 20v1.5M17.5 20v1.5"/></svg></div>' +
        '<div class="bv-name">Bee\'s Vault</div>' +
        '<div class="bv-sub">Games, apps, links &amp; chat</div>' +
        '<div class="bv-pill"><span class="bv-msg">Bee\'s Vault</span><span class="bv-leds"><i></i><i></i><i></i><i></i><i></i><i></i></span></div>' +
      '</div>' +
      '<div class="bso-skip"></div>');
    var el = R.el, win = R.win, doc = R.doc, SN = R.SN;
    var card = el.querySelector('.bv-card'), dialIn = el.querySelector('.bv-dial-in'), msg = el.querySelector('.bv-msg'), leds = el.querySelectorAll('.bv-leds i');
    if (R.quick) el.classList.add('bv-quick');
    var who = '';
    try { who = (win.localStorage.getItem('player-name') || '').replace(/\s+/g, ' ').trim().slice(0, 16).toUpperCase(); } catch (e) {}
    function setMsg(m) { msg.textContent = m; }
    function cardX() { var r = card.getBoundingClientRect(); return (r.left + r.width * 0.79) / (win.innerWidth || 1) * 1.6 - 0.8; }

    // ── its sound
    var hum = null;
    function live() { return R.live(); }
    function sDive() {
      if (!live()) return;
      SN.noise({ f: 180, f2: 2600, dur: 0.8, vol: 0.045, q: 0.8, atk: 0.5, wet: 0.4 });
      SN.tone({ f: 70, f2: 150, dur: 0.8, vol: 0.04, atk: 0.4, wet: 0.3 });
    }
    function sArrive() {
      if (!live()) return;
      SN.tone({ f: 56, f2: 30, dur: 0.9, vol: 0.26 });
      SN.noise({ f: 500, f2: 90, dur: 0.6, vol: 0.1, ft: 'lowpass', wet: 0.5 });
      SN.bell({ f: 146.83, ratio: 2.4, index: 3, dur: 2.4, vol: 0.05, wet: 0.7 });
      SN.bell({ at: 0.02, f: 220, ratio: 1.8, index: 2, dur: 1.8, vol: 0.02, wet: 0.7 });
      hum = SN.drone({ fs: [55, 110, 165.5], type: 'sawtooth', vol: 0.016, cut: 150, cut2: 320, rise: 1, wet: 0.3 });
    }
    function sTick(p) {
      if (!live()) return;
      SN.noise({ f: 3600, dur: 0.018, vol: 0.04, q: 6, pan: p, wet: 0.1 });
      SN.bell({ f: 2300, ratio: 1.41, index: 0.8, dur: 0.1, vol: 0.006, pan: p, wet: 0.2 });
    }
    var CHIME = [523.25, 587.33, 659.25, 783.99, 880, 1046.5];
    function sLock(k, p) {
      if (!live()) return;
      SN.noise({ f: 1600, f2: 480, dur: 0.09, vol: 0.1, q: 1.5, pan: p, wet: 0.2 });
      SN.tone({ f: 150, f2: 70, dur: 0.12, vol: 0.1, type: 'square', cut: 700, pan: p });
      SN.bell({ at: 0.03, f: CHIME[k], ratio: 3.01, index: 1.1, dur: 1.1, vol: 0.03, pan: p, wet: 0.6 });
    }
    function sGranted() {
      if (!live()) return;
      SN.chord([659.26, 830.61, 987.77, 1318.51], { bell: true, dur: 1.8, vol: 0.028, spread: 0.06, ratio: 3.01, index: 1 });
      SN.noise({ at: 0.1, f: 4000, f2: 9000, dur: 0.6, vol: 0.015, q: 2, atk: 0.2, wet: 0.5 });
    }
    function sOpen() {
      if (!live()) return;
      SN.tone({ type: 'sawtooth', f: 90, f2: 260, dur: 0.8, vol: 0.03, cut: 600, cut2: 2200, vib: [18, 10], wet: 0.4 });
      SN.tone({ f: 48, f2: 34, dur: 1, vol: 0.14, type: 'sawtooth', cut: 150 });
      SN.chord([523.25, 659.25, 783.99, 987.77], { at: 0.2, dur: 2, vol: 0.018, atk: 0.5, wet: 0.9, spread: 0.08 });
      if (hum) { hum.stop(1.1); hum = null; }
    }
    function sThrough() {
      if (!live()) return;
      SN.noise({ f: 400, f2: 3000, dur: 0.8, vol: 0.055, q: 0.9, atk: 0.3, wet: 0.5 });
      SN.chord([523.25, 783.99, 1046.5, 1567.98], { bell: true, at: 0.2, dur: 1.6, vol: 0.012, spread: 0.05, ratio: 2, index: 0.6 });
    }

    // ── the card comes forward: out of its place on the front page if it is there
    function enter(ms) {
      var from = null;
      try {
        var door = doc.querySelector('.door.vault'), r = door && door.getBoundingClientRect();
        if (r && r.width > 60 && r.height > 60 && r.bottom > 0 && r.top < win.innerHeight) from = r;
      } catch (e) {}
      var to = card.getBoundingClientRect();
      card.style.transition = 'none';
      if (from && to.width) {
        var dx = (from.left + from.width / 2) - (to.left + to.width / 2), dy = (from.top + from.height / 2) - (to.top + to.height / 2);
        card.style.transform = 'translate(' + dx + 'px,' + dy + 'px) scale(' + (from.width / to.width) + ',' + (from.height / to.height) + ')';
        card.style.opacity = '1';
      } else {
        card.style.transform = 'translateY(24px) scale(.92)';
        card.style.opacity = '0';
      }
      void card.offsetWidth;
      card.style.transition = 'transform ' + ms + 'ms cubic-bezier(.16,1,.3,1), opacity ' + Math.round(ms * 0.6) + 'ms ease';
      card.style.transform = 'none';
      card.style.opacity = '1';
      el.classList.add('bv-on');
    }

    // ── the steps
    var P = R.quick ? { enter: 380, arrive: 200, lock0: 320, lockStep: 75, open: 220, through: 380 }
                    : { enter: 750, arrive: 720, lock0: 1000, lockStep: 210, open: 520, through: 560 };
    var ANG = [52, -31, 96, -64, 138, 0];
    var lockT = [], done = 0, opened = false, sync = null;
    function arrive() {
      el.classList.add('bv-named');
      setMsg('Unlocking');
      sArrive();
    }
    function lock(k) {
      if (R.over || leds[k].className === 'ok') return;
      dialIn.style.transform = 'rotate(' + ANG[k] + 'deg)';
      leds[k].className = 'ok';
      sLock(k, cardX());
      done++;
      if (done === 6) R.later(waitReady, 150);
    }
    function schedule(from) {
      lockT.forEach(clearTimeout); lockT = [];
      for (var k = 0; k < 6; k++) (function (k) { lockT.push(R.later(function () { lock(k); }, from + k * P.lockStep)); })(k);
    }
    function waitReady() {
      if (!R.ready()) {
        el.classList.add('bv-sync'); setMsg('Syncing the vault');
        var a = 0; sync = win.setInterval(function () { a += 30; dialIn.style.transform = 'rotate(' + a + 'deg)'; sTick(cardX()); }, 260);
      }
      R.whenReady(granted, 15000);
    }
    function granted() {
      if (sync) { win.clearInterval(sync); sync = null; }
      el.classList.remove('bv-sync'); el.classList.add('bv-granted');
      for (var k = 0; k < 6; k++) leds[k].className = 'ok';
      dialIn.style.transform = 'rotate(0deg)';
      setMsg(who ? 'Welcome back, ' + who : 'Access granted');
      sGranted();
      if (!R.calm) R.later(openUp, P.open + 260);
    }
    // the card swings past you, into the vault, as the vault shows through
    function openUp() {
      if (opened) return; opened = true;
      sOpen();
      card.style.transition = 'transform .32s cubic-bezier(.16,1,.3,1)';
      card.style.transform = 'scale(1.035)';
      R.later(function () {
        el.classList.add('bv-through');
        sThrough();
        R.reveal();
        card.style.transition = 'transform .85s cubic-bezier(.55,0,.8,.2), opacity .6s ease .2s';
        card.style.transform = 'perspective(900px) rotateX(10deg) scale(4.2)';
        card.style.opacity = '0';
        el.classList.add('out');
        R.later(R.end, 1000);
      }, P.through);
    }
    R.onSkip(function () {
      if (R.calm || opened || el.classList.contains('bv-granted')) return;
      // straight to the unlock (still waiting for the vault, if it is not here yet)
      if (!el.classList.contains('bv-named')) arrive();
      P.lockStep = 50;
      schedule(0);
    });

    if (R.calm) {
      card.style.opacity = '1'; el.classList.add('bv-on', 'bv-named');
      setMsg('Unlocking');
      R.whenReady(function () { granted(); R.later(function () { R.reveal(); el.classList.add('out'); R.later(R.end, 900); }, 700); }, 15000);
      return R.api;
    }
    win.requestAnimationFrame(function () {
      enter(P.enter);
      if (!R.quick) sDive();
      R.later(arrive, P.arrive);
      schedule(P.lock0);
    });
    return R.api;
  };

  // ════════════════════════════════════════════════════════════════════
  //  NEON SIEGE 2: the cabinet boots, the camera races over a 3D neon grid
  //  with towers streaming past and shooting down drones, the logo slams in
  //  extruded like chrome, the neon catches and the flight jumps to warp
  //  under a lens flare, and the logo flies onto the title screen's own.
  // ════════════════════════════════════════════════════════════════════
  var NS_CSS = [
    '#nsIntro{position:fixed;inset:0;z-index:2147483000;overflow:hidden;background:#02030a;cursor:pointer;color:#fff;',
    '  font-family:var(--f1,"Orbitron"),system-ui,sans-serif;-webkit-user-select:none;user-select:none;touch-action:none;animation:bsoFailsafe .3s linear 30s forwards}',
    '@keyframes bsoFailsafe{to{opacity:0;visibility:hidden;pointer-events:none}}',
    '#nsIntro>*{position:absolute}',
    '.nsi-bg{inset:0}',
    '.nsi-go .nsi-bg{animation:nsiFade .9s ease-out .22s both}',
    '.nsi-fly .nsi-bg{animation:nsiOut .5s ease forwards}',
    '@keyframes nsiOut{from{opacity:1}to{opacity:0}}',
    '.nsi-fly{background:transparent!important;transition:background-color .5s ease}',
    '.nsi-stars{position:absolute;inset:0 0 40% 0;opacity:.7;',
    '  background-image:radial-gradient(1.2px 1.2px at 22px 38px,#fff,transparent),radial-gradient(1px 1px at 132px 84px,#9ff,transparent),',
    '    radial-gradient(1.4px 1.4px at 88px 150px,#fff,transparent),radial-gradient(1px 1px at 190px 22px,#fcf,transparent),',
    '    radial-gradient(1px 1px at 58px 196px,#fff,transparent),radial-gradient(1.2px 1.2px at 172px 176px,#bff,transparent);',
    '  background-size:220px 220px;-webkit-mask-image:linear-gradient(#000,transparent);mask-image:linear-gradient(#000,transparent)}',
    '.nsi-go .nsi-stars{animation:nsiTwinkle 2.4s ease-in-out infinite alternate}',
    '@keyframes nsiTwinkle{to{opacity:.35}}',
    '.nsi-sun{position:absolute;left:50%;top:63%;width:min(50vmin,420px);aspect-ratio:1/1;border-radius:50%;opacity:.95;transform:translate(-50%,-56%);',
    '  background:linear-gradient(180deg,#ffe66d 0%,#ffb03a 30%,#ff2d9b 66%,#b46bff 100%);',
    '  -webkit-mask-image:linear-gradient(180deg,#000 0 27%,transparent 27% 28.6%,#000 28.6% 33%,transparent 33% 35.4%,#000 35.4% 40%,transparent 40% 43.2%,#000 43.2% 47.5%,transparent 47.5% 51.5%,#000 51.5%);',
    '          mask-image:linear-gradient(180deg,#000 0 27%,transparent 27% 28.6%,#000 28.6% 33%,transparent 33% 35.4%,#000 35.4% 40%,transparent 40% 43.2%,#000 43.2% 47.5%,transparent 47.5% 51.5%,#000 51.5%)}',
    '.nsi-go .nsi-sun{animation:nsiSun 1.6s cubic-bezier(.16,1,.3,1) .3s both}',
    '@keyframes nsiSun{from{transform:translate(-50%,-14%);opacity:0}}',
    '.nsi-horizon{position:absolute;left:0;right:0;top:63%;height:2px;margin-top:-1px;',
    '  background:linear-gradient(90deg,transparent,#ff2d9b 25%,#fff 50%,#22e6ff 75%,transparent);',
    '  box-shadow:0 0 18px 3px rgba(255,45,155,.55),0 0 60px 10px rgba(34,230,255,.18)}',
    '.nsi-scan{position:absolute;inset:0;background:repeating-linear-gradient(0deg,rgba(0,0,0,.28) 0 1px,transparent 1px 3px);pointer-events:none}',
    '.nsi-vig{position:absolute;inset:0;background:radial-gradient(ellipse 80% 75% at 50% 45%,transparent 50%,rgba(0,0,0,.75))}',
    '.nsi-cv{position:absolute;inset:0;width:100%;height:100%;display:block}',
    '.nsi-crt{inset:0;background:radial-gradient(ellipse at center,#fff 0%,#bff 30%,#22e6ff 70%);opacity:0;transform:scale(0,.004)}',
    '.nsi-go .nsi-crt{animation:nsiCrt .5s cubic-bezier(.3,0,.2,1) both}',
    '@keyframes nsiCrt{0%{opacity:1;transform:scale(0,.004)}38%{opacity:1;transform:scale(1,.004)}62%{opacity:.85;transform:scale(1,1)}100%{opacity:0;transform:scale(1,1)}}',
    '.nsi-presents{left:0;right:0;top:29%;text-align:center;font-weight:700;font-size:clamp(10px,1.6vw,14px);letter-spacing:.5em;padding-left:.5em;color:#7b96b8;opacity:0}',
    '.nsi-presents b{color:#ffd633;font-weight:700}',
    '.nsi-presents span{display:inline-block;clip-path:inset(0 100% 0 0)}',
    '.nsi-go .nsi-presents{animation:nsiPres 1.25s ease both .4s}',
    '.nsi-go .nsi-presents span{animation:nsiType .55s steps(24,end) .45s both}',
    '@keyframes nsiPres{0%{opacity:1}75%{opacity:1;transform:none}100%{opacity:0;transform:translateY(-10px)}}',
    '@keyframes nsiType{to{clip-path:inset(0 0 0 0)}}',
    '.nsi-logo{left:50%;top:36%;font-weight:900;font-size:clamp(32px,6.2vw,74px);letter-spacing:.09em;line-height:.95;text-align:center;white-space:nowrap;',
    '  transform:translate(-50%,-50%) scale(var(--k,1.3));transform-origin:50% 50%}',
    '.nsi-logo::before{content:"";position:absolute;left:-30%;right:-30%;top:-45%;bottom:-45%;z-index:-1;',
    '  background:radial-gradient(ellipse at center,rgba(2,3,10,.6) 25%,transparent 68%)}',
    '.nsi-word{display:block}',
    '.nsi-word+.nsi-word{position:absolute;left:0;top:0;right:0}',
    '.nsi-ch{display:inline-block;opacity:0}',
    '.nsi-g .nsi-ch{background:linear-gradient(180deg,#ffffff 8%,#22e6ff 56%,#ff2d9b 118%);-webkit-background-clip:text;background-clip:text;color:transparent}',
    '.nsi-m{color:#ff2d9b;mix-blend-mode:screen}',
    '.nsi-c{color:#22e6ff;mix-blend-mode:screen}',
    '.nsi-slam .nsi-ch{animation:nsiSlam .5s cubic-bezier(.2,.9,.25,1.25) calc(var(--i)*var(--st,55ms)) both}',
    '@keyframes nsiSlam{0%{opacity:0;transform:translateY(-.3em) scale(2.6)}55%{opacity:1;transform:scale(.9)}100%{opacity:1;transform:none}}',
    '.nsi-slam .nsi-m{animation:nsiCaM calc(var(--st,55ms)*10 + .7s) ease-out both}',
    '.nsi-slam .nsi-c{animation:nsiCaC calc(var(--st,55ms)*10 + .7s) ease-out both}',
    '@keyframes nsiCaM{0%{transform:translate(-.14em,.03em) skewX(-10deg);opacity:.95}70%{transform:translate(-.05em,0);opacity:.7}100%{transform:none;opacity:0}}',
    '@keyframes nsiCaC{0%{transform:translate(.14em,-.03em) skewX(10deg);opacity:.95}70%{transform:translate(.05em,0);opacity:.7}100%{transform:none;opacity:0}}',
    '.nsi-logo b{display:block;font-size:.34em;letter-spacing:.62em;color:#ff2d9b;margin-top:6px;opacity:0;text-shadow:0 0 14px rgba(255,45,155,.7)}',
    '.nsi-lit b{animation:nsiNeon .6s steps(1,end) both}',
    '@keyframes nsiNeon{0%{opacity:0}12%{opacity:1}20%{opacity:.15}32%{opacity:1}44%{opacity:.35}52%,100%{opacity:1}}',
    '.nsi-beam{position:absolute;top:-20%;bottom:-20%;left:0;width:22%;opacity:0;pointer-events:none;',
    '  background:linear-gradient(90deg,transparent,rgba(255,255,255,.85),transparent);transform:translateX(-120%) skewX(-18deg);mix-blend-mode:overlay}',
    '.nsi-sweep .nsi-beam{animation:nsiBeam .55s cubic-bezier(.5,0,.3,1) both}',
    '@keyframes nsiBeam{0%{opacity:0;transform:translateX(-120%) skewX(-18deg)}15%{opacity:1}100%{opacity:0;transform:translateX(560%) skewX(-18deg)}}',
    '.nsi-shock{left:50%;top:36%;width:40vmin;height:40vmin;margin:-20vmin 0 0 -20vmin;border-radius:50%;border:3px solid #22e6ff;opacity:0;',
    '  box-shadow:0 0 30px rgba(34,230,255,.6),inset 0 0 30px rgba(255,45,155,.4)}',
    '.nsi-shockgo .nsi-shock{animation:nsiShock .7s cubic-bezier(.16,1,.3,1) both}',
    '@keyframes nsiShock{0%{opacity:.95;transform:scale(.2)}100%{opacity:0;transform:scale(3.2)}}',
    '.nsi-shake{animation:nsiShake .32s steps(8,end)}',
    '@keyframes nsiShake{0%{transform:translate(6px,-4px)}25%{transform:translate(-5px,3px)}50%{transform:translate(4px,4px)}75%{transform:translate(-3px,-2px)}100%{transform:none}}',
    '#nsIntro .bso-skip{left:0;right:0;bottom:max(18px,env(safe-area-inset-bottom));text-align:center;font-size:10px;letter-spacing:.34em;color:#3d5674;opacity:0}',
    '.nsi-go .bso-skip{animation:nsiFade .6s ease 1.2s both}',
    '.nsi-fly .bso-skip,.nsi-quick .bso-skip{display:none}',
    '@keyframes nsiFade{from{opacity:0}}',
    '.nsi-boot{left:max(18px,4vw);top:max(16px,5vh);font:600 clamp(10px,1.2vw,13px)/1.7 ui-monospace,Consolas,"Courier New",monospace;letter-spacing:.08em;color:#6fe9ff;',
    '  text-shadow:0 0 8px rgba(34,230,255,.6);white-space:pre;pointer-events:none}',
    '.nsi-boot b{color:#ff2d9b;font-weight:600;text-shadow:0 0 8px rgba(255,45,155,.7)}',
    '.nsi-boot i{font-style:normal;color:#5cff9d;text-shadow:0 0 8px rgba(92,255,157,.7)}',
    '.nsi-bootx .nsi-boot{animation:nsiBootOut .42s steps(1,end) forwards}',
    '@keyframes nsiBootOut{0%{transform:translateX(6px) skewX(-12deg);color:#ff2d9b}25%{transform:translateX(-8px);opacity:.4}50%{clip-path:inset(0 0 55% 0);transform:none;opacity:1}75%{clip-path:inset(50% 0 0 0);transform:translateX(10px)}100%{opacity:0}}',
    /* the letters extruded like chrome: the word again, underneath (it is the one in the flow, so it paints below the others) */
    '.nsi-x .nsi-ch{color:#2a0838;text-shadow:0 0 0 #d4238f,0 0 0 #b31d82,0 0 0 #921874,0 0 0 #731366,0 0 0 #560f58,0 0 0 #3a0a47,0 0 0 rgba(0,0,0,0);transition:text-shadow .45s cubic-bezier(.16,1,.3,1)}',
    '.nsi-lit .nsi-x .nsi-ch{text-shadow:0 1px 0 #d4238f,0 2px 0 #b31d82,0 3px 0 #921874,0 4px 0 #731366,0 5px 0 #560f58,0 6px 0 #3a0a47,0 13px 24px rgba(0,0,0,.7)}',
    '.nsi-fly .nsi-x{opacity:0;transition:opacity .3s ease}',
    '.nsi-flare{left:0;right:0;top:36%;height:0;pointer-events:none}',
    '.nsi-flare::before{content:"";position:absolute;left:-10%;right:-10%;top:-2px;height:4px;border-radius:4px;opacity:0;transform:scaleX(0);',
    '  background:linear-gradient(90deg,transparent,rgba(34,230,255,.55) 25%,#fff 50%,rgba(255,45,155,.55) 75%,transparent);box-shadow:0 0 18px 4px rgba(120,230,255,.45)}',
    '.nsi-flare::after{content:"";position:absolute;left:50%;top:-90px;width:180px;height:180px;margin-left:-90px;border-radius:50%;opacity:0;',
    '  background:radial-gradient(circle,rgba(255,255,255,.85),rgba(120,230,255,.35) 30%,transparent 65%)}',
    '.nsi-flareon .nsi-flare::before{animation:nsiStreak .95s cubic-bezier(.16,1,.3,1) forwards}',
    '.nsi-flareon .nsi-flare::after{animation:nsiBloom .7s ease-out forwards}',
    '@keyframes nsiStreak{0%{opacity:1;transform:scaleX(0)}35%{opacity:1;transform:scaleX(1)}100%{opacity:0;transform:scaleX(1.12)}}',
    '@keyframes nsiBloom{0%{opacity:0;transform:scale(.4)}20%{opacity:1}100%{opacity:0;transform:scale(1.7)}}',
    '.nsi-calm .nsi-boot,.nsi-calm .nsi-flare{display:none}',
    '.nsi-calm .nsi-x{visibility:hidden}',
    '.nsi-calm .nsi-ch,.nsi-calm .nsi-logo b{opacity:1}',
    '.nsi-calm .nsi-m,.nsi-calm .nsi-c,.nsi-calm .nsi-beam,.nsi-calm .nsi-shock{display:none}',
    '.nsi-calm .nsi-logo{animation:nsiFade .5s ease both}'
  ].join('\n');
  // on the title screen: hide its logo while the opening plays, then the title screen rises in behind ours as it lands
  var NS_TARGET_CSS = [
    'html.nsi-on #logo,html.nsi-on #toBeeside{opacity:0}',
    'html.nsi-land #logo{transition:opacity .22s ease}',
    '#titleBox.nsi-reveal>:not(#logo){animation:nsiRise .75s cubic-bezier(.16,1,.3,1) both}',
    '#titleBox.nsi-reveal>:nth-child(2){animation-delay:.05s}#titleBox.nsi-reveal>:nth-child(3){animation-delay:.12s}',
    '#titleBox.nsi-reveal>:nth-child(4){animation-delay:.17s}#titleBox.nsi-reveal>:nth-child(5){animation-delay:.2s}',
    '#titleBox.nsi-reveal>:nth-child(6){animation-delay:.25s}#titleBox.nsi-reveal>:nth-child(7){animation-delay:.3s}',
    '#titleBox.nsi-reveal>:nth-child(8){animation-delay:.34s}#titleBox.nsi-reveal>:nth-child(n+9){animation-delay:.38s}',
    '@keyframes nsiRise{from{opacity:0;transform:translateY(26px)}}',
    '@media (prefers-reduced-motion:reduce){#titleBox.nsi-reveal>:not(#logo){animation:none!important}}'
  ].join('\n');

  O['neon-siege'] = function (o) {
    var host = o.host || document;
    css(host, 'bso-ns-css', NS_CSS);
    var R = Run(o, 'nsIntro',
      '<div class="nsi-bg"><div class="nsi-stars"></div><div class="nsi-sun"></div><canvas class="nsi-cv"></canvas><div class="nsi-horizon"></div><div class="nsi-vig"></div><div class="nsi-scan"></div></div>' +
      '<div class="nsi-crt"></div><div class="nsi-boot"></div>' +
      '<div class="nsi-presents"><span><b>BEESIDE STUDIO\'S</b> PRESENTS</span></div>' +
      '<div class="nsi-logo"><div class="nsi-word nsi-x" aria-hidden="true">NEON SIEGE</div><div class="nsi-word nsi-g">NEON SIEGE</div><div class="nsi-word nsi-m">NEON SIEGE</div><div class="nsi-word nsi-c">NEON SIEGE</div><b>II</b><div class="nsi-beam"></div></div>' +
      '<div class="nsi-shock"></div><div class="nsi-flare"></div><div class="bso-skip"></div>');
    var el = R.el, win = R.win, doc = R.doc, SN = R.SN, quick = R.quick, calm = R.calm, later = R.later;
    if (quick) el.classList.add('nsi-quick');
    // each word as letters, the same in every layer
    [].forEach.call(el.querySelectorAll('.nsi-word'), function (w) {
      var text = w.textContent; w.textContent = '';
      for (var i = 0; i < text.length; i++) {
        var c = doc.createElement('span'); c.className = 'nsi-ch'; c.style.setProperty('--i', i);
        c.textContent = text[i] === ' ' ? ' ' : text[i]; w.appendChild(c);
      }
    });
    var logo = el.querySelector('.nsi-logo'), pad = null, hum = null;
    function live() { return R.live(); }
    function sCrt() {
      if (!live()) return;
      SN.tone({ f: 60, f2: 38, dur: 0.35, vol: 0.2, type: 'sawtooth', cut: 280 });
      SN.noise({ f: 6000, f2: 2500, dur: 0.35, vol: 0.05, ft: 'highpass', wet: 0.3 });
      SN.tone({ f: 9800, dur: 0.7, vol: 0.004, atk: 0.05 });
      SN.tone({ at: 0.05, f: 190, f2: 70, dur: 0.55, vol: 0.05, vib: [28, 22], wet: 0.4 });
      for (var k = 0; k < 6; k++) SN.bell({ at: 0.3 + Math.random() * 0.9, f: 1800 + Math.random() * 2400, ratio: 2, index: 0.6, dur: 0.9, vol: 0.006, pan: Math.random() * 1.6 - 0.8, wet: 0.8 });
    }
    function sPad() {
      if (!live()) return;
      pad = SN.drone({ fs: [110, 220, 261.63, 329.63, 493.88], vol: 0.04, rise: 1.4, cut: 250, cut2: 2200, wet: 0.6 });
      SN.noise({ f: 300, f2: 3000, dur: 1.4, vol: 0.02, atk: 1.2, wet: 0.5 });
      var sp = 0.105;
      for (var k = 0; k < (quick ? 6 : 16); k++) {
        SN.tone({ at: k * sp, f: [55, 55, 110, 55][k % 4], dur: sp * 0.9, vol: 0.05, type: 'sawtooth', cut: 500 + k * 60, q: 4 });
        if (k % 2) SN.noise({ at: k * sp, f: 8000, dur: 0.03, vol: 0.012, ft: 'highpass' });
      }
    }
    function sType() { if (!live()) return; for (var k = 0; k < 12; k++) SN.tone({ at: k * 0.046, f: 1900 + (k % 3) * 120 + Math.random() * 60, dur: 0.02, vol: 0.016, type: 'square', cut: 4500, pan: -0.3 + k * 0.05, wet: 0.15 }); }
    function sSlam() {
      if (!live()) return;
      var st = parseFloat(win.getComputedStyle(logo).getPropertyValue('--st')) || 55;
      for (var k = 0; k < 10; k++) {
        if (k === 4) continue;
        var at = k * st / 1000 + 0.2, p = -0.7 + k * 0.155;
        SN.tone({ at: at, f: 170, f2: 52, dur: 0.14, vol: 0.13, pan: p });
        SN.noise({ at: at, f: 2600, f2: 1200, dur: 0.05, vol: 0.05, pan: p, wet: 0.2 });
      }
      SN.tone({ at: 10 * st / 1000 + 0.25, f: 120, f2: 40, dur: 0.3, vol: 0.18, pan: 0.5 });
      for (var j = 0; j < 3; j++) SN.tone({ at: 0.15 + j * 0.09 + Math.random() * 0.05, f: 3000 + Math.random() * 2000, f2: 200, dur: 0.05, vol: 0.02, type: 'square', cut: 6000, pan: Math.random() * 1.2 - 0.6 });
    }
    function sLit() {
      if (!live()) return;
      SN.tone({ f: 120, f2: 30, dur: 0.7, vol: 0.3 });
      SN.noise({ f: 6000, f2: 1500, dur: 1.1, vol: 0.09, ft: 'highpass', q: 0.6, wet: 0.6 });
      SN.noise({ f: 150, f2: 1800, dur: 0.6, vol: 0.06, ft: 'lowpass', wet: 0.4 });
      SN.noise({ f: 90, dur: 0.45, vol: 0.08, ft: 'lowpass' });
      hum = SN.drone({ fs: [120, 240], vol: 0.03, rise: 0.02, cut: 1400, wet: 0.2 });
      if (hum) { var t = SN.now(); [[0.07, 0.03], [0.12, 0.004], [0.19, 0.03], [0.26, 0.008], [0.31, 0.03], [0.7, 0.012]].forEach(function (p) { hum.g.gain.setValueAtTime(p[1], t + p[0]); }); }
      if (pad) pad.f.frequency.setTargetAtTime(3200, SN.now(), 0.2);
    }
    function sSweep() { if (!live()) return; SN.noise({ f: 2500, f2: 9000, dur: 0.4, vol: 0.06, q: 3, pan: -0.6, wet: 0.4 }); SN.tone({ f: 1760, f2: 3520, dur: 0.35, vol: 0.018, wet: 0.5 }); SN.bell({ at: 0.2, f: 2637.02, ratio: 2, index: 0.8, dur: 1, vol: 0.012, pan: 0.6 }); }
    function sPost() { if (!live()) return; SN.tone({ f: 1046.5, dur: 0.14, vol: 0.022, type: 'square', cut: 3200, wet: 0.2 }); }
    function sBootLine(k) { if (!live()) return; SN.tone({ f: 1760 + k * 90, dur: 0.025, vol: 0.012, type: 'square', cut: 5000, pan: -0.5, wet: 0.1 }); SN.tone({ at: 0.06, f: 2640, dur: 0.02, vol: 0.008, type: 'square', cut: 6000, pan: -0.5 }); }
    function sBootOut() { if (!live()) return; SN.tone({ f: 3200, f2: 180, dur: 0.18, vol: 0.02, type: 'sawtooth', cut: 5000, pan: -0.4 }); SN.noise({ f: 4000, dur: 0.12, vol: 0.03, ft: 'highpass', pan: -0.4 }); }
    var fxAt = {};
    function fxOk(k, gap) { var n = SN ? SN.now() : 0; if (n - (fxAt[k] || -9) < gap) return false; fxAt[k] = n; return true; }
    function sPass(side) { if (!live() || !fxOk('pass', 0.12)) return; SN.noise({ f: 500, f2: 2600, dur: 0.26, vol: 0.022, q: 1, atk: 0.08, pan: side * 0.8, wet: 0.15 }); }
    function sZap(p) { if (!live() || !fxOk('zap', 0.07)) return; SN.tone({ f: 1500 + Math.random() * 400, f2: 420, dur: 0.07, vol: 0.011, type: 'square', cut: 4200, pan: p, wet: 0.2 }); }
    function sPop(p) { if (!live() || !fxOk('pop', 0.06)) return; SN.noise({ f: 1400, f2: 250, dur: 0.12, vol: 0.03, pan: p, wet: 0.3 }); SN.tone({ f: 330, f2: 80, dur: 0.12, vol: 0.02, type: 'square', cut: 1800, pan: p }); }
    function sWarp() {
      if (!live()) return;
      SN.noise({ f: 200, f2: 7000, dur: 0.55, vol: 0.06, q: 0.8, atk: 0.25, wet: 0.4 });
      SN.tone({ f: 110, f2: 38, dur: 0.9, vol: 0.12 });
      SN.bell({ at: 0.1, f: 2637.02, ratio: 2, index: 0.9, dur: 1.4, vol: 0.012, pan: 0.3 });
      SN.bell({ at: 0.16, f: 3520, ratio: 2, index: 0.7, dur: 1.2, vol: 0.008, pan: -0.3 });
    }
    function sFly() {
      if (!live()) return;
      SN.noise({ f: 3000, f2: 350, dur: 0.55, vol: 0.08, q: 1.2, wet: 0.4 });
      SN.tone({ at: 0.45, f: 90, f2: 60, dur: 0.45, vol: 0.1 });
      SN.chord([440, 523.25, 659.25, 880], { bell: true, at: 0.55, dur: 1.6, vol: 0.02, spread: 0.06, ratio: 3.01, index: 0.9 });
      if (pad) pad.stop(1.1); if (hum) hum.stop(0.25); pad = hum = null;
    }
    var flying = false, T0 = 0;
    var at = quick ? { slam: 240, lit: 700, sweep: 820, fly: 1050 } : { slam: 1400, lit: 2250, sweep: 2480, fly: 3300 };
    if (quick) logo.style.setProperty('--st', '28ms');

    // the flight, on the canvas
    var Flight = (function () {
      var cv = el.querySelector('.nsi-cv'), g = cv && cv.getContext && cv.getContext('2d');
      if (!g) return null;
      var W, H, DPR, HZ, FL, CH = 1, z = 0, camX = 0, t = 0, last = 0, warpAt = -9;
      var towers = [], drones = [], beams = [], bits = [], stars = [], hills = [], spawn = 0.5;
      var TC = ['#22e6ff', '#b46bff', '#5cff9d'], DC = ['#ff2d9b', '#ff8a3d', '#b46bff', '#ffd633'];
      function size() {
        W = win.innerWidth; H = win.innerHeight; DPR = Math.min(2, win.devicePixelRatio || 1);
        cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
        HZ = H * 0.63; FL = H * 0.95;
        hills = [0, 1].map(function (r) {
          var p = [], x = -30;
          while (x < W + 60) { p.push([x, HZ - H * (r ? rnd(0.005, 0.035) : rnd(0.03, 0.105))]); x += r ? rnd(25, 55) : rnd(40, 90); p.push([x, HZ - H * rnd(0, 0.015)]); x += rnd(20, 50); }
          return p;
        });
        stars = [];
        for (var i = 0; i < 110; i++) stars.push({ x: Math.random() * W, y: Math.random() * HZ * 0.92, r: rnd(0.4, 1.5), p: Math.random() * 6 });
      }
      function start() {
        size(); win.addEventListener('resize', size);
        for (var k = 0; k < 14; k++) towers.push({ side: k % 2 ? 1 : -1, x: (k % 2 ? 1 : -1) * rnd(2.5, 3.3), z: 5 + k * 4.2, h: rnd(1.1, 2.4), c: TC[k % 3], cd: rnd(0, 0.5) });
        last = win.performance.now();
        win.requestAnimationFrame(frame);
      }
      function warp() { warpAt = t; }
      function proj(x, y, rz) { return [W / 2 + FL * (x - camX) / rz, HZ + FL * (CH - y) / rz]; }
      function pop(x, y, c) {
        for (var i = 0; i < 16; i++) { var a = Math.random() * 6.28, v = rnd(60, 260); bits.push({ x: x, y: y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: rnd(0.3, 0.6), c: c }); }
        bits.push({ ring: true, x: x, y: y, life: 0.35, c: c });
      }
      function frame(now) {
        if (R.over) { win.removeEventListener('resize', size); return; }
        win.requestAnimationFrame(frame);
        var dt = Math.min(0.05, Math.max(0, (now - last) / 1000)); last = now; t += dt;
        var wk = (t - warpAt) / 0.9, spd = 7 + (wk >= 0 && wk < 1 ? 38 * Math.sin(Math.PI * wk) : 0);
        z += spd * dt; camX = 0.35 * Math.sin(t * 0.6);
        for (var i = 0; i < towers.length; i++) { var tw = towers[i]; if (tw.z - z < 0.9) { if (!quick) sPass(tw.side); tw.z += towers.length * 4.2; tw.h = rnd(1.1, 2.4); } }
        spawn -= dt;
        if (spawn <= 0 && t > 0.3) { spawn = rnd(0.28, 0.5); drones.push({ x: rnd(-1.9, 1.9), y: rnd(1.25, 1.9), z: z + 58, hp: 1 + (Math.random() * 3 | 0), c: DC[(Math.random() * DC.length) | 0], r: Math.random() * 6, hit: 0 }); }
        for (var d = drones.length - 1; d >= 0; d--) { var dr = drones[d]; dr.z -= 6 * dt; dr.r += dt * 3; dr.hit = Math.max(0, dr.hit - dt * 6); if (dr.z - z < 1.2) drones.splice(d, 1); }
        for (i = 0; i < towers.length; i++) {
          tw = towers[i]; var rz = tw.z - z; tw.cd -= dt;
          if (rz < 3 || rz > 34 || tw.cd > 0) continue;
          var best = null;
          for (d = 0; d < drones.length; d++) { var e = drones[d], dz = e.z - tw.z; if (dz > -2 && dz < 9 && e.z - z > 2.5 && (!best || e.z < best.z)) best = e; }
          if (!best) continue;
          tw.cd = rnd(0.28, 0.45);
          var a = proj(tw.x, tw.h + 0.1, rz), b = proj(best.x, best.y, best.z - z);
          beams.push({ x1: a[0], y1: a[1], x2: b[0], y2: b[1], c: tw.c, life: 0.13 });
          sZap((a[0] / W) * 1.6 - 0.8);
          best.hit = 1;
          if (--best.hp <= 0) { pop(b[0], b[1], best.c); sPop((b[0] / W) * 1.6 - 0.8); drones.splice(drones.indexOf(best), 1); }
        }
        draw(spd);
      }
      function draw(spd) {
        g.setTransform(DPR, 0, 0, DPR, 0, 0);
        g.clearRect(0, 0, W, H);
        var warpK = Math.max(0, (spd - 7) / 38);
        for (var i = 0; i < stars.length; i++) {
          var st = stars[i], tw = 0.55 + 0.45 * Math.sin(t * 2 + st.p);
          if (warpK > 0.02) {
            var dx = st.x - W / 2, dy = st.y - HZ, l = warpK * 0.35;
            g.strokeStyle = 'rgba(210,245,255,' + (0.6 * tw).toFixed(3) + ')'; g.lineWidth = st.r;
            g.beginPath(); g.moveTo(st.x, st.y); g.lineTo(st.x + dx * l, st.y + dy * l); g.stroke();
          } else { g.fillStyle = 'rgba(220,245,255,' + (0.7 * tw).toFixed(3) + ')'; g.fillRect(st.x, st.y, st.r, st.r); }
        }
        hills.forEach(function (p, r) {
          g.beginPath(); g.moveTo(p[0][0], HZ);
          for (var k = 0; k < p.length; k++) g.lineTo(p[k][0], p[k][1]);
          g.lineTo(W + 60, HZ); g.closePath();
          g.fillStyle = r ? '#0a0420' : '#07021a'; g.fill();
          g.strokeStyle = r ? 'rgba(34,230,255,.55)' : 'rgba(255,45,155,.5)'; g.lineWidth = 1.2; g.stroke();
        });
        var gr = g.createLinearGradient(0, HZ, 0, H); gr.addColorStop(0, '#12052b'); gr.addColorStop(0.5, '#06031a'); gr.addColorStop(1, '#02030a');
        g.fillStyle = gr; g.fillRect(0, HZ, W, H - HZ);
        var sp = 1.3, first = Math.ceil(z / sp) * sp;
        for (var n = 0; n < 60; n++) {
          var rz = first + n * sp - z; if (rz < 0.3) continue;
          var y = HZ + FL * CH / rz; if (y - HZ < 1) break;
          var al = Math.min(1, (y - HZ) / (H * 0.2));
          g.strokeStyle = 'rgba(255,45,155,' + (0.62 * al).toFixed(3) + ')'; g.lineWidth = Math.min(2.4, 0.5 + 24 / rz);
          g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke();
        }
        for (var k2 = -16; k2 <= 16; k2++) {
          var x0 = k2 * 1.1 - camX, near = 0.35, far = 70;
          var ax = W / 2 + FL * x0 / near, ay = HZ + FL * CH / near, bx = W / 2 + FL * x0 / far, by = HZ + FL * CH / far;
          var lg = g.createLinearGradient(0, ay, 0, HZ); lg.addColorStop(0, 'rgba(34,230,255,.55)'); lg.addColorStop(0.8, 'rgba(34,230,255,.12)'); lg.addColorStop(1, 'rgba(34,230,255,0)');
          g.strokeStyle = lg; g.lineWidth = 1.3; g.beginPath(); g.moveTo(ax, ay); g.lineTo(bx, by); g.stroke();
        }
        var things = [];
        towers.forEach(function (o2) { things.push({ o: o2, rz: o2.z - z, k: 't' }); });
        drones.forEach(function (o2) { things.push({ o: o2, rz: o2.z - z, k: 'd' }); });
        things.sort(function (a, b) { return b.rz - a.rz; });
        for (i = 0; i < things.length; i++) {
          var th = things[i], ob = th.o; rz = th.rz; if (rz < 0.9 || rz > 62) continue;
          var fog = Math.min(1, (62 - rz) / 30);
          if (th.k === 't') {
            var base = proj(ob.x, 0, rz), top = proj(ob.x, ob.h, rz), hw = FL * 0.2 / rz;
            g.globalAlpha = fog;
            g.fillStyle = '#060818'; g.fillRect(base[0] - hw, top[1], hw * 2, base[1] - top[1]);
            g.strokeStyle = ob.c; g.lineWidth = Math.max(1, 3 / rz * 2); g.strokeRect(base[0] - hw, top[1], hw * 2, base[1] - top[1]);
            g.fillStyle = ob.c; g.globalAlpha = fog * 0.25; g.fillRect(base[0] - hw, top[1], hw * 2, (base[1] - top[1]) * 0.12);
            g.globalAlpha = fog; g.beginPath(); g.arc(top[0], top[1], Math.max(1.5, FL * 0.07 / rz), 0, 6.283); g.fill();
            g.globalCompositeOperation = 'lighter';
            var glow = g.createRadialGradient(top[0], top[1], 0, top[0], top[1], FL * 0.5 / rz);
            glow.addColorStop(0, ob.c + '88'); glow.addColorStop(1, ob.c + '00'); g.fillStyle = glow;
            g.beginPath(); g.arc(top[0], top[1], FL * 0.5 / rz, 0, 6.283); g.fill();
            g.globalCompositeOperation = 'source-over';
          } else {
            var p = proj(ob.x, ob.y, rz), sz = FL * 0.16 / rz;
            g.globalAlpha = fog; g.save(); g.translate(p[0], p[1]); g.rotate(ob.r);
            g.fillStyle = ob.hit > 0.2 ? '#ffffff' : ob.c;
            g.beginPath(); g.moveTo(0, -sz); g.lineTo(sz, 0); g.lineTo(0, sz); g.lineTo(-sz, 0); g.closePath(); g.fill();
            g.globalAlpha = fog * 0.25; g.beginPath(); g.moveTo(0, -sz * 1.8); g.lineTo(sz * 1.8, 0); g.lineTo(0, sz * 1.8); g.lineTo(-sz * 1.8, 0); g.closePath(); g.fill();
            g.restore();
          }
        }
        g.globalAlpha = 1;
        g.globalCompositeOperation = 'lighter'; g.lineCap = 'round';
        for (i = beams.length - 1; i >= 0; i--) {
          var bm = beams[i]; bm.life -= 1 / 60; if (bm.life <= 0) { beams.splice(i, 1); continue; }
          var ba = bm.life / 0.13;
          g.strokeStyle = bm.c; g.globalAlpha = 0.4 * ba; g.lineWidth = 6; g.beginPath(); g.moveTo(bm.x1, bm.y1); g.lineTo(bm.x2, bm.y2); g.stroke();
          g.strokeStyle = '#ffffff'; g.globalAlpha = ba; g.lineWidth = 1.4; g.stroke();
        }
        for (i = bits.length - 1; i >= 0; i--) {
          var bt = bits[i]; bt.life -= 1 / 60; if (bt.life <= 0) { bits.splice(i, 1); continue; }
          if (bt.ring) { var rk = 1 - bt.life / 0.35; g.strokeStyle = bt.c; g.globalAlpha = 0.8 * (1 - rk); g.lineWidth = 2; g.beginPath(); g.arc(bt.x, bt.y, 4 + 30 * rk, 0, 6.283); g.stroke(); }
          else { bt.x += bt.vx / 60; bt.y += bt.vy / 60; bt.vx *= 0.94; bt.vy *= 0.94; g.fillStyle = bt.c; g.globalAlpha = Math.min(1, bt.life * 2.4); g.fillRect(bt.x - 1.5, bt.y - 1.5, 3, 3); }
        }
        g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
      }
      return { start: start, warp: warp };
    })();

    var BOOT = [
      ['BEESIDE SYSTEMS  ', '<b>NS-II</b>', '  BIOS v2.0'],
      ['MEMORY CHECK ....... ', '<i>640K OK</i>', ''],
      ['NEON CORE .......... ', '<i>ONLINE</i>', ''],
      ['GRID LINK .......... ', '<i>LOCKED</i>', ''],
      ['TOWER ARRAY ........ ', '<i>22 ARMED</i>', ''],
      ['SIEGE PROTOCOL ..... ', '<i>ENGAGED</i>', '']
    ];
    function boot() {
      var box = el.querySelector('.nsi-boot'), html = '';
      sPost();
      BOOT.forEach(function (l, k) {
        later(function () { html += l[0]; box.innerHTML = html + '_'; }, 60 + k * 125);
        later(function () { html += l[1] + l[2] + '\n'; box.innerHTML = html + (k < BOOT.length - 1 ? '_' : ''); sBootLine(k); }, 115 + k * 125);
      });
      later(function () { el.classList.add('nsi-bootx'); sBootOut(); }, at.slam - 380);
    }
    function fontReady() { try { return !doc.fonts || doc.fonts.check('900 60px Orbitron'); } catch (e) { return true; } }
    function slam() { logo.classList.add('nsi-slam'); sSlam(); }
    function lit() { logo.classList.add('nsi-lit'); el.classList.add('nsi-shockgo', 'nsi-shake', 'nsi-flareon'); if (Flight) Flight.warp(); sLit(); sWarp(); }
    function sweep() { logo.classList.add('nsi-sweep'); sSweep(); }
    // run fn once node's transition of prop ends; the backstop counts from when it really starts
    function after(node, prop, ms, fn) {
      var ran = false, tm = setTimeout(go, ms + 2500);
      function go() { if (ran) return; ran = true; clearTimeout(tm); node.removeEventListener('transitionend', te); node.removeEventListener('transitionrun', tr); fn(); }
      function te(e) { if (e.target === node && e.propertyName === prop) go(); }
      function tr(e) { if (e.target === node && e.propertyName === prop) { clearTimeout(tm); tm = setTimeout(go, ms); } }
      node.addEventListener('transitionend', te);
      node.addEventListener('transitionrun', tr);
    }
    // the logo lands on the title screen's own logo, then hands over to it;
    // this is the last second, so the title screen shows through as it flies
    function fly() {
      if (flying) return;
      flying = true;
      R.whenReady(land, 14000);
    }
    function land() {
      if (R.over) return;
      sFly();
      R.timers.forEach(clearTimeout); R.timers = [];
      if (!logo.classList.contains('nsi-lit')) logo.style.setProperty('--st', '0ms');
      logo.classList.add('nsi-slam', 'nsi-lit');
      el.classList.remove('nsi-shake');
      el.classList.add('nsi-fly');
      var T = R.target() || doc;
      css(T, 'bso-ns-target-css', NS_TARGET_CSS);
      R.reveal();
      var title = T.getElementById('ovTitle'), target = T.getElementById('logo'), box = T.getElementById('titleBox');
      var r = target && title && title.classList.contains('on') ? target.getBoundingClientRect() : null;
      var tRoot = T.documentElement;
      if (box && r && r.width) { box.classList.add('nsi-reveal'); setTimeout(function () { box.classList.remove('nsi-reveal'); }, 1500); }
      if (calm || !r || !r.width) {
        tRoot.classList.add('nsi-land'); tRoot.classList.remove('nsi-on');
        after(logo, 'opacity', 1500, R.end);
        logo.style.transition = 'opacity .45s ease';
        logo.style.opacity = '0';
        return;
      }
      // line up the words themselves: the title's logo is a full-width block, so it is its text that is measured
      var words = target.firstChild && target.firstChild.nodeType === 3 ? target.firstChild : target;
      var rg = T.createRange(); rg.selectNodeContents(words);
      var rt = rg.getBoundingClientRect(), li = logo.getBoundingClientRect(), g = logo.querySelector('.nsi-g');
      var k = parseFloat(win.getComputedStyle(logo).getPropertyValue('--k')) || 1.3;
      var ri = { left: li.left + g.offsetLeft * k, top: li.top + g.offsetTop * k, width: g.offsetWidth * k, height: g.offsetHeight * k };
      var s = rt.width / (ri.width / k);
      var cx = li.left + li.width / 2, cy = li.top + li.height / 2;
      var dx = (rt.left + rt.width / 2) - cx - s * ((ri.left + ri.width / 2) - cx) / k;
      var dy = (rt.top + rt.height / 2) - cy - s * ((ri.top + ri.height / 2) - cy) / k;
      logo.style.transition = 'transform .62s cubic-bezier(.7,0,.2,1)';
      logo.style.transform = 'translate(calc(-50% + ' + dx.toFixed(1) + 'px), calc(-50% + ' + dy.toFixed(1) + 'px)) scale(' + s.toFixed(4) + ')';
      after(logo, 'transform', 1400, function () {
        tRoot.classList.add('nsi-land'); tRoot.classList.remove('nsi-on');
        after(logo, 'opacity', 900, function () { tRoot.classList.remove('nsi-land'); R.end(); });
        logo.style.transition = 'opacity .24s ease';
        logo.style.opacity = '0';
      });
    }
    R.onSkip(function () { if (!flying) fly(); });
    T0 = Date.now();
    if (calm) { el.classList.add('nsi-calm'); later(fly, 900); return R.api; }
    el.classList.add('nsi-go');
    sCrt(); later(sPad, 300); if (!quick) later(sType, 450);
    if (Flight) Flight.start();
    if (!quick) later(boot, 240);
    if (quick) el.querySelector('.nsi-presents').style.display = 'none';
    later(function go() {
      if (!fontReady() && Date.now() - T0 < at.slam + 700) { later(go, 80); return; }
      slam();
      later(lit, at.lit - at.slam);
      later(sweep, at.sweep - at.slam);
      later(fly, at.fly - at.slam);
    }, at.slam);
    return R.api;
  };

  // ════════════════════════════════════════════════════════════════════
  //  ROTFALL: rain, and lightning shows the swarm all round. An ember
  //  catches in the middle; they creep in to its heartbeat; it gathers and
  //  bursts in a shockwave that turns every one of them to embers, and the
  //  embers rise and gather into the name, right where the menu's name is.
  // ════════════════════════════════════════════════════════════════════
  var RF_CSS = [
    '#bsoRot{position:fixed;inset:0;z-index:2147483000;overflow:hidden;background:#040505;cursor:pointer;-webkit-user-select:none;user-select:none;animation:bsoFailsafe .4s linear 30s forwards}',
    '@keyframes bsoFailsafe{to{opacity:0;visibility:hidden;pointer-events:none}}',
    '#bsoRot.out{opacity:0;pointer-events:none;transition:opacity 1s ease}',
    '#bsoRot canvas{position:absolute;inset:0;width:100%;height:100%;display:block}',
    '#bsoRot .bso-skip{position:absolute;left:0;right:0;bottom:22px;text-align:center;font-family:Rajdhani,sans-serif;font-size:11px;font-weight:600;letter-spacing:5px;color:#2e2e2e;opacity:0;animation:rfFade .6s ease 1.2s forwards}',
    '#bsoRot.rf-quick .bso-skip,#bsoRot.out .bso-skip{display:none}',
    '@keyframes rfFade{to{opacity:1}}'
  ].join('\n');
  var RF_TARGET_CSS = 'html.ri-on .logo-wrap,html.ri-on #toBeeside{opacity:0}\nhtml.ri-land .logo-wrap{transition:opacity .45s ease}';

  O.rotfall = function (o) {
    var host = o.host || document;
    css(host, 'bso-rf-css', RF_CSS);
    // the menu's typeface, here too, for the name the embers become
    if (!host.getElementById('bso-font-bebas')) {
      var fl = host.createElement('link'); fl.id = 'bso-font-bebas'; fl.rel = 'stylesheet';
      fl.href = 'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Rajdhani:wght@600&display=swap';
      (host.head || host.documentElement).appendChild(fl);
    }
    var R = Run(o, 'bsoRot', '<canvas></canvas><div class="bso-skip"></div>');
    var el = R.el, win = R.win, SN = R.SN, cv = el.querySelector('canvas'), g = cv.getContext('2d');
    if (R.quick) el.classList.add('rf-quick');
    var W, H, DPR, cx, cy, MIN;
    function size() {
      W = win.innerWidth; H = win.innerHeight; DPR = Math.min(2, win.devicePixelRatio || 1);
      cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
      cx = W / 2; cy = H / 2; MIN = Math.min(W, H);
    }
    size(); win.addEventListener('resize', size);
    var Q = R.quick;
    var T = Q ? { flash1: 0.05, ember: 0.25, creep: 0.25, flash2: -1, charge: 0.45, shock: 0.7, rise: 0.85, form: 1.05, solid: 1.7, reveal: 1.75 }
              : { flash1: 0.35, ember: 0.9, creep: 1.0, flash2: 1.85, charge: 2.4, shock: 2.72, rise: 2.9, form: 3.35, solid: 4.45, reveal: 4.6 };
    var t = 0, last = 0, flash = 0, bolt = null, orb = 0, beat = 0, light = 0, charge = 0, shock = -1, shake = 0, formAt = Infinity, solidAt = Infinity;
    var FORM = Q ? 0.35 : 0.6, FLY = Q ? 0.35 : 0.55, SOLID = (T.solid - T.form);
    var rain = [], Z = [], E = [], pts = null, name = null, solid = 0, lettersDone = 0;
    for (var i = 0; i < 230; i++) rain.push({ x: Math.random() * 1.3, y: Math.random(), l: rnd(12, 26), a: rnd(0.12, 0.32), v: rnd(0.9, 1.3) });
    // the swarm: a ring of the dead all round, none in the middle
    var nZ = Q ? 70 : 110;
    for (i = 0; i < nZ; i++) {
      var a = Math.random() * TAU, d = rnd(0.36, 0.95), rr = rnd(9, 17);
      Z.push({ a: a, d: d, r: rr, v: rnd(0.035, 0.07), wob: Math.random() * 6, open: rnd(0, 0.5), dead: -1, glow: ['#4ade80', '#38bdf8', '#f87171', '#c084fc', '#fbbf24'][(Math.random() * 5) | 0] });
    }
    function zx(z) { return cx + Math.cos(z.a) * z.d * Math.hypot(W, H) * 0.55; }
    function zy(z) { return cy + Math.sin(z.a) * z.d * Math.hypot(W, H) * 0.55; }

    // ── its sound
    function live() { return R.live(); }
    var rainT = 0;
    function sRain() { if (!live()) return; SN.noise({ f: rnd(2600, 4200), dur: 0.7, vol: 0.022, q: 0.4, atk: 0.25, pan: rnd(-0.6, 0.6), wet: 0.4 }); }
    function sThunder(big) {
      if (!live()) return;
      SN.noise({ f: 3200, f2: 700, dur: 0.16, vol: big ? 0.16 : 0.1, ft: 'highpass' });
      SN.noise({ at: 0.05, f: 420, f2: 55, dur: 1.9, vol: big ? 0.32 : 0.22, ft: 'lowpass', q: 0.5, atk: 0.03, wet: 0.6 });
      SN.tone({ at: 0.05, f: 52, f2: 28, dur: 1.6, vol: big ? 0.22 : 0.15 });
    }
    function sEyes() {
      if (!live()) return;
      for (var k = 0; k < 24; k++) { var p = rnd(-0.9, 0.9); SN.tone({ at: rnd(0.05, 0.6), f: 380 + Math.random() * 160, f2: 190, dur: 0.08, vol: 0.008, type: 'triangle', pan: p, wet: 0.35 }); }
    }
    function sIgnite() {
      if (!live()) return;
      for (var k = 0; k < 8; k++) SN.noise({ at: Math.random() * 0.35, f: 2500 + Math.random() * 3000, dur: 0.012, vol: 0.04, q: 4, pan: Math.random() * 0.6 - 0.3, wet: 0.15 });
      SN.noise({ f: 500, f2: 1600, dur: 0.45, vol: 0.05, ft: 'lowpass', atk: 0.12, wet: 0.3 }); SN.tone({ f: 95, f2: 48, dur: 0.5, vol: 0.14 });
    }
    function sBeat(v) { if (!live()) return; SN.tone({ f: 62, f2: 34, dur: 0.28, vol: 0.3 * v }); SN.tone({ at: 0.18, f: 52, f2: 32, dur: 0.26, vol: 0.2 * v }); SN.noise({ f: 400, f2: 1600, dur: 0.8, vol: 0.012 * v, q: 3, atk: 0.1, wet: 0.7 }); }
    function sGrowls() {
      if (!live()) return;
      for (var k = 0; k < 5; k++) { var p = rnd(-0.8, 0.8), at = rnd(0, 1.2);
        SN.tone({ at: at, type: 'sawtooth', f: rnd(62, 82), f2: rnd(46, 56), dur: 0.7, vol: 0.024, cut: 520, cut2: 240, vib: [rnd(14, 22), 5], atk: 0.12, pan: p, wet: 0.45 });
        SN.noise({ at: at, f: rnd(190, 300), f2: 140, dur: 0.6, vol: 0.02, q: 5, atk: 0.15, pan: p, wet: 0.4 }); }
    }
    function sCharge(d) { if (!live()) return; SN.noise({ f: 300, f2: 5000, dur: d, vol: 0.06, q: 2, atk: d * 0.92, wet: 0.3 }); SN.tone({ type: 'sawtooth', f: 70, f2: 420, dur: d, vol: 0.04, atk: d * 0.85, cut: 800, cut2: 4000 }); }
    function sShock() {
      if (!live()) return;
      SN.noise({ f: 5000, dur: 0.06, vol: 0.14, ft: 'highpass' });
      SN.noise({ f: 900, f2: 120, dur: 1.2, vol: 0.3, ft: 'lowpass', q: 0.7, wet: 0.5 });
      SN.tone({ f: 85, f2: 26, dur: 1, vol: 0.35 });
      SN.noise({ f: 200, f2: 3500, dur: 0.75, vol: 0.03, q: 2, atk: 0.05, wet: 0.6 });
      for (var k = 0; k < 16; k++) SN.tone({ at: 0.05 + Math.random() * 0.55, f: 700 + Math.random() * 300, f2: 150, dur: 0.06, vol: 0.016, type: 'triangle', pan: rnd(-0.9, 0.9), wet: 0.2 });
    }
    function sRise() { if (!live()) return; SN.noise({ f: 600, f2: 5200, dur: 1.2, vol: 0.02, q: 2, atk: 0.5, wet: 0.7 }); SN.chord([220, 329.63, 440], { at: 0.2, dur: 1.6, vol: 0.012, atk: 0.5, wet: 0.8, spread: 0.1 }); }
    function sLetter(x, lastOne) { if (!live()) return; var p = SN.pan(x); SN.tone({ f: lastOne ? 140 : 125, f2: lastOne ? 38 : 50, dur: lastOne ? 0.35 : 0.15, vol: lastOne ? 0.24 : 0.14, pan: p }); SN.noise({ f: 1600, f2: 400, dur: 0.05, vol: 0.05, pan: p, wet: 0.2 }); }
    function sName() { if (!live()) return; SN.noise({ f: 3000, f2: 8000, dur: 0.5, vol: 0.02, q: 2, atk: 0.1, wet: 0.5 }); SN.chord([110, 164.81, 220, 261.63], { bell: true, dur: 2.4, vol: 0.02, spread: 0.05, ratio: 1.5, index: 1.2 }); }

    // ── where the name goes: the menu's own name, measured in its document
    function measure() {
      var D = R.target() || R.doc, lm = D.querySelector('.logo-main'), lt = D.querySelector('.logo-tag'), ls = D.querySelector('.logo-sub');
      if (!lm) return null;
      var dw = D.defaultView || win, r = lm.getBoundingClientRect(), cs = dw.getComputedStyle(lm);
      function line(n) { if (!n) return null; var rr = n.getBoundingClientRect(), c = dw.getComputedStyle(n); return { text: n.textContent, x: rr.left + rr.width / 2, y: rr.top + rr.height / 2, font: c.fontWeight + ' ' + c.fontSize + ' Rajdhani, sans-serif', ls: c.letterSpacing, col: c.color }; }
      return { text: lm.textContent, x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, size: parseFloat(cs.fontSize) || 96, ls: cs.letterSpacing, tag: line(lt), sub: line(ls) };
    }
    function drawName(c, n, fill) {
      c.save(); c.textAlign = 'center'; c.textBaseline = 'middle';
      c.font = n.size + 'px "Bebas Neue", Impact, sans-serif';
      try { c.letterSpacing = n.ls; } catch (e) {}
      c.fillStyle = fill; c.fillText(n.text, n.x + (parseFloat(n.ls) || 0) / 2, n.y + n.size * 0.02);
      c.restore();
    }
    // the points the embers gather to: the pixels of the name
    function sample(n) {
      var c = win.document.createElement('canvas'); c.width = Math.ceil(W); c.height = Math.ceil(H);
      var x = c.getContext('2d'); drawName(x, n, '#fff');
      var data = x.getImageData(0, 0, c.width, c.height).data, out = [], step = Math.max(2, Math.round(n.size / 34));
      var y0 = Math.max(0, Math.floor(n.y - n.size)), y1 = Math.min(c.height, Math.ceil(n.y + n.size)), x0 = Math.max(0, Math.floor(n.x - n.w)), x1 = Math.min(c.width, Math.ceil(n.x + n.w));
      for (var yy = y0; yy < y1; yy += step) for (var xx = x0; xx < x1; xx += step) if (data[(yy * c.width + xx) * 4 + 3] > 140) out.push([xx, yy]);
      return out;
    }
    // where each letter of the name ends, for its thump
    function letterEdges(n) {
      var c = win.document.createElement('canvas').getContext('2d');
      c.font = n.size + 'px "Bebas Neue", Impact, sans-serif';
      try { c.letterSpacing = n.ls; } catch (e) {}
      var full = c.measureText(n.text).width, x0 = n.x - full / 2, ed = [];
      for (var k = 1; k <= n.text.length; k++) ed.push(x0 + c.measureText(n.text.slice(0, k)).width);
      return ed;
    }

    // ── the scene
    function lightning() {
      flash = 1; shake = Math.max(shake, 5);
      var x = rnd(W * 0.15, W * 0.85), y = 0, p = [[x, y]];
      while (y < H * rnd(0.45, 0.8)) { x += rnd(-40, 40); y += rnd(25, 60); p.push([x, y]); }
      bolt = { p: p, life: 0.22 };
    }
    function killAt(z, x, y) {
      z.dead = 0;
      for (var k = 0; k < (Q ? 5 : 6); k++) { var a = Math.random() * TAU, v = rnd(40, 180); E.push({ x: x, y: y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 60, t0: t, tx: null, ty: null, delay: 0, life: 1, r: rnd(1, 2.2) }); }
    }
    var edges = null, thumped = [];
    function gather() {
      name = measure();
      if (!name) { R.later(hand, 400); return; }
      edges = letterEdges(name);
      pts = sample(name);
      if (!pts.length) { name = null; R.later(hand, 400); return; }
      // top up the embers from the swarm with a few from the ember itself
      while (E.length < Math.min(pts.length, Q ? 480 : 700)) { var a = Math.random() * TAU; E.push({ x: cx + Math.cos(a) * rnd(5, 40), y: cy + Math.sin(a) * rnd(5, 40), vx: Math.cos(a) * rnd(40, 160), vy: Math.sin(a) * rnd(40, 160) - 80, t0: t, life: 1, r: rnd(0.9, 2) }); }
      // letters fill from left to right: each ember takes a point, earlier the further left
      var span = name.w || 1, left = name.x - span / 2;
      for (var k = 0; k < E.length; k++) {
        var q = pts[(k * 7919) % pts.length], e = E[k];
        e.tx = q[0]; e.ty = q[1]; e.delay = clamp((q[0] - left) / span, 0, 1) * FORM + rnd(0, 0.12);
      }
      formAt = t; solidAt = t + SOLID;
      R.later(sName, (SOLID + 0.05) * 1000);
      R.later(hand, (SOLID + 0.2) * 1000);
    }
    // gather once the menu is there to gather onto, its name in its own typeface and in ours
    function whenMenu(fn) {
      var t0 = Date.now();
      (function w() {
        if (R.over) return;
        var D = R.target() || R.doc, ok = R.ready() && D && D.querySelector('.logo-main');
        try { ok = ok && (!D.fonts || D.fonts.check('96px "Bebas Neue"')) && (!R.doc.fonts || R.doc.fonts.check('96px "Bebas Neue"')); } catch (e) {}
        if (ok || Date.now() - t0 > 14000) fn(); else R.later(w, 80);
      })();
      try { R.doc.fonts.load('96px "Bebas Neue"'); } catch (e) {}
    }
    function frame(now) {
      if (R.over) { win.removeEventListener('resize', size); return; }
      win.requestAnimationFrame(frame);
      var dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016; last = now; t += dt;
      if (charge > 0 && charge < 1) charge = Math.min(1, charge + dt * 3.2);
      // rain, heard
      rainT -= dt; if (rainT <= 0) { rainT = 0.42; sRain(); }
      var sx = rnd(-shake, shake), sy = rnd(-shake, shake); shake *= Math.pow(0.01, dt);
      g.setTransform(DPR, 0, 0, DPR, DPR * sx, DPR * sy);
      g.fillStyle = '#040505'; g.fillRect(-20, -20, W + 40, H + 40);
      flash = Math.max(0, flash - dt * 4);
      if (bolt) { bolt.life -= dt; if (bolt.life <= 0) bolt = null; }
      // the ember's light
      var LR = light * MIN * 0.32 * (1 + beat * 0.12) * (1 - charge * 0.6);
      if (LR > 1) { var lg = g.createRadialGradient(cx, cy, 0, cx, cy, LR); lg.addColorStop(0, 'rgba(232,93,0,.28)'); lg.addColorStop(0.5, 'rgba(120,40,0,.12)'); lg.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = lg; g.fillRect(0, 0, W, H); }
      // the swarm: bodies only where light falls on them, eyes always, once open
      var seen = flash > 0.05;
      for (var k = 0; k < Z.length; k++) {
        var z = Z[k];
        if (z.dead >= 0) { z.dead += dt; continue; }
        if (t > T.creep && shock < 0) z.d = Math.max(0.1, z.d - z.v * dt * (t > T.charge ? 0.4 : 1));
        z.wob += dt * 3;
        var x = zx(z) + Math.sin(z.wob) * 1.5, y = zy(z);
        var dl = Math.hypot(x - cx, y - cy), lit2 = LR > 0 ? clamp(1 - dl / LR, 0, 1) : 0, body = Math.max(seen ? flash : 0, lit2 * 0.9);
        if (body > 0.02) { g.globalAlpha = body; g.fillStyle = '#18221a'; g.beginPath(); g.arc(x, y, z.r, 0, TAU); g.fill(); g.strokeStyle = z.glow; g.globalAlpha = body * 0.4; g.lineWidth = 1.2; g.stroke(); g.globalAlpha = 1; }
        if (t > T.flash1 + z.open * (Q ? 0.3 : 1)) {
          var ang = Math.atan2(cy - y, cx - x), ex = Math.cos(ang), ey = Math.sin(ang), er = z.r * 0.2;
          g.globalCompositeOperation = 'lighter';
          var eg = g.createRadialGradient(x + ex * z.r * 0.3, y + ey * z.r * 0.3, 0, x + ex * z.r * 0.3, y + ey * z.r * 0.3, er * 4);
          eg.addColorStop(0, 'rgba(255,40,0,.5)'); eg.addColorStop(1, 'rgba(255,40,0,0)'); g.fillStyle = eg; g.fillRect(x - z.r, y - z.r, z.r * 2, z.r * 2);
          g.globalCompositeOperation = 'source-over';
          g.fillStyle = '#ff2200';
          g.beginPath(); g.arc(x + ex * z.r * 0.3 - ey * z.r * 0.28, y + ey * z.r * 0.3 + ex * z.r * 0.28, er, 0, TAU); g.arc(x + ex * z.r * 0.3 + ey * z.r * 0.28, y + ey * z.r * 0.3 - ex * z.r * 0.28, er, 0, TAU); g.fill();
        }
        // the shockwave reaches it
        if (shock >= 0) { var sr = (t - shock) * Math.hypot(W, H) * 1.3; if (dl < sr) killAt(z, x, y); }
      }
      // the shockwave ring
      if (shock >= 0 && t - shock < 0.8) {
        var sk = (t - shock) / 0.8, srr = sk * Math.hypot(W, H) * 1.05;
        g.strokeStyle = 'rgba(255,140,40,' + (1 - sk).toFixed(3) + ')'; g.lineWidth = 10 * (1 - sk) + 2;
        g.shadowColor = '#e85d00'; g.shadowBlur = 30; g.beginPath(); g.arc(cx, cy, srr, 0, TAU); g.stroke(); g.shadowBlur = 0;
      }
      // the ember: a pulsing orb, gathering itself before the burst
      if (orb > 0 && (shock < 0 || t - shock < 0.3)) {
        var os = (8 + 5 * beat) * orb * (1 + charge * 0.8) * (shock >= 0 ? Math.max(0, 1 - (t - shock) / 0.3) : 1);
        var og = g.createRadialGradient(cx, cy, 0, cx, cy, os * 5); og.addColorStop(0, 'rgba(255,200,120,.95)'); og.addColorStop(0.2, 'rgba(255,109,0,.8)'); og.addColorStop(1, 'rgba(232,93,0,0)');
        g.fillStyle = og; g.beginPath(); g.arc(cx, cy, os * 5, 0, TAU); g.fill();
        g.fillStyle = '#ffb35c'; g.beginPath(); g.arc(cx, cy, os * 0.6, 0, TAU); g.fill();
      }
      beat *= Math.pow(0.02, dt);
      // embers: thrown out, then rising, then gathering into the name
      g.globalCompositeOperation = 'lighter';
      for (k = 0; k < E.length; k++) {
        var e = E[k], age = t - e.t0;
        if (e.tx != null && t > formAt + e.delay) {
          var fk = clamp((t - formAt - e.delay) / FLY, 0, 1), f2 = eio(fk);
          if (e.sx == null) { e.sx = e.x; e.sy = e.y; }
          e.x = e.sx + (e.tx - e.sx) * f2 + Math.sin(fk * Math.PI) * 30 * Math.cos(k); e.y = e.sy + (e.ty - e.sy) * f2 - Math.sin(fk * Math.PI) * 40;
          if (fk >= 1 && !e.done) { e.done = 1; }
        } else {
          e.vx *= Math.pow(0.4, dt); e.vy = e.vy * Math.pow(0.4, dt) - 60 * dt; e.x += e.vx * dt + Math.sin(age * 3 + k) * 20 * dt; e.y += e.vy * dt;
        }
        var ea = (1 - solid) * (e.done ? 0.85 : 0.75);
        if (ea <= 0.01) continue;
        g.fillStyle = e.done ? 'rgba(255,140,50,' + ea.toFixed(3) + ')' : 'rgba(255,110,20,' + ea.toFixed(3) + ')';
        g.fillRect(e.x - e.r, e.y - e.r, e.r * 2, e.r * 2);
      }
      g.globalCompositeOperation = 'source-over';
      // each letter thumps as its embers land
      if (name && edges && t > formAt) {
        for (k = 0; k < edges.length; k++) if (!thumped[k] && t > formAt + clamp((edges[k] - (name.x - name.w / 2)) / name.w, 0, 1) * FORM + FLY) {
          thumped[k] = 1; sLetter(edges[k], k === edges.length - 1); shake = Math.max(shake, k === edges.length - 1 ? 4 : 2);
        }
      }
      // the name itself, as the embers settle into it, then its lines
      if (name && t > solidAt - 0.25) {
        solid = clamp((t - (solidAt - 0.25)) / 0.35, 0, 1);
        g.save(); g.shadowColor = '#e85d00'; g.shadowBlur = 40 * (1.4 - solid * 0.6); g.globalAlpha = solid; drawName(g, name, '#e85d00'); g.restore();
        [name.tag, name.sub].forEach(function (ln, j) {
          if (!ln || !ln.text) return;
          var lk = clamp((t - solidAt - j * 0.12) / 0.4, 0, 1); if (lk <= 0) return;
          g.save(); g.textAlign = 'center'; g.textBaseline = 'middle'; g.font = ln.font; try { g.letterSpacing = ln.ls; } catch (x2) {}
          var n2 = Math.ceil(ln.text.length * lk);
          g.fillStyle = lk < 1 ? '#ff8a3d' : ln.col; g.globalAlpha = 0.9;
          var full = g.measureText(ln.text).width;
          g.textAlign = 'left'; g.fillText(ln.text.slice(0, n2), ln.x - full / 2 + (parseFloat(ln.ls) || 0) / 2, ln.y);
          g.restore();
        });
      }
      // rain over everything, and the flash
      g.strokeStyle = 'rgba(160,175,190,.5)'; g.lineWidth = 1;
      for (k = 0; k < rain.length; k++) {
        var rd = rain[k]; rd.y += dt * rd.v * 1.25; rd.x -= dt * rd.v * 0.16; if (rd.y > 1.05) { rd.y = -0.05; rd.x = Math.random() * 1.3; }
        var rx = rd.x * W, ry = rd.y * H;
        g.globalAlpha = rd.a * (1 + flash * 1.5); g.beginPath(); g.moveTo(rx, ry); g.lineTo(rx - rd.l * 0.13, ry + rd.l); g.stroke();
      }
      g.globalAlpha = 1;
      if (bolt) { g.strokeStyle = 'rgba(220,235,255,' + (bolt.life / 0.22).toFixed(3) + ')'; g.lineWidth = 2.5; g.shadowColor = '#bcd7ff'; g.shadowBlur = 24; g.beginPath(); bolt.p.forEach(function (p, j) { j ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]); }); g.stroke(); g.shadowBlur = 0; }
      if (flash > 0) { g.fillStyle = 'rgba(200,220,255,' + (flash * 0.5).toFixed(3) + ')'; g.fillRect(-20, -20, W + 40, H + 40); }
      if (shock >= 0 && t - shock < 0.35) { g.fillStyle = 'rgba(255,190,120,' + ((1 - (t - shock) / 0.35) * 0.6).toFixed(3) + ')'; g.fillRect(-20, -20, W + 40, H + 40); }
    }

    // ── the steps
    function hand() {
      // the last second: the menu shows through, the name already on its own
      var D = R.target() || R.doc, rt = D.documentElement;
      css(D, 'bso-rf-target-css', RF_TARGET_CSS);
      R.reveal();
      rt.classList.add('ri-land'); rt.classList.remove('ri-on');
      el.classList.add('out');
      R.later(function () { rt.classList.remove('ri-land'); R.end(); }, 1050);
    }
    function schedule() {
      var L = R.later;
      L(function () { lightning(); sThunder(true); sEyes(); }, T.flash1 * 1000);
      L(function () { orb = 1; light = 1; sIgnite(); }, T.ember * 1000);
      if (!Q) {
        [1.0, 1.55, 2.0, 2.3].forEach(function (b, k) { L(function () { beat = 1; sBeat(0.7 + k * 0.15); }, b * 1000); });
        L(sGrowls, 1150);
        L(function () { lightning(); sThunder(false); }, T.flash2 * 1000);
      }
      L(function () { charge = 0.001; sCharge((T.shock - T.charge)); }, T.charge * 1000);
      L(function () { shock = t; charge = 0; light = 0.6; shake = 12; sShock(); }, T.shock * 1000);
      L(function () { sRise(); }, T.rise * 1000);
      L(function () { whenMenu(gather); }, (T.form - 0.05) * 1000);
    }
    R.onSkip(function () {
      // straight to the name
      if (t >= T.form - 0.1 || formAt < Infinity) return;
      R.timers.forEach(clearTimeout); R.timers = [];
      Z.forEach(function (z) { if (z.dead < 0) killAt(z, zx(z), zy(z)); });
      orb = 0; light = 0.5; t = Math.max(t, T.rise);
      R.later(function () { whenMenu(gather); }, 250);
    });
    if (R.calm) {
      whenMenu(function () {
        name = measure(); solid = 1;
        if (name) { g.setTransform(DPR, 0, 0, DPR, 0, 0); g.fillStyle = '#040505'; g.fillRect(0, 0, W, H); drawName(g, name, '#e85d00'); }
        R.later(hand, 500);
      });
      return R.api;
    }
    schedule();
    win.requestAnimationFrame(frame);
    return R.api;
  };
})();
