/* Emulated instrument: what the controller and its cards answer over MIDI (docs/sysex.md), so the app can be used
 * and tested without hardware. Programs, parts (docs/midi.md 2), the edit buffers, six voice cards with plausible
 * status, voice allocation over the parts' slot masks; sound through TSP.Synth when an AudioContext is given. */
var TSP = window.TSP = window.TSP || {};

TSP.Emulator = function (send) {
  "use strict";
  var pr = TSP.proto, C = pr.CMD, K = pr.BYKEY, self = this;
  var DEV = 0;
  this.synth = null;

  /* the first program set (midi.md 5); values: parameter key -> value over the defaults */
  var BANK = [
    ["Moog Lead", { OSC2_WAVE: 1, OSC2_FINE: 8, OSC3_WAVE: 2, OSC3_COARSE: -12, CUTOFF: 1500, RESONANCE: 110,
                    FENV_AMT: 900, GLIDE_TIME: 30, GLIDE_MODE: 2, LFO_RATE: 75, WHEEL_VIBRATO: 40 }],
    ["Moog Bass", { OSC2_WAVE: 1, OSC2_COARSE: -12, OSC3_WAVE: 2, OSC3_COARSE: -24, CUTOFF: 1100, RESONANCE: 90,
                    FENV_AMT: 1100, FENV_D: 50, FENV_S: 10, AENV_S: 90, AENV_R: 25 }],
    ["Open Saws", { OSC2_WAVE: 1, OSC2_FINE: 12, OSC3_WAVE: 1, OSC3_COARSE: 0, OSC3_FINE: -10, CUTOFF: 2100,
                    RESONANCE: 30, FENV_AMT: 300 }],
    ["Acid Bass", { OSC1_WAVE: 1, CUTOFF: 900, RESONANCE: 190, FENV_AMT: 1500, FENV_D: 45, FENV_S: 0,
                    AENV_D: 55, AENV_S: 80, AENV_R: 20, GLIDE_TIME: 25, GLIDE_MODE: 2 }],
    ["Lead", { OSC2_WAVE: 2, OSC2_COARSE: -12, OSC2_LEVEL: 80, CUTOFF: 1800, RESONANCE: 80 }],
    ["Brass", { OSC2_WAVE: 1, OSC2_FINE: 6, CUTOFF: 1200, RESONANCE: 40, FENV_A: 35, FENV_D: 70, FENV_S: 70,
                FENV_AMT: 900, AENV_A: 30, AENV_S: 110 }],
    ["Strings", { OSC2_WAVE: 1, OSC2_FINE: 9, OSC3_WAVE: 1, OSC3_COARSE: 12, OSC3_FINE: -7, OSC3_LEVEL: 60,
                  CUTOFF: 1900, RESONANCE: 20, FENV_AMT: 200, AENV_A: 75, AENV_R: 85, LFO_PITCH: 8, LFO_RATE: 55 }],
    ["PWM Pad", { OSC1_WAVE: 2, OSC1_PW: 40, OSC1_PWM: 70, OSC2_WAVE: 2, OSC2_PW: 90, OSC2_FINE: 6,
                  CUTOFF: 1700, AENV_A: 70, AENV_R: 90, LFO_RATE: 35 }],
    ["Organ", { OSC1_WAVE: 2, OSC2_WAVE: 2, OSC2_COARSE: 12, OSC2_FINE: 0, OSC3_WAVE: 2, OSC3_COARSE: 19,
                OSC3_LEVEL: 70, CUTOFF: 2300, RESONANCE: 0, FENV_AMT: 0, AENV_A: 0, AENV_D: 0, AENV_S: 127,
                AENV_R: 15 }],
    ["Pedal Bass", { OSC2_WAVE: 2, OSC2_COARSE: -12, CUTOFF: 1000, RESONANCE: 60, FENV_AMT: 600, AENV_S: 110 }],
    ["Wind", { OSC1_WAVE: 0, NOISE_LEVEL: 120, CUTOFF: 1500, RESONANCE: 215, FENV_AMT: 0, AENV_A: 80,
               AENV_R: 90, LFO_CUTOFF: 300, LFO_RATE: 30 }],
    ["Theremin", { OSC1_WAVE: 2, OSC1_PW: 64, CUTOFF: 1600, RESONANCE: 60, GLIDE_TIME: 55, GLIDE_MODE: 1,
                   LFO_PITCH: 25, LFO_RATE: 80, AENV_A: 40, AENV_R: 70 }],
    ["Arp Pluck", { OSC2_WAVE: 1, OSC2_FINE: 5, CUTOFF: 1200, RESONANCE: 120, FENV_AMT: 1300, FENV_D: 40,
                    FENV_S: 0, AENV_D: 45, AENV_S: 0, AENV_R: 40 }],
    ["Sweep", { OSC2_WAVE: 1, OSC2_FINE: 10, CUTOFF: 900, RESONANCE: 180, FENV_AMT: 1800, FENV_A: 95,
                FENV_D: 100, AENV_A: 40, AENV_R: 95 }],
    ["Unison Lead", { OSC2_WAVE: 1, OSC2_FINE: 15, CUTOFF: 1900, RESONANCE: 70, UNISON_SPREAD: 25 }],
    ["Kettle", { ENGINE: 1, MODAL_MODEL: 0, MALLET: 25, CUTOFF: 2400, RESONANCE: 0, FENV_AMT: 0 }],
    ["Tom", { ENGINE: 1, MODAL_MODEL: 1, MALLET: 15, PENV_AMT: 5, PENV_DECAY: 30, CUTOFF: 2300, FENV_AMT: 0 }],
    ["Marimba", { ENGINE: 1, MODAL_MODEL: 2, MALLET: 30, CUTOFF: 2500, FENV_AMT: 0 }],
    ["Bell", { ENGINE: 1, MODAL_MODEL: 3, MALLET: 10, MODAL_DECAY: 20, CUTOFF: 2560, FENV_AMT: 0 }],
    ["Kick", { OSC1_WAVE: 2, OSC1_COARSE: -24, OSC1_LEVEL: 127, PENV_AMT: 24, PENV_DECAY: 25, CUTOFF: 1000,
               RESONANCE: 150, FENV_AMT: 0, AENV_A: 0, AENV_D: 62, AENV_S: 0, AENV_R: 30, VOLUME: 127 }],
    ["Snare", { ENGINE: 1, MODAL_MODEL: 1, MODAL_NOISE: 110, MALLET: 5, CUTOFF: 2400, FENV_AMT: 0 }],
    ["Hat", { OSC1_WAVE: 0, NOISE_LEVEL: 127, CUTOFF: 2500, RESONANCE: 60, FENV_AMT: 0, AENV_A: 0, AENV_D: 20,
              AENV_S: 0, AENV_R: 15 }],
    ["Drum Kit", { ENGINE: 1, MODAL_MODEL: 0 }]
  ];
  function patchFrom(over) {
    var v = pr.defaults();
    Object.keys(over).forEach(function (k) { v[K[k].id] = pr.clampParam(K[k].id, over[k]); });
    return v;
  }
  var programs = [];
  for (var i = 0; i < pr.NPROG; i++)
    programs.push(i < BANK.length ? { name: BANK[i][0], values: patchFrom(BANK[i][1]) }
                                  : { name: "Init " + (i + 1), values: pr.defaults() });
  function newPart(k) {
    return { channel: k === 0 ? 1 : 0, keyLo: 0, keyHi: 127, mask: 0xFF, mode: 0, program: 0, volume: 100,
             transpose: 0, pan: 64 };
  }
  var setup = { parts: [], tuning: 0, flags: 0 };
  var edit = [];
  for (var p = 0; p < pr.NPART; p++) {
    setup.parts.push(newPart(p));
    edit.push({ name: programs[0].name, values: programs[0].values.slice() });
  }
  /* cards: six voice cards in slots 1-6, slots 7 and 8 empty */
  function rnd(seed) { var x = Math.sin(seed) * 10000; return x - Math.floor(x); }
  var cards = [];
  for (var s = 0; s < pr.NSLOT; s++) {
    var uid = [];
    for (var b = 0; b < 8; b++) uid.push(Math.floor(rnd(s * 17 + b + 1) * 256));
    cards.push({ present: s < 6, kind: 0, uid: uid, fw: 3, caps: 0, state: s < 6 ? 3 : 0,
                 ppm: Math.round((rnd(s + 99) - 0.5) * 700), load: 8, crc: 0, late: 0, underruns: 0,
                 calibrated: false, busy: false });
  }
  this.state = { programs: programs, setup: setup, edit: edit, cards: cards };

  /* voices: slot -> {part, note, t, held} */
  var voices = {}, clock = 0;
  var perf = [];                                      /* per part: wheel, cutoff / resonance CC offsets, bend */
  for (var q = 0; q < pr.NPART; q++) perf.push({ wheel: 0, cut: 0, res: 0, bend: 0, sustain: false, last: undefined });
  function voiceSlots(part) {
    var out = [];
    for (var s = 0; s < pr.NSLOT; s++)
      if ((setup.parts[part].mask >> s) & 1 && cards[s].present && cards[s].kind === 0 && !cards[s].busy) out.push(s);
    return out;
  }
  function pick(part) {                               /* free, else the oldest released, else the oldest held */
    var sl = voiceSlots(part), best = null, bt = Infinity;
    for (var i = 0; i < sl.length; i++) if (!voices[sl[i]]) return sl[i];
    [false, true].forEach(function (held) {
      if (best !== null) return;
      sl.forEach(function (s) { var vo = voices[s]; if (vo.held === held && vo.t < bt) { bt = vo.t; best = s; } });
    });
    return best;
  }
  function panOf(part) { return (setup.parts[part].pan - 64) / 64; }
  function sound(slot, part, note, vel, cents) {
    var pp = setup.parts[part], pe = perf[part], vals = edit[part].values;
    voices[slot] = { part: part, note: note, t: ++clock, held: true };
    if (self.synth) {
      self.synth.noteOn(slot, note + pp.transpose, vel, vals, {
        pan: panOf(part), gain: pp.volume / 127, cents: cents || 0, wheel: pe.wheel,
        bend: pe.bend * vals[K.BEND_RANGE.id] * 100, cutOff: pe.cut, resOff: pe.res,
        glideFrom: pe.last !== undefined ? pe.last + pp.transpose : undefined });
    }
    cards[slot].load = vals[K.ENGINE.id] ? 38 : 24;
  }
  function release(slot) {
    var vo = voices[slot];
    if (!vo) return;
    vo.held = false;
    if (self.synth) self.synth.noteOff(slot);
    setTimeout(function () { if (voices[slot] === vo) { delete voices[slot]; cards[slot].load = 8; } }, 1500);
  }
  function noteOn(part, note, vel) {
    var pp = setup.parts[part], pe = perf[part];
    if (note < pp.keyLo || note > pp.keyHi) return;
    if (pp.mode === 3) {                              /* unison: every slot of the mask */
      var sl = voiceSlots(part), spread = edit[part].values[K.UNISON_SPREAD.id];
      sl.forEach(function (s, i) { sound(s, part, note, vel, sl.length > 1 ? (i / (sl.length - 1) - 0.5) * 2 * spread : 0); });
    } else if (pp.mode === 1 || pp.mode === 2) {      /* mono / legato: one slot, last note */
      var s1 = voiceSlots(part)[0];
      if (s1 !== undefined) sound(s1, part, note, vel);
    } else {
      var s2 = pick(part);
      if (s2 !== null) sound(s2, part, note, vel);
    }
    pe.last = note;
  }
  function noteOff(part, note) {
    if (perf[part].sustain) { perf[part].pending = (perf[part].pending || []).concat([note]); return; }
    Object.keys(voices).forEach(function (s) {
      var vo = voices[s];
      if (vo.part === part && vo.note === note && vo.held) release(+s);
    });
  }
  function allOff(part) {
    Object.keys(voices).forEach(function (s) { if (part === undefined || voices[s].part === part) release(+s); });
  }
  function partsOn(ch) {
    var out = [];
    setup.parts.forEach(function (pp, k) { if (pp.channel === ch) out.push(k); });
    return out;
  }
  function liveFilter(part) {
    if (!self.synth) return;
    Object.keys(voices).forEach(function (s) {
      if (voices[s].part === part) self.synth.update(+s, edit[part].values, perf[part].cut, perf[part].res);
    });
  }

  /* MIDI in */
  var nrpnState = [];
  for (var c = 0; c <= 16; c++) nrpnState.push({ msb: 127, lsb: 127, dmsb: 0 });
  function reply(msg) { setTimeout(function () { send(msg); }, 3); }
  function cc(ch, num, val) {
    var parts = partsOn(ch), st = nrpnState[ch];
    if (num === 0x63) st.msb = val;
    else if (num === 0x62) st.lsb = val;
    else if (num === 0x06) st.dmsb = val;
    else if (num === 0x26) {
      if (st.msb === 0 && pr.BYID[st.lsb]) {
        var p = pr.BYID[st.lsb], value = pr.fromD(p, (st.dmsb << 7) | val);
        parts.forEach(function (k) { edit[k].values[p.id] = value; liveFilter(k); });
        if (self.onParam) self.onParam(ch, p.id, value);
      }
    } else parts.forEach(function (k) {
      var pe = perf[k];
      if (num === 1) pe.wheel = val / 127;
      else if (num === 7) setup.parts[k].volume = val;
      else if (num === 74) { pe.cut = (val - 64) * 16; liveFilter(k); }
      else if (num === 71) { pe.res = (val - 64) * 2; liveFilter(k); }
      else if (num === 64) {
        pe.sustain = val >= 64;
        if (!pe.sustain && pe.pending) { var pend = pe.pending; pe.pending = []; pend.forEach(function (n) { noteOff(k, n); }); }
      } else if (num === 120 || num === 123) allOff(k);
    });
  }
  function onSysex(b) {
    if (b.length === 6 && b[1] === 0x7E && b[3] === 0x06 && b[4] === 0x01) {
      reply([0xF0, 0x7E, DEV, 0x06, 0x02, 0x7D, 0, 0, 0, 0, 0, 1, 0, 0, 0xF7]);
      return;
    }
    var m = pr.parseSysex(b);
    if (!m || (m.dev !== 0x7F && m.dev !== DEV)) return;
    var d = m.data;
    switch (m.cmd) {
      case C.PATCH_REQ:
        var src = d[0] >= pr.EDIT ? edit[(d[0] - pr.EDIT) & 7] : programs[d[0] & 63];
        reply(pr.patchDump(d[0], src.name, src.values, DEV));
        break;
      case C.PATCH_DUMP:
        var pd = pr.rdPatch(d);
        if (!pd) { reply(pr.ack(m.cmd, 2, DEV)); break; }
        pd.values = pd.values.map(function (x, id) { return pr.BYID[id] ? pr.clampParam(id, x) : 0; });
        if (pd.slot >= pr.EDIT) { edit[(pd.slot - pr.EDIT) & 7] = { name: pd.name, values: pd.values }; liveFilter((pd.slot - pr.EDIT) & 7); }
        else programs[pd.slot & 63] = { name: pd.name, values: pd.values };
        reply(pr.ack(m.cmd, 0, DEV));
        break;
      case C.STORE:
        var e = edit[d[0] & 7];
        programs[d[1] & 63] = { name: e.name, values: e.values.slice() };
        reply(pr.ack(m.cmd, 0, DEV));
        break;
      case C.NAMES_REQ:
        reply(pr.namesMsg(programs.map(function (x) { return x.name; }), DEV));
        break;
      case C.SETUP_REQ:
        reply(pr.setupDump(setup, DEV));
        break;
      case C.SETUP_DUMP:
        var su = pr.rdSetup(d);
        if (!su) { reply(pr.ack(m.cmd, 2, DEV)); break; }
        allOff();
        setup.parts = su.parts; setup.tuning = su.tuning; setup.flags = su.flags;
        self.state.setup = setup;
        reply(pr.ack(m.cmd, 0, DEV));
        break;
      case C.CARDS_REQ:
        reply(pr.cardsMsg(cards, DEV));
        break;
      case C.CALIBRATE:
        var mask = (d[0] & 0x7F) | ((d[1] & 1) << 7);
        cards.forEach(function (cd, s) {
          if ((mask >> s) & 1 && cd.present) {
            cd.busy = true; cd.calibrated = false;
            setTimeout(function () { cd.busy = false; cd.calibrated = true; }, 2500 + s * 300);
          }
        });
        reply(pr.ack(m.cmd, 0, DEV));
        break;
      default:
        reply(pr.ack(m.cmd, 1, DEV));
    }
  }
  this.receive = function (b) {
    b = Array.prototype.slice.call(b);
    if (!b.length) return;
    if (b[0] === 0xF0) { onSysex(b); return; }
    var t = b[0] & 0xF0, ch = (b[0] & 15) + 1;
    if (t === 0x90 && b[2]) partsOn(ch).forEach(function (k) { noteOn(k, b[1], b[2]); });
    else if (t === 0x80 || t === 0x90) partsOn(ch).forEach(function (k) { noteOff(k, b[1]); });
    else if (t === 0xB0) cc(ch, b[1], b[2]);
    else if (t === 0xC0) partsOn(ch).forEach(function (k) {
      setup.parts[k].program = b[1] & 63;
      var src = programs[b[1] & 63];
      edit[k] = { name: src.name, values: src.values.slice() };
    });
    else if (t === 0xE0) partsOn(ch).forEach(function (k) {
      perf[k].bend = (((b[2] << 7) | b[1]) - 8192) / 8192;
      Object.keys(voices).forEach(function (s) {
        if (voices[s].part === k && self.synth) self.synth.bend(+s, perf[k].bend * edit[k].values[K.BEND_RANGE.id] * 100);
      });
    });
  };
  this.activeSlots = function () {
    var o = {};
    Object.keys(voices).forEach(function (s) { o[s] = voices[s].held ? 2 : 1; });
    return o;
  };

  /* status drift: clock error wander, the odd late event under load */
  this.timer = setInterval(function () {
    cards.forEach(function (cd) {
      if (!cd.present) return;
      cd.ppm += Math.round((Math.random() - 0.5) * 20);
      cd.ppm = Math.max(-900, Math.min(900, cd.ppm));
    });
  }, 500);
  this.close = function () { clearInterval(this.timer); allOff(); };
};
