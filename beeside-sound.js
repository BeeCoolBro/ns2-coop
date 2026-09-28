/* BeeSide sound: one small synthesizer shared by the front page, Other
   Projects and the openings of Bee's Vault, NEON SIEGE 2 and ROTFALL. There
   are no sound files; every sound is made here, in the page.

   A browser only lets a page make sound once the visitor has done something
   on the site. Arriving from another BeeSide page counts in Chrome, so the
   openings are heard when you come in through the front page; opened cold,
   they are silent until the first click or key. The Sound switch on the front
   page turns all of it off (bs-sound in localStorage). */
(function () {
  if (window.BSND) return;
  var AudioC = window.AudioContext || window.webkitAudioContext;
  var S = { on: true, A: null };
  try { S.on = localStorage.getItem('bs-sound') !== 'off'; } catch (e) {}
  var A = null, master, dry, hall, buf;

  function make() {
    if (A || !AudioC) return A;
    try { A = new AudioC(); } catch (e) { return null; }
    S.A = A;
    master = A.createGain(); master.gain.value = 0.85;
    var comp = A.createDynamicsCompressor();
    comp.threshold.value = -18; comp.knee.value = 12; comp.ratio.value = 4; comp.attack.value = 0.003; comp.release.value = 0.25;
    master.connect(comp); comp.connect(A.destination);
    dry = A.createGain(); dry.connect(master);
    // a hall: two seconds of decaying stereo noise as the impulse
    var len = Math.floor(A.sampleRate * 2.4), ir = A.createBuffer(2, len, A.sampleRate);
    for (var ch = 0; ch < 2; ch++) { var d = ir.getChannelData(ch); for (var i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3.4); }
    var conv = A.createConvolver(); conv.buffer = ir;
    var hp = A.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 200;
    hall = A.createGain(); hall.gain.value = 0.55;
    hall.connect(conv); conv.connect(hp); hp.connect(master);
    buf = A.createBuffer(1, A.sampleRate * 2, A.sampleRate);
    var n = buf.getChannelData(0); for (var j = 0; j < n.length; j++) n[j] = Math.random() * 2 - 1;
    return A;
  }
  function wake() { if (!S.on) return; var a = make(); if (a && a.state === 'suspended') { try { a.resume(); } catch (e) {} } }
  ['pointerdown', 'keydown', 'touchend'].forEach(function (t) { document.addEventListener(t, wake, { capture: true, passive: true }); });

  // A sound that starts on one page and ends on the next. The page you leave
  // plays the rise, notes down the chord, and the page you arrive at plays
  // the chord blooming out, so it is never cut off by the page changing.
  var hand = null;
  try {
    var h = JSON.parse(sessionStorage.getItem('bs-hand') || 'null');
    sessionStorage.removeItem('bs-hand');
    if (h && h.c && Date.now() - h.t < 3000) hand = h.c;
  } catch (e) {}
  S.leave = function (chord) { try { sessionStorage.setItem('bs-hand', JSON.stringify({ c: chord, t: Date.now() })); } catch (e) {} };
  function arrive(tries) {
    if (!hand) return;
    if (!S.live()) { if (tries < 20 && S.on) setTimeout(function () { arrive(tries + 1); }, 50); return; }
    var c = hand; hand = null;
    S.tone({ f: 70, f2: 45, dur: 0.9, vol: 0.1 });
    for (var i = 0; i < c.length; i++) {
      S.tone({ at: i * 0.04, f: c[i], f2: c[i] * 1.003, dur: 1.8, vol: 0.03, type: 'triangle', atk: 0.02, wet: 0.7 });
      S.bell({ at: 0.05 + i * 0.06, f: c[i] * 2, ratio: 2.76, index: 1, dur: 1.8, vol: 0.012, pan: -0.45 + i * 0.3 });
    }
    S.noise({ f: 7000, dur: 1, vol: 0.018, ft: 'highpass', atk: 0.1, wet: 0.7 });
  }
  // try at once: allowed if the visitor came here from another BeeSide page
  S.start = function () { if (S.on) { wake(); arrive(0); } };
  S.live = function () { return S.on && !!A && A.state === 'running'; };
  S.now = function () { return A ? A.currentTime : 0; };
  S.pan = function (x) { return Math.max(-0.9, Math.min(0.9, (x / (window.innerWidth || 1)) * 2 - 1)); };
  S.panOf = function (el) { try { var r = el.getBoundingClientRect(); return S.pan(r.left + r.width / 2); } catch (e) { return 0; } };
  S.set = function (on) {
    S.on = on;
    try { localStorage.setItem('bs-sound', on ? 'on' : 'off'); } catch (e) {}
    if (on) wake();
  };

  function out(g, o) {
    var node = g;
    if (o.pan && A.createStereoPanner) { var p = A.createStereoPanner(); p.pan.value = Math.max(-1, Math.min(1, o.pan)); g.connect(p); node = p; }
    node.connect(dry);
    var w = o.wet == null ? 0.25 : o.wet;
    if (w > 0) { var s = A.createGain(); s.gain.value = w; node.connect(s); s.connect(hall); }
  }
  function env(g, t, o, dur) {
    var v = o.vol || 0.05;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(v, t + (o.atk || 0.005));
    if (o.hold) g.gain.setValueAtTime(v, t + o.hold);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  }
  // an oscillator with a pitch glide, a sweeping filter, vibrato and an envelope
  S.tone = function (o) {
    if (!S.live()) return;
    var t = A.currentTime + (o.at || 0), dur = o.dur || 0.2, osc = A.createOscillator(), g = A.createGain(), f = A.createBiquadFilter();
    osc.type = o.type || 'sine';
    osc.frequency.setValueAtTime(o.f, t);
    if (o.f2 && o.f2 !== o.f) osc.frequency.exponentialRampToValueAtTime(o.f2, t + (o.glide || dur));
    if (o.detune) osc.detune.value = o.detune;
    if (o.vib) { var l = A.createOscillator(), lg = A.createGain(); l.frequency.value = o.vib[0]; lg.gain.value = o.vib[1]; l.connect(lg); lg.connect(osc.frequency); l.start(t); l.stop(t + dur + 0.1); }
    f.type = o.ft || 'lowpass'; f.Q.value = o.q || 0.7;
    f.frequency.setValueAtTime(o.cut || 14000, t);
    if (o.cut2) f.frequency.exponentialRampToValueAtTime(o.cut2, t + dur);
    env(g, t, o, dur);
    osc.connect(f); f.connect(g); out(g, o);
    osc.start(t); osc.stop(t + dur + 0.05);
  };
  // filtered noise with a sweep: air, hiss, clicks, rumbles
  S.noise = function (o) {
    if (!S.live()) return;
    var t = A.currentTime + (o.at || 0), dur = o.dur || 0.2, s = A.createBufferSource(), f = A.createBiquadFilter(), g = A.createGain();
    s.buffer = buf; f.type = o.ft || 'bandpass'; f.Q.value = o.q || 1;
    f.frequency.setValueAtTime(o.f || 1000, t);
    if (o.f2) f.frequency.exponentialRampToValueAtTime(o.f2, t + dur);
    env(g, t, o, dur);
    s.connect(f); f.connect(g); out(g, o);
    s.start(t, Math.random() * 1.5); s.stop(t + dur + 0.05);
  };
  // struck glass or metal: frequency modulation that fades out
  S.bell = function (o) {
    if (!S.live()) return;
    var t = A.currentTime + (o.at || 0), dur = o.dur || 1.2, car = A.createOscillator(), mod = A.createOscillator(), mg = A.createGain(), g = A.createGain();
    car.frequency.value = o.f; mod.frequency.value = o.f * (o.ratio || 3.5);
    mg.gain.setValueAtTime(o.f * (o.index || 2), t); mg.gain.exponentialRampToValueAtTime(Math.max(1, o.f * 0.02), t + dur * 0.7);
    mod.connect(mg); mg.connect(car.frequency);
    env(g, t, { vol: o.vol || 0.04, atk: o.atk || 0.002 }, dur);
    car.connect(g); out(g, { pan: o.pan, wet: o.wet == null ? 0.55 : o.wet });
    car.start(t); mod.start(t); car.stop(t + dur + 0.05); mod.stop(t + dur + 0.05);
  };
  S.chord = function (fs, o) { for (var i = 0; i < fs.length; i++) { var c = {}; for (var k in o) c[k] = o[k]; c.f = fs[i]; c.at = (o.at || 0) + i * (o.spread || 0); (o.bell ? S.bell : S.tone)(c); } };
  // a held sound through a filter that opens, until let go
  S.drone = function (o) {
    if (!S.live()) return null;
    var t = A.currentTime, g = A.createGain(), f = A.createBiquadFilter(), os = [], rise = o.rise || 1;
    f.type = 'lowpass'; f.Q.value = o.q || 0.7;
    f.frequency.setValueAtTime(o.cut || 400, t); if (o.cut2) f.frequency.exponentialRampToValueAtTime(o.cut2, t + rise);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(o.vol || 0.03, t + rise);
    o.fs.forEach(function (fr, i) { var x = A.createOscillator(); x.type = o.type || 'sawtooth'; x.frequency.value = fr; x.detune.value = (i % 2 ? 1 : -1) * (o.spreadCents || 7); x.connect(f); x.start(t); os.push(x); });
    f.connect(g); out(g, { pan: o.pan, wet: o.wet == null ? 0.4 : o.wet });
    var done = false;
    return {
      g: g, f: f,
      stop: function (fade) {
        if (done) return; done = true;
        var n = A.currentTime; fade = fade || 0.5;
        g.gain.cancelScheduledValues(n); g.gain.setValueAtTime(Math.max(0.0001, g.gain.value), n); g.gain.exponentialRampToValueAtTime(0.0001, n + fade);
        os.forEach(function (x) { try { x.stop(n + fade + 0.1); } catch (e) {} });
      }
    };
  };
  window.BSND = S;
})();
