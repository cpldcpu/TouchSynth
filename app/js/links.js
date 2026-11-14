/* Links between the app and an instrument: the in-page emulator or a real one through Web MIDI; Web Serial for the
 * maintenance console (CDC). A link has: name, open(onMessage) -> Promise, send(bytes), close(). */
var TSP = window.TSP = window.TSP || {};

TSP.EmulatorLink = function () {
  "use strict";
  var emu = null, self = this;
  this.name = "Emulator";
  this.isEmulator = true;
  this.open = function (onMessage) {
    emu = new TSP.Emulator(function (b) { onMessage(b); });
    self.emulator = emu;
    return Promise.resolve();
  };
  this.send = function (b) { if (emu) emu.receive(b); };
  this.close = function () { if (emu) emu.close(); emu = null; };
};

TSP.midiAccess = null;
TSP.listMidi = function () {
  "use strict";
  if (!navigator.requestMIDIAccess) return Promise.reject(new Error("Web MIDI is not available in this browser"));
  var p = TSP.midiAccess ? Promise.resolve(TSP.midiAccess) : navigator.requestMIDIAccess({ sysex: true });
  return p.then(function (acc) {
    TSP.midiAccess = acc;
    var outs = [], ins = [];
    acc.outputs.forEach(function (o) { outs.push(o); });
    acc.inputs.forEach(function (i) { ins.push(i); });
    return { outputs: outs, inputs: ins };
  });
};

TSP.MidiLink = function (output, input) {
  "use strict";
  this.name = output.name;
  this.isEmulator = false;
  this.open = function (onMessage) {
    input.onmidimessage = function (e) { onMessage(Array.prototype.slice.call(e.data)); };
    return Promise.all([output.open(), input.open()]);
  };
  this.send = function (b) { output.send(b); };
  this.close = function () { input.onmidimessage = null; };
};

/* the CDC console (maintenance): lines in and out */
TSP.SerialLink = function () {
  "use strict";
  var port = null, reader = null, self = this;
  this.open = function (onText) {
    if (!navigator.serial) return Promise.reject(new Error("Web Serial is not available in this browser"));
    return navigator.serial.requestPort().then(function (p) {
      port = p;
      return port.open({ baudRate: 115200 });
    }).then(function () {
      var dec = new TextDecoder();
      reader = port.readable.getReader();
      (function pump() {
        reader.read().then(function (r) {
          if (r.done) return;
          onText(dec.decode(r.value));
          pump();
        }).catch(function () {});
      })();
    });
  };
  this.write = function (s) {
    if (!port) return;
    var w = port.writable.getWriter();
    w.write(new TextEncoder().encode(s)).then(function () { w.releaseLock(); });
  };
  this.close = function () {
    if (reader) reader.cancel().catch(function () {});
    if (port) port.close().catch(function () {});
    port = reader = null;
  };
};
