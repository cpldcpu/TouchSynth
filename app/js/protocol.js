/* TouchSynth Poly host protocol (docs/sysex.md): NRPN and SysEx encoding / decoding, shared by the app and the
 * emulator. Plain script (no modules), so the app opens from disk; everything lives in window.TSP. */
var TSP = window.TSP = window.TSP || {};

TSP.proto = (function () {
  "use strict";
  var HDR = [0xF0, 0x7D, 0x54, 0x50];
  var CMD = {
    PATCH_REQ: 0x01, PATCH_DUMP: 0x02, STORE: 0x03, NAMES_REQ: 0x04, NAMES: 0x05,
    SETUP_REQ: 0x10, SETUP_DUMP: 0x11, CARDS_REQ: 0x20, CARDS: 0x21, CALIBRATE: 0x22, ACK: 0x7E
  };
  var CMD_NAME = {};
  Object.keys(CMD).forEach(function (k) { CMD_NAME[CMD[k]] = k; });
  var EDIT = 0x40;                                    /* PATCH slot of part p's edit buffer: 0x40 + p */
  var NPARAM = 64, NAMELEN = 16, NPROG = 64, NPART = 8, NSLOT = 8;
  var PART_LEN = 10, CARD_LEN = 37;

  /* parameter table (params.js) */
  var PT = TSP.PARAMTABLE, BYID = {}, BYKEY = {};
  PT.params.forEach(function (p) { BYID[p.id] = p; BYKEY[p.key] = p; });

  function clampParam(id, v) {
    var p = BYID[id];
    if (!p) return 0;
    v = Math.round(v);
    return v < p.min ? p.min : v > p.max ? p.max : v;
  }
  function defaults() {
    var v = new Array(NPARAM).fill(0);
    PT.params.forEach(function (p) { v[p.id] = p.default; });
    return v;
  }

  /* 7-bit packing */
  function i16(v) { v &= 0xFFFF; return [v & 0x7F, (v >> 7) & 0x7F, (v >> 14) & 0x03]; }
  function rdI16(b, o) { var v = b[o] | (b[o + 1] << 7) | ((b[o + 2] & 3) << 14); return v >= 0x8000 ? v - 0x10000 : v; }
  function name16(s) {
    var out = [];
    s = (s || "").slice(0, NAMELEN);
    for (var i = 0; i < NAMELEN; i++) {
      var c = i < s.length ? s.charCodeAt(i) : 0x20;
      out.push(c >= 0x20 && c <= 0x7E ? c : 0x3F);
    }
    return out;
  }
  function rdName(b, o) { return String.fromCharCode.apply(null, b.slice(o, o + NAMELEN)).replace(/\s+$/, ""); }

  function sysex(cmd, data, dev) {
    return HDR.concat([dev === undefined ? 0x7F : dev, cmd], data || [], [0xF7]);
  }
  /* -> {dev, cmd, data} or null if not ours */
  function parseSysex(b) {
    if (b.length < 7 || b[0] !== 0xF0 || b[b.length - 1] !== 0xF7) return null;
    for (var i = 1; i < 4; i++) if (b[i] !== HDR[i]) return null;
    return { dev: b[4], cmd: b[5], data: Array.prototype.slice.call(b, 6, b.length - 1) };
  }

  /* messages */
  function patchDump(slot, name, values, dev) {
    var d = [slot].concat(name16(name));
    for (var i = 0; i < NPARAM; i++) d = d.concat(i16(values[i] || 0));
    return sysex(CMD.PATCH_DUMP, d, dev);
  }
  function rdPatch(d) {
    if (d.length < 1 + NAMELEN + 3 * NPARAM) return null;
    var v = [];
    for (var i = 0; i < NPARAM; i++) v.push(rdI16(d, 1 + NAMELEN + 3 * i));
    return { slot: d[0], name: rdName(d, 1), values: v };
  }
  function namesMsg(names, dev) {
    var d = [];
    for (var i = 0; i < NPROG; i++) d = d.concat(name16(names[i]));
    return sysex(CMD.NAMES, d, dev);
  }
  function rdNames(d) {
    var out = [];
    for (var i = 0; i < NPROG; i++) out.push(rdName(d, i * NAMELEN));
    return out;
  }
  function setupDump(setup, dev) {
    var d = [];
    setup.parts.forEach(function (p) {
      d.push(p.channel, p.keyLo, p.keyHi, p.mask & 0x7F, (p.mask >> 7) & 1, p.mode, p.program, p.volume,
             p.transpose + 64, p.pan);
    });
    d = d.concat(i16(setup.tuning || 0), [setup.flags || 0]);
    return sysex(CMD.SETUP_DUMP, d, dev);
  }
  function rdSetup(d) {
    if (d.length < NPART * PART_LEN + 4) return null;
    var parts = [];
    for (var k = 0; k < NPART; k++) {
      var o = k * PART_LEN;
      parts.push({ channel: d[o], keyLo: d[o + 1], keyHi: d[o + 2], mask: d[o + 3] | ((d[o + 4] & 1) << 7),
                   mode: d[o + 5], program: d[o + 6], volume: d[o + 7], transpose: d[o + 8] - 64, pan: d[o + 9] });
    }
    return { parts: parts, tuning: rdI16(d, NPART * PART_LEN), flags: d[NPART * PART_LEN + 3] };
  }
  function cardsMsg(cards, dev) {
    var d = [];
    cards.forEach(function (c) {
      var uid = [];
      for (var i = 0; i < 8; i++) { var b = (c.uid && c.uid[i]) || 0; uid.push(b >> 4, b & 15); }
      d = d.concat([c.present ? 1 : 0, c.kind || 0], uid, i16(c.fw || 0), [c.caps || 0, c.state || 0],
                   i16(c.ppm || 0), [Math.min(127, c.load || 0)], i16(c.crc || 0), i16(c.late || 0),
                   i16(c.underruns || 0), [(c.calibrated ? 1 : 0) | (c.busy ? 2 : 0)]);
    });
    return sysex(CMD.CARDS, d, dev);
  }
  function rdCards(d) {
    var out = [];
    for (var k = 0; k < NSLOT; k++) {
      var o = k * CARD_LEN;
      if (d.length < o + CARD_LEN) break;
      var uid = [];
      for (var i = 0; i < 8; i++) uid.push((d[o + 2 + 2 * i] << 4) | d[o + 3 + 2 * i]);
      out.push({ slot: k + 1, present: !!d[o], kind: d[o + 1], uid: uid, fw: rdI16(d, o + 18), caps: d[o + 21],
                 state: d[o + 22], ppm: rdI16(d, o + 23), load: d[o + 26], crc: rdI16(d, o + 27) & 0xFFFF,
                 late: rdI16(d, o + 30) & 0xFFFF, underruns: rdI16(d, o + 33) & 0xFFFF,
                 calibrated: !!(d[o + 36] & 1), busy: !!(d[o + 36] & 2) });
    }
    return out;
  }
  function ack(cmd, status, dev) { return sysex(CMD.ACK, [cmd, status || 0], dev); }

  /* NRPN: d spans [min, max] (docs/sysex.md 1) */
  function toD(p, v) { return p.max === p.min ? 0 : Math.round((v - p.min) * 16383 / (p.max - p.min)); }
  function fromD(p, d) { return p.min + Math.round(d * (p.max - p.min) / 16383); }
  function nrpn(ch, id, v) {                          /* ch 1...16 -> four CC messages */
    var p = BYID[id], d = p ? toD(p, clampParam(id, v)) : 0, s = 0xB0 | ((ch - 1) & 15);
    return [[s, 0x63, 0], [s, 0x62, id & 0x7F], [s, 0x06, d >> 7], [s, 0x26, d & 0x7F]];
  }

  /* a short text for the MIDI monitor */
  var NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  function noteName(n) { return NOTE[n % 12] + (Math.floor(n / 12) - 1); }
  function describe(b) {
    if (!b.length) return "";
    var s = b[0];
    if (s === 0xF0) {
      var m = parseSysex(b);
      if (m) return "SysEx " + (CMD_NAME[m.cmd] || ("0x" + m.cmd.toString(16))) + " (" + b.length + " bytes)";
      if (b[1] === 0x7E && b[3] === 0x06) return "SysEx identity " + (b[4] === 1 ? "request" : "reply");
      return "SysEx (" + b.length + " bytes)";
    }
    var ch = (s & 15) + 1, t = s & 0xF0;
    if (t === 0x90 && b[2]) return "ch" + ch + " note on " + noteName(b[1]) + " vel " + b[2];
    if (t === 0x80 || t === 0x90) return "ch" + ch + " note off " + noteName(b[1]);
    if (t === 0xB0) return "ch" + ch + " CC " + b[1] + " = " + b[2];
    if (t === 0xC0) return "ch" + ch + " program " + (b[1] + 1);
    if (t === 0xE0) return "ch" + ch + " bend " + (((b[2] << 7) | b[1]) - 8192);
    if (t === 0xD0) return "ch" + ch + " pressure " + b[1];
    return b.map(function (x) { return x.toString(16).padStart(2, "0"); }).join(" ");
  }

  return {
    CMD: CMD, CMD_NAME: CMD_NAME, EDIT: EDIT, NPARAM: NPARAM, NPROG: NPROG, NPART: NPART, NSLOT: NSLOT,
    PARAMS: PT.params, GROUPS: PT.groups, BYID: BYID, BYKEY: BYKEY, clampParam: clampParam, defaults: defaults,
    i16: i16, rdI16: rdI16, sysex: sysex, parseSysex: parseSysex, patchDump: patchDump, rdPatch: rdPatch,
    namesMsg: namesMsg, rdNames: rdNames, setupDump: setupDump, rdSetup: rdSetup, cardsMsg: cardsMsg,
    rdCards: rdCards, ack: ack, toD: toD, fromD: fromD, nrpn: nrpn, describe: describe, noteName: noteName,
    IDENTITY_REQ: [0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]
  };
})();
