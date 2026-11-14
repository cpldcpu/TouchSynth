/* Emulator sound: a Web Audio approximation of one voice card per slot (docs/midi.md 4). Not the card's DSP: the
 * oscillators are Web Audio's (pulse width fixed per note, no PWM), the 4-pole ladder is two resonant biquads, the
 * modal engine a few decaying sines. Good enough to hear what a patch edit does. */
var TSP = window.TSP = window.TSP || {};

TSP.Synth = function (ctx) {
  "use strict";
  var P = TSP.proto.BYKEY, self = this;
  var master = ctx.createGain(), comp = ctx.createDynamicsCompressor();
  master.gain.value = 0.6;
  comp.threshold.value = -10; comp.ratio.value = 4;
  master.connect(comp); comp.connect(ctx.destination);
  this.analyser = ctx.createAnalyser();
  this.analyser.fftSize = 2048;
  comp.connect(this.analyser);
  this.ctx = ctx;

  var noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
  (function () { var d = noiseBuf.getChannelData(0); for (var i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1; })();
  var pulseWaves = {};
  function pulseWave(pw) {                            /* pw 0...127 (64 = 50 %) */
    var duty = Math.min(0.97, Math.max(0.03, pw / 128)), key = Math.round(duty * 64);
    if (!pulseWaves[key]) {
      var n = 64, re = new Float32Array(n), im = new Float32Array(n), dd = key / 64;
      for (var k = 1; k < n; k++) re[k] = 2 / (k * Math.PI) * Math.sin(k * Math.PI * dd);
      pulseWaves[key] = ctx.createPeriodicWave(re, im);
    }
    return pulseWaves[key];
  }
  function tsec(i) { return 0.001 * Math.pow(10000, Math.max(0, i) / 127); }   /* time index -> s */
  function v(vals, key) { return vals[P[key].id]; }
  var MODES = [                                       /* modal models: [ratio, level, decay s] */
    [[1, 1, 1.6], [1.5, 0.5, 1.2], [1.98, 0.35, 0.9], [2.44, 0.25, 0.7], [2.9, 0.15, 0.5]],
    [[1, 1, 0.6], [1.59, 0.5, 0.4], [2.14, 0.3, 0.3], [2.3, 0.2, 0.25]],
    [[1, 1, 0.9], [3.93, 0.4, 0.35], [9.2, 0.15, 0.12]],
    [[1, 0.8, 2.6], [2.0, 0.6, 2.0], [2.76, 0.5, 1.6], [5.4, 0.3, 1.0], [8.93, 0.15, 0.6]]];

  /* one sounding note on one slot; vals = the part's patch values (64), opts: pan, gain, cents (unison detune),
     glideFrom (MIDI note), bend (cents) */
  function Voice(note, vel, vals, opts) {
    var t = ctx.currentTime, nodes = [], oscs = [];
    this.note = note; this.vals = vals;
    var out = ctx.createGain(), pan = ctx.createStereoPanner(), amp = ctx.createGain(), trem = ctx.createGain();
    var f1 = ctx.createBiquadFilter(), f2 = ctx.createBiquadFilter(), mix = ctx.createGain();
    f1.type = f2.type = "lowpass";
    mix.connect(f1); f1.connect(f2); f2.connect(amp); amp.connect(trem); trem.connect(pan); pan.connect(out);
    out.connect(master);
    pan.pan.value = opts.pan || 0;
    out.gain.value = opts.gain === undefined ? 1 : opts.gain;
    this.out = out; this.f1 = f1; this.f2 = f2; this.amp = amp;

    /* LFO */
    var lfo = ctx.createOscillator(), lfoP = ctx.createGain(), lfoC = ctx.createGain(), lfoA = ctx.createGain();
    var lw = v(vals, "LFO_WAVE");
    lfo.type = ["triangle", "square", "sawtooth", "sawtooth", "square"][lw] || "triangle";
    lfo.frequency.value = 0.05 * Math.pow(1000, v(vals, "LFO_RATE") / 127);
    var sign = lw === 3 ? -1 : 1, dly = tsec(v(vals, "LFO_DELAY")) * (v(vals, "LFO_DELAY") ? 1 : 0);
    lfo.connect(lfoP); lfo.connect(lfoC); lfo.connect(lfoA);
    var vib = v(vals, "LFO_PITCH") + (opts.wheel || 0) * v(vals, "WHEEL_VIBRATO");
    [[lfoP, sign * vib], [lfoC, sign * v(vals, "LFO_CUTOFF") * 1200 / 256],
     [lfoA, v(vals, "LFO_AMP") / 254]].forEach(function (g) {
      g[0].gain.setValueAtTime(0, t);
      g[0].gain.linearRampToValueAtTime(g[1], t + dly + 0.01);
    });
    trem.gain.value = 1 - v(vals, "LFO_AMP") / 254;
    lfoA.connect(trem.gain);
    lfoC.connect(f1.detune); lfoC.connect(f2.detune);
    this.lfoP = lfoP;
    nodes.push(lfo);

    /* pitch */
    var bend = opts.bend || 0, cents = opts.cents || 0;
    function hz(n) { return 440 * Math.pow(2, (n - 69) / 12); }
    var penv = v(vals, "PENV_AMT") * 100, pdec = tsec(v(vals, "PENV_DECAY"));
    var glide = opts.glideFrom !== undefined && v(vals, "GLIDE_MODE") > 0 && v(vals, "GLIDE_TIME") > 0;
    function pitchTo(param, base) {
      if (glide) {
        param.setValueAtTime(hz(opts.glideFrom) * base / hz(note), t);
        param.setTargetAtTime(base, t, tsec(v(vals, "GLIDE_TIME")) / 3);
      } else param.setValueAtTime(base, t);
    }
    function detuneTo(param, c) {
      param.setValueAtTime(c + bend + cents + penv, t);
      if (penv) param.setTargetAtTime(c + bend + cents, t, pdec / 3);
      param._base = c + cents;                        /* fine tuning and unison detune, without bend */
    }

    if (v(vals, "ENGINE") === 1) {                   /* modal: decaying partials, struck */
      var model = MODES[v(vals, "MODAL_MODEL")] || MODES[0], dk = Math.pow(2, v(vals, "MODAL_DECAY") / 32);
      var mallet = v(vals, "MALLET") / 40;
      model.forEach(function (m) {
        var o = ctx.createOscillator(), g = ctx.createGain(), lvl = m[1] * Math.exp(-(m[0] - 1) * mallet) * 0.5;
        o.type = "sine";
        pitchTo(o.frequency, hz(note) * m[0]);
        detuneTo(o.detune, 0);
        lfoP.connect(o.detune);
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(lvl, t + 0.002);
        g.gain.setTargetAtTime(0, t + 0.002, m[2] * dk / 4);
        o.connect(g); g.connect(mix); nodes.push(o); oscs.push(o);
      });
      if (v(vals, "MODAL_NOISE")) {
        var nz = ctx.createBufferSource(), ng = ctx.createGain();
        nz.buffer = noiseBuf; nz.loop = true;
        ng.gain.setValueAtTime(v(vals, "MODAL_NOISE") / 127 * 0.6, t);
        ng.gain.setTargetAtTime(0, t, 0.03);
        nz.connect(ng); ng.connect(mix); nodes.push(nz);
      }
      this.modal = true;
    } else {
      [1, 2, 3].forEach(function (k) {
        var w = v(vals, "OSC" + k + "_WAVE");
        if (!w) return;
        var o = ctx.createOscillator(), g = ctx.createGain();
        if (w === 1) o.type = "sawtooth"; else o.setPeriodicWave(pulseWave(v(vals, "OSC" + k + "_PW")));
        pitchTo(o.frequency, hz(note + v(vals, "OSC" + k + "_COARSE")));
        detuneTo(o.detune, v(vals, "OSC" + k + "_FINE"));
        lfoP.connect(o.detune);
        g.gain.value = v(vals, "OSC" + k + "_LEVEL") / 127 * 0.35;
        o.connect(g); g.connect(mix); nodes.push(o); oscs.push(o);
      });
      if (v(vals, "NOISE_LEVEL")) {
        var n2 = ctx.createBufferSource(), g2 = ctx.createGain();
        n2.buffer = noiseBuf; n2.loop = true;
        g2.gain.value = v(vals, "NOISE_LEVEL") / 127 * 0.3;
        n2.connect(g2); g2.connect(mix); nodes.push(n2);
      }
    }
    this.oscs = oscs;

    /* filter: cutoff in 1/256 octave above 20 Hz, key tracking around C4, envelope on detune (cents) */
    this.setFilter(vals, opts.cutOff || 0, opts.resOff || 0);
    var amt = v(vals, "FENV_AMT") * (1 - v(vals, "FENV_VEL") / 127 * (1 - vel / 127)) * 1200 / 256;
    var fa = tsec(v(vals, "FENV_A")), fd = tsec(v(vals, "FENV_D")), fs = v(vals, "FENV_S") / 127;
    [f1, f2].forEach(function (f) {
      f.detune.setValueAtTime(0, t);
      f.detune.linearRampToValueAtTime(amt, t + fa);
      f.detune.setTargetAtTime(amt * fs, t + fa, fd / 3);
    });
    this.famt = amt;

    /* amplitude */
    var lvl = v(vals, "VOLUME") / 127 * (1 - v(vals, "AENV_VEL") / 127 * (1 - vel / 127));
    var aa = tsec(v(vals, "AENV_A")), ad = tsec(v(vals, "AENV_D")), as = v(vals, "AENV_S") / 127;
    if (this.modal) { aa = 0.001; as = 1; }
    amp.gain.setValueAtTime(0, t);
    amp.gain.linearRampToValueAtTime(lvl, t + aa);
    amp.gain.setTargetAtTime(lvl * as, t + aa, ad / 3);
    this.nodes = nodes;
    nodes.forEach(function (n) { n.start(t); });
  }
  Voice.prototype.setFilter = function (vals, cutOff, resOff) {
    var kt = v(vals, "KEYTRACK") * (this.note - 60) / 12;
    var c = Math.max(0, Math.min(2700, v(vals, "CUTOFF") + kt + cutOff));
    var f = Math.min(ctx.sampleRate * 0.45, 20 * Math.pow(2, c / 256));
    var r = Math.max(0, Math.min(255, v(vals, "RESONANCE") + resOff)) / 255;
    var now = ctx.currentTime;
    this.f1.frequency.setTargetAtTime(f, now, 0.01);
    this.f2.frequency.setTargetAtTime(f, now, 0.01);
    this.f1.Q.setTargetAtTime(0.5 + r * r * 18, now, 0.01);
    this.f2.Q.setTargetAtTime(0.707, now, 0.01);
  };
  Voice.prototype.bend = function (cents) {
    var now = ctx.currentTime;
    this.oscs.forEach(function (o) {
      o.detune.cancelScheduledValues(now);
      o.detune.setTargetAtTime((o.detune._base || 0) + cents, now, 0.01);
    });
  };
  Voice.prototype.release = function () {
    var now = ctx.currentTime, vals = this.vals, rel = this.modal ? 0.3 : tsec(v(vals, "AENV_R"));
    var frel = tsec(v(vals, "FENV_R"));
    this.amp.gain.cancelScheduledValues(now);
    this.amp.gain.setValueAtTime(this.amp.gain.value, now);
    this.amp.gain.setTargetAtTime(0, now, rel / 3);
    [this.f1, this.f2].forEach(function (f) {
      f.detune.cancelScheduledValues(now); f.detune.setValueAtTime(f.detune.value, now);
      f.detune.setTargetAtTime(0, now, frel / 3);
    });
    var nodes = this.nodes, out = this.out;
    this.nodes.forEach(function (n) { try { n.stop(now + rel * 2 + 0.05); } catch (e) {} });
    setTimeout(function () { try { out.disconnect(); } catch (e) {} }, (rel * 2 + 0.2) * 1000);
    this.released = true;
  };
  Voice.prototype.kill = function () {
    var now = ctx.currentTime;
    this.nodes.forEach(function (n) { try { n.stop(now + 0.01); } catch (e) {} });
    var out = this.out;
    setTimeout(function () { try { out.disconnect(); } catch (e) {} }, 50);
  };

  var slots = {};                                     /* slot -> Voice */
  this.noteOn = function (slot, note, vel, vals, opts) {
    if (slots[slot]) slots[slot].kill();
    slots[slot] = new Voice(note, vel, vals, opts || {});
  };
  this.noteOff = function (slot) { if (slots[slot] && !slots[slot].released) slots[slot].release(); };
  this.allOff = function () { Object.keys(slots).forEach(function (s) { slots[s].kill(); }); slots = {}; };
  this.update = function (slot, vals, cutOff, resOff) {     /* live edits: the filter of a sounding note */
    var vo = slots[slot];
    if (vo && !vo.released) { vo.vals = vals; vo.setFilter(vals, cutOff || 0, resOff || 0); }
  };
  this.bend = function (slot, cents) { if (slots[slot]) slots[slot].bend(cents); };
};
