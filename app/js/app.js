/* TouchSynth Poly browser app: the views and the model mirrored from the instrument (docs/sysex.md). */
(function () {
  "use strict";
  var pr = TSP.proto, C = pr.CMD;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var el = function (tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") e.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), attrs[k]);
      else if (k === "class") e.className = attrs[k];
      else e.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  };

  /* ------------------------------------------------------------------ model */
  var M = {
    link: null, connected: false, part: 0,
    names: new Array(pr.NPROG).fill(""), edit: null, setup: null, cards: null,
    waiting: {}, bankCollect: null
  };
  var MODES = ["poly", "mono", "legato", "unison", "kit"];
  var STATES = ["standalone", "trim", "listen", "synced", "SYNC lost"];
  var audioCtx = null, synth = null;

  /* ------------------------------------------------------------------ link and messages */
  function send(b, quiet) {
    if (!M.link) return;
    M.link.send(b);
    if (!quiet) log("out", b);
  }
  function sendSysex(cmd, data) { send(pr.sysex(cmd, data || [])); }
  function partChannel() { return M.setup ? M.setup.parts[M.part].channel : 1; }

  function onMessage(b) {
    log("in", b);
    if (b[0] !== 0xF0) return;
    var m = pr.parseSysex(b);
    if (!m) {
      if (b[1] === 0x7E && b[3] === 0x06 && b[4] === 0x02) status("instrument identified (firmware " + b.slice(10, 14).join(".") + ")");
      return;
    }
    if (m.cmd === C.NAMES) { M.names = pr.rdNames(m.data); renderLibrary(); renderSetup(); renderPartSelect(); }
    else if (m.cmd === C.PATCH_DUMP) {
      var pd = pr.rdPatch(m.data);
      if (!pd) return;
      if (M.bankCollect && pd.slot < pr.NPROG) { M.bankCollect.got[pd.slot] = b; checkBank(); }
      else if (pd.slot === pr.EDIT + M.part) { M.edit = pd; renderEditor(); }
    } else if (m.cmd === C.SETUP_DUMP) { M.setup = pr.rdSetup(m.data); renderSetup(); renderPartSelect(); }
    else if (m.cmd === C.CARDS) { M.cards = pr.rdCards(m.data); renderInstrument(); }
    else if (m.cmd === C.ACK) {
      var what = pr.CMD_NAME[m.data[0]] || m.data[0], st = m.data[1];
      if (st) status(what + ": refused (" + ["ok", "unknown command", "bad data", "busy"][st] + ")", true);
      else if (m.data[0] === C.STORE) { status("stored"); sendSysex(C.NAMES_REQ); }
    }
  }

  function connect(which) {
    if (M.link) { M.link.close(); M.link = null; }
    if (synth) { synth.allOff(); }
    M.connected = false;
    var p;
    if (which === "emulator") {
      M.link = new TSP.EmulatorLink();
      p = M.link.open(onMessage).then(function () {
        if (synth) M.link.emulator.synth = synth;
      });
    } else {
      var io = midiPorts[which];
      M.link = new TSP.MidiLink(io.output, io.input);
      p = M.link.open(onMessage);
    }
    return p.then(function () {
      M.connected = true;
      $("#conn-state").textContent = M.link.isEmulator ? "emulator" : "connected";
      $("#conn-state").className = "pill ok";
      $("#sound").disabled = !M.link.isEmulator;
      status("connected to " + M.link.name);
      send(pr.IDENTITY_REQ);
      sendSysex(C.SETUP_REQ);
      sendSysex(C.NAMES_REQ);
      sendSysex(C.PATCH_REQ, [pr.EDIT + M.part]);
      sendSysex(C.CARDS_REQ);
    }).catch(function (e) { status("connection failed: " + e.message, true); });
  }

  var midiPorts = {};
  function scanMidi() {
    var sel = $("#conn");
    TSP.listMidi().then(function (io) {
      Array.prototype.slice.call(sel.querySelectorAll("option.midi")).forEach(function (o) { o.remove(); });
      midiPorts = {};
      io.outputs.forEach(function (o) {
        var inp = io.inputs.filter(function (i) { return i.name === o.name; })[0] || io.inputs[0];
        if (!inp) return;
        midiPorts[o.id] = { output: o, input: inp };
        var opt = el("option", { value: o.id, class: "midi", text: "MIDI: " + o.name });
        sel.appendChild(opt);
        if (/touchsynth/i.test(o.name) && sel.value === "emulator" && !M.userPicked) sel.value = o.id;
      });
    }).catch(function (e) { status(e.message + " (the emulator still works)"); });
  }

  /* ------------------------------------------------------------------ status line and monitor */
  function status(s, bad) {
    var st = $("#status");
    st.textContent = s;
    st.className = bad ? "bad" : "";
  }
  var monPaused = false, monRows = [];
  function log(dir, b) {
    if (monPaused) return;
    var hideNrpn = $("#mon-nrpn") && !$("#mon-nrpn").checked;
    if (hideNrpn && (b[0] & 0xF0) === 0xB0 && [0x63, 0x62, 0x06, 0x26].indexOf(b[1]) >= 0) return;
    monRows.push([performance.now(), dir, pr.describe(b)]);
    if (monRows.length > 400) monRows.shift();
    if (!$("#view-monitor").hidden) renderMonitor();
  }
  function renderMonitor() {
    var box = $("#mon-log");
    box.textContent = monRows.slice(-200).map(function (r) {
      return (r[0] / 1000).toFixed(3).padStart(9) + "  " + (r[1] === "out" ? "→" : "←") + "  " + r[2];
    }).join("\n");
    box.scrollTop = box.scrollHeight;
  }

  /* ------------------------------------------------------------------ part selector */
  function renderPartSelect() {
    var sel = $("#part");
    sel.innerHTML = "";
    for (var k = 0; k < pr.NPART; k++) {
      var p = M.setup && M.setup.parts[k];
      var lbl = "Part " + (k + 1) + (p ? (p.channel ? " · ch " + p.channel : " · off") : "");
      sel.appendChild(el("option", { value: k, text: lbl }));
    }
    sel.value = M.part;
  }

  /* ------------------------------------------------------------------ patch editor */
  var pendingParam = {}, paramTimer = null;
  function queueParam(id, value) {
    pendingParam[id] = value;
    if (paramTimer) return;
    paramTimer = setTimeout(function () {
      paramTimer = null;
      var ch = partChannel();
      if (!ch) { status("part " + (M.part + 1) + " has no MIDI channel: set one in Setup", true); pendingParam = {}; return; }
      Object.keys(pendingParam).forEach(function (pid) {
        pr.nrpn(ch, +pid, pendingParam[pid]).forEach(function (m, i) { send(m, i < 3); });
      });
      pendingParam = {};
    }, 25);
  }
  function fmt(p, v) {
    if (p.enum) return p.enum[v - p.min];
    if (p.unit === "time") return v ? (function (s) { return s < 1 ? (s * 1000).toFixed(s < 0.01 ? 1 : 0) + " ms" : s.toFixed(2) + " s"; })(0.001 * Math.pow(10000, v / 127)) : "0";
    if (p.unit === "1/256 oct above 20 Hz") { var hz = 20 * Math.pow(2, v / 256); return hz < 1000 ? hz.toFixed(0) + " Hz" : (hz / 1000).toFixed(2) + " kHz"; }
    if (p.unit === "1/256 oct") return (v / 256).toFixed(2) + " oct";
    if (p.key === "LFO_RATE") return (0.05 * Math.pow(1000, v / 127)).toFixed(2) + " Hz";
    return v + (p.unit ? " " + p.unit : "");
  }
  function renderEditor() {
    var box = $("#editor");
    box.innerHTML = "";
    if (!M.edit) { box.appendChild(el("p", { class: "muted", text: "No patch yet: connect to an instrument or the emulator." })); return; }
    $("#patch-name").value = M.edit.name;
    var engine = M.edit.values[pr.BYKEY.ENGINE.id];
    pr.GROUPS.forEach(function (g) {
      var ps = pr.PARAMS.filter(function (p) { return p.group === g.key; });
      var dim = (engine === 1 && /^osc|src$/.test(g.key)) || (engine === 0 && g.key === "modal");
      var card = el("section", { class: "group" + (dim ? " dim" : "") }, [el("h3", { text: g.name })]);
      ps.forEach(function (p) {
        var v = M.edit.values[p.id], val = el("span", { class: "val", text: p.enum ? "" : fmt(p, v) }), ctl;
        if (p.enum) {
          ctl = el("select", { "aria-label": g.name + " " + p.name });
          p.enum.forEach(function (n, i) { ctl.appendChild(el("option", { value: p.min + i, text: n })); });
          ctl.value = v;
          ctl.addEventListener("change", function () {
            var x = +ctl.value; M.edit.values[p.id] = x; queueParam(p.id, x);
            if (p.key === "ENGINE") renderEditor();
          });
        } else {
          ctl = el("input", { type: "range", min: p.min, max: p.max, step: 1, value: v, "aria-label": g.name + " " + p.name });
          ctl.addEventListener("input", function () {
            var x = +ctl.value; M.edit.values[p.id] = x; val.textContent = fmt(p, x); queueParam(p.id, x);
          });
          ctl.addEventListener("dblclick", function () {
            ctl.value = p.default; ctl.dispatchEvent(new Event("input"));
          });
        }
        card.appendChild(el("label", { class: "row", title: (p.note || "") + (p.note ? " · " : "") + "ID " + p.id + (p.cc ? " · CC " + p.cc : "") + " · double-click: default" },
                            [el("span", { class: "lbl", text: p.name }), ctl, val]));
      });
      box.appendChild(card);
    });
    var stsel = $("#store-to");
    stsel.innerHTML = "";
    M.names.forEach(function (n, i) { stsel.appendChild(el("option", { value: i, text: (i + 1) + "  " + (n || "—") })); });
    if (M.setup) stsel.value = M.setup.parts[M.part].program;
  }
  function sendWholePatch() {
    if (!M.edit) return;
    M.edit.name = $("#patch-name").value;
    send(pr.patchDump(pr.EDIT + M.part, M.edit.name, M.edit.values));
  }

  /* ------------------------------------------------------------------ library */
  function renderLibrary() {
    var box = $("#library");
    box.innerHTML = "";
    var cur = M.setup ? M.setup.parts[M.part].program : -1;
    M.names.forEach(function (n, i) {
      box.appendChild(el("button", { class: "prog" + (i === cur ? " cur" : ""), onclick: function () { selectProgram(i); } },
                         [el("span", { class: "num", text: String(i + 1).padStart(2, "0") }), el("span", { text: n || "—" })]));
    });
  }
  function selectProgram(i) {
    var ch = partChannel();
    if (!ch) { status("part " + (M.part + 1) + " has no MIDI channel", true); return; }
    send([0xC0 | (ch - 1), i]);
    if (M.setup) M.setup.parts[M.part].program = i;
    sendSysex(C.PATCH_REQ, [pr.EDIT + M.part]);
    renderLibrary();
    status("part " + (M.part + 1) + ": program " + (i + 1) + " " + (M.names[i] || ""));
  }
  function download(name, bytes) {
    var a = el("a", { href: URL.createObjectURL(new Blob([new Uint8Array(bytes)], { type: "application/octet-stream" })), download: name });
    document.body.appendChild(a); a.click(); a.remove();
  }
  function exportBank() {
    M.bankCollect = { got: {}, n: 0 };
    status("reading 64 programs...");
    for (var i = 0; i < pr.NPROG; i++) (function (i) { setTimeout(function () { sendSysex(C.PATCH_REQ, [i]); }, i * 10); })(i);
    M.bankCollect.timer = setTimeout(function () { if (M.bankCollect) { status("bank read timed out", true); M.bankCollect = null; } }, 5000);
  }
  function checkBank() {
    var bc = M.bankCollect;
    if (Object.keys(bc.got).length < pr.NPROG) return;
    clearTimeout(bc.timer);
    var all = [];
    for (var i = 0; i < pr.NPROG; i++) all = all.concat(bc.got[i]);
    M.bankCollect = null;
    download("touchsynth_poly_bank.syx", all);
    status("bank exported (64 programs)");
  }
  function exportPatch() {
    if (!M.edit) return;
    M.edit.name = $("#patch-name").value;
    download((M.edit.name || "patch").replace(/[^\w-]+/g, "_") + ".syx", pr.patchDump(0x7F, M.edit.name, M.edit.values));
  }
  function importSyx(file) {
    var rd = new FileReader();
    rd.onload = function () {
      var b = new Uint8Array(rd.result), msgs = [], s = -1;
      for (var i = 0; i < b.length; i++) {
        if (b[i] === 0xF0) s = i;
        else if (b[i] === 0xF7 && s >= 0) { msgs.push(Array.prototype.slice.call(b, s, i + 1)); s = -1; }
      }
      var n = 0;
      msgs.forEach(function (m, k) {
        var x = pr.parseSysex(m);
        if (!x || x.cmd !== C.PATCH_DUMP) return;
        var pd = pr.rdPatch(x.data);
        if (!pd) return;
        var slot = pd.slot < pr.NPROG ? pd.slot : pr.EDIT + M.part;
        n++;
        setTimeout(function () { send(pr.patchDump(slot, pd.name, pd.values)); }, k * 10);
      });
      setTimeout(function () { sendSysex(C.NAMES_REQ); sendSysex(C.PATCH_REQ, [pr.EDIT + M.part]); }, msgs.length * 10 + 50);
      status("imported " + n + " patch" + (n === 1 ? "" : "es") + " from " + file.name);
    };
    rd.readAsArrayBuffer(file);
  }

  /* ------------------------------------------------------------------ setup (parts) */
  var setupTimer = null;
  function setupChanged() {
    clearTimeout(setupTimer);
    setupTimer = setTimeout(function () { send(pr.setupDump(M.setup)); renderPartSelect(); }, 200);
  }
  function renderSetup() {
    var tb = $("#setup tbody");
    if (!tb) return;
    tb.innerHTML = "";
    if (!M.setup) return;
    M.setup.parts.forEach(function (p, k) {
      function num(field, min, max, w) {
        var i = el("input", { type: "number", min: min, max: max, value: p[field], style: "width:" + (w || 4.5) + "em" });
        i.addEventListener("change", function () { p[field] = Math.max(min, Math.min(max, +i.value || 0)); i.value = p[field]; setupChanged(); });
        return i;
      }
      var ch = el("select", {});
      ch.appendChild(el("option", { value: 0, text: "off" }));
      for (var c = 1; c <= 16; c++) ch.appendChild(el("option", { value: c, text: String(c) }));
      ch.value = p.channel;
      ch.addEventListener("change", function () { p.channel = +ch.value; setupChanged(); });
      var mode = el("select", {});
      MODES.forEach(function (m, i) { mode.appendChild(el("option", { value: i, text: m })); });
      mode.value = p.mode;
      mode.addEventListener("change", function () { p.mode = +mode.value; setupChanged(); });
      var prog = el("select", {});
      M.names.forEach(function (n, i) { prog.appendChild(el("option", { value: i, text: (i + 1) + " " + (n || "—") })); });
      prog.value = p.program;
      prog.addEventListener("change", function () {
        p.program = +prog.value; setupChanged();
        if (p.channel) send([0xC0 | (p.channel - 1), p.program]);
        if (k === M.part) setTimeout(function () { sendSysex(C.PATCH_REQ, [pr.EDIT + M.part]); }, 250);
      });
      var mask = el("span", { class: "mask" });
      for (var s = 0; s < pr.NSLOT; s++) (function (s) {
        var cb = el("input", { type: "checkbox", title: "slot " + (s + 1) });
        cb.checked = (p.mask >> s) & 1;
        cb.addEventListener("change", function () { p.mask = cb.checked ? p.mask | (1 << s) : p.mask & ~(1 << s); setupChanged(); });
        mask.appendChild(el("label", {}, [cb, String(s + 1)]));
      })(s);
      var keys = el("span", {}, [num("keyLo", 0, 127), " – ", num("keyHi", 0, 127)]);
      tb.appendChild(el("tr", { class: k === M.part ? "cur" : "" }, [
        el("td", {}, [el("button", { class: "link", text: String(k + 1), title: "edit this part", onclick: function () { choosePart(k); } })]),
        el("td", {}, [ch]), el("td", {}, [keys]), el("td", {}, [mask]), el("td", {}, [mode]), el("td", {}, [prog]),
        el("td", {}, [num("volume", 0, 127)]), el("td", {}, [num("transpose", -48, 48)]), el("td", {}, [num("pan", 0, 127)])]));
    });
  }

  /* ------------------------------------------------------------------ instrument (cards) */
  function hex(u) { return u.map(function (x) { return x.toString(16).padStart(2, "0"); }).join(""); }
  function renderInstrument() {
    var box = $("#cards");
    box.innerHTML = "";
    if (!M.cards) return;
    var act = M.link && M.link.isEmulator && M.link.emulator ? M.link.emulator.activeSlots() : {};
    M.cards.forEach(function (c) {
      var s = c.slot;
      if (!c.present) {
        box.appendChild(el("div", { class: "card empty" }, [el("h3", { text: "Slot " + s }), el("p", { class: "muted", text: "empty" })]));
        return;
      }
      var st = STATES[c.state] || "?", ok = c.state === 3;
      var bar = el("div", { class: "bar" }, [el("div", { style: "width:" + Math.min(100, c.load) + "%" })]);
      var cal = el("button", { text: c.busy ? "calibrating…" : "Calibrate", disabled: c.busy ? "" : null,
                                onclick: function () { sendSysex(C.CALIBRATE, [s <= 7 ? 1 << (s - 1) : 0, s === 8 ? 1 : 0]); } });
      if (!c.busy) cal.removeAttribute("disabled");
      box.appendChild(el("div", { class: "card" + (act[s - 1] === 2 ? " playing" : act[s - 1] ? " ringing" : "") }, [
        el("h3", {}, ["Slot " + s + " ", el("span", { class: "pill " + (ok ? "ok" : "warn"), text: st })]),
        el("p", { class: "kind", text: (c.kind === 1 ? "effects card" : "voice card") + " · fw " + c.fw + (c.caps & 1 ? " · dual PWM" : "") }),
        el("p", { class: "mono", text: hex(c.uid) }),
        el("div", { class: "kv" }, [el("span", { text: "CPU" }), bar, el("span", { text: c.load + " %" })]),
        el("div", { class: "kv" }, [el("span", { text: "clock" }), el("span", { text: (c.ppm > 0 ? "+" : "") + c.ppm + " ppm" })]),
        el("div", { class: "kv" }, [el("span", { text: "errors" }), el("span", { text: "CRC " + c.crc + " · late " + c.late + " · underruns " + c.underruns })]),
        el("div", { class: "kv" }, [el("span", { text: "calibrated" }), el("span", { text: c.calibrated ? "yes" : "no" })]),
        cal]));
    });
  }

  /* ------------------------------------------------------------------ keyboard */
  var held = {}, octave = 4;
  function vel() { return +$("#vel").value; }
  function keyOn(n) {
    if (held[n]) return;
    var ch = partChannel();
    if (!ch) { status("part " + (M.part + 1) + " has no MIDI channel", true); return; }
    held[n] = ch;
    send([0x90 | (ch - 1), n, vel()]);
    var k = $('[data-note="' + n + '"]'); if (k) k.classList.add("down");
  }
  function keyOff(n) {
    if (!held[n]) return;
    send([0x80 | (held[n] - 1), n, 0]);
    delete held[n];
    var k = $('[data-note="' + n + '"]'); if (k) k.classList.remove("down");
  }
  function renderKeys() {
    var kb = $("#keys");
    kb.innerHTML = "";
    var lo = octave * 12 + 12, white = [0, 2, 4, 5, 7, 9, 11], wi = 0;
    for (var n = lo; n < lo + 36; n++) {
      var isW = white.indexOf(n % 12) >= 0;
      var key = el("div", { class: "key " + (isW ? "w" : "b"), "data-note": n, title: pr.noteName(n) });
      if (!isW) key.style.left = "calc(" + wi + " * var(--kw) - var(--bw) / 2)";
      if (isW) wi++;
      (function (n) {
        key.addEventListener("pointerdown", function (e) { e.preventDefault(); key.setPointerCapture(e.pointerId); keyOn(n); });
        key.addEventListener("pointerup", function () { keyOff(n); });
        key.addEventListener("pointercancel", function () { keyOff(n); });
      })(n);
      kb.appendChild(key);
    }
    kb.style.setProperty("--nw", wi);
    $("#oct").textContent = "C" + (octave);
  }
  var KEYMAP = "awsedftgyhujkolp;'";                    /* a = C, w = C#, ..., k = C+1 */
  document.addEventListener("keydown", function (e) {
    if (e.repeat || /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    var i = KEYMAP.indexOf(e.key.toLowerCase());
    if (i >= 0) keyOn(octave * 12 + 12 + i);
    else if (e.key === "z") { octave = Math.max(0, octave - 1); renderKeys(); }
    else if (e.key === "x") { octave = Math.min(8, octave + 1); renderKeys(); }
  });
  document.addEventListener("keyup", function (e) {
    var i = KEYMAP.indexOf(e.key.toLowerCase());
    if (i >= 0) keyOff(octave * 12 + 12 + i);
  });
  function panic() {
    Object.keys(held).forEach(function (n) { keyOff(+n); });
    for (var c = 0; c < 16; c++) { send([0xB0 | c, 123, 0], true); send([0xB0 | c, 120, 0], true); }
    if (synth) synth.allOff();
    status("all notes off");
  }

  /* ------------------------------------------------------------------ sound (emulator) and scope */
  function toggleSound() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      synth = new TSP.Synth(audioCtx);
      if (M.link && M.link.isEmulator) M.link.emulator.synth = synth;
      drawScope();
    }
    if (audioCtx.state === "running") { audioCtx.suspend(); $("#sound").textContent = "Sound: off"; }
    else { audioCtx.resume(); $("#sound").textContent = "Sound: on"; }
  }
  function drawScope() {
    var cv = $("#scope"), g = cv.getContext("2d"), buf = new Float32Array(synth.analyser.fftSize);
    (function frame() {
      requestAnimationFrame(frame);
      var w = cv.width = cv.clientWidth * devicePixelRatio, h = cv.height = cv.clientHeight * devicePixelRatio;
      synth.analyser.getFloatTimeDomainData(buf);
      var i0 = 0;
      for (var i = 1; i < buf.length / 2; i++) if (buf[i - 1] < 0 && buf[i] >= 0) { i0 = i; break; }
      g.clearRect(0, 0, w, h);
      g.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent");
      g.lineWidth = 1.5 * devicePixelRatio;
      g.beginPath();
      var n = 1024;
      for (var k = 0; k < n; k++) {
        var x = k / n * w, y = h / 2 - buf[i0 + k] * h * 0.45;
        if (k) g.lineTo(x, y); else g.moveTo(x, y);
      }
      g.stroke();
    })();
  }

  /* ------------------------------------------------------------------ maintenance (CDC console) */
  var serial = null;
  function serialConnect() {
    serial = new TSP.SerialLink();
    serial.open(function (t) { var o = $("#term"); o.textContent += t; o.scrollTop = o.scrollHeight; })
      .then(function () { status("console connected (CDC)"); $("#term-in").disabled = false; })
      .catch(function (e) { status(e.message, true); serial = null; });
  }

  /* ------------------------------------------------------------------ tabs and wiring */
  function showTab(name) {
    document.querySelectorAll("nav button").forEach(function (b) { b.classList.toggle("on", b.dataset.tab === name); });
    document.querySelectorAll("main > section.view").forEach(function (v) { v.hidden = v.id !== "view-" + name; });
    try { localStorage.setItem("tsp-tab", name); } catch (e) {}
    if (name === "monitor") renderMonitor();
    if (name === "instrument") sendSysex(C.CARDS_REQ);
  }
  function choosePart(k) {
    M.part = k;
    renderPartSelect(); renderSetup(); renderLibrary();
    M.edit = null; renderEditor();
    sendSysex(C.PATCH_REQ, [pr.EDIT + k]);
  }
  setInterval(function () {
    if (M.connected && !$("#view-instrument").hidden) send(pr.sysex(C.CARDS_REQ, []), true);
  }, 1000);

  window.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("nav button").forEach(function (b) { b.addEventListener("click", function () { showTab(b.dataset.tab); }); });
    $("#conn").addEventListener("change", function () { M.userPicked = true; });
    $("#connect").addEventListener("click", function () { connect($("#conn").value); });
    $("#scan").addEventListener("click", scanMidi);
    $("#part").addEventListener("change", function () { choosePart(+$("#part").value); });
    $("#sound").addEventListener("click", toggleSound);
    $("#panic").addEventListener("click", panic);
    $("#oct-dn").addEventListener("click", function () { octave = Math.max(0, octave - 1); renderKeys(); });
    $("#oct-up").addEventListener("click", function () { octave = Math.min(8, octave + 1); renderKeys(); });
    $("#reload").addEventListener("click", function () { sendSysex(C.PATCH_REQ, [pr.EDIT + M.part]); });
    $("#send-patch").addEventListener("click", sendWholePatch);
    $("#store").addEventListener("click", function () {
      sendWholePatch();
      setTimeout(function () { sendSysex(C.STORE, [M.part, +$("#store-to").value]); }, 20);
    });
    $("#export-patch").addEventListener("click", exportPatch);
    $("#export-bank").addEventListener("click", exportBank);
    $("#import").addEventListener("change", function (e) { if (e.target.files[0]) importSyx(e.target.files[0]); e.target.value = ""; });
    $("#setup-reload").addEventListener("click", function () { sendSysex(C.SETUP_REQ); });
    $("#cal-all").addEventListener("click", function () { sendSysex(C.CALIBRATE, [0x7F, 1]); });
    $("#mon-pause").addEventListener("click", function () { monPaused = !monPaused; $("#mon-pause").textContent = monPaused ? "Resume" : "Pause"; });
    $("#mon-clear").addEventListener("click", function () { monRows = []; renderMonitor(); });
    $("#serial").addEventListener("click", serialConnect);
    $("#term-in").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && serial) { serial.write(e.target.value + "\n"); e.target.value = ""; }
    });
    var tab = "patch";
    try { tab = localStorage.getItem("tsp-tab") || "patch"; } catch (e) {}
    if (location.hash.length > 1) tab = location.hash.slice(1);       /* index.html#library opens that view */
    if (!$("#view-" + tab)) tab = "patch";
    showTab(tab);
    renderPartSelect(); renderEditor(); renderKeys();
    connect("emulator");                              /* start on the emulator; "Find MIDI" lists real ports (the
                                                         browser asks for MIDI and SysEx permission then) */
  });
  window.TSP_APP = M;                                 /* for the console and the tests */
})();
