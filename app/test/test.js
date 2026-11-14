/* Protocol and emulator tests (Node, no browser):  node app/test/test.js
 * Loads the app's plain scripts into a sandbox with a minimal `window`. */
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
const dir = path.join(__dirname, "..", "js");
const sb = { console, setTimeout, clearTimeout, setInterval, clearInterval, Math, performance };
sb.window = sb;
vm.createContext(sb);
for (const f of ["params.js", "protocol.js", "emulator.js"])
  vm.runInContext(fs.readFileSync(path.join(dir, f), "utf8"), sb, { filename: f });
const TSP = sb.TSP, pr = TSP.proto, C = pr.CMD;

let fails = 0, n = 0;
function check(name, ok, info) {
  n++;
  if (!ok) { fails++; console.log("FAIL " + name + (info ? ": " + info : "")); }
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/* 1. encoding */
for (const v of [-32768, -2560, -1, 0, 1, 127, 128, 16383, 16384, 32767])
  check("i16 " + v, pr.rdI16(pr.i16(v), 0) === v);
for (const p of pr.PARAMS) {
  const vals = new Set([p.min, p.max, p.default, Math.round((p.min + p.max) / 2)]);
  for (let v = p.min; v <= p.max && p.max - p.min <= 300; v++) vals.add(v);
  for (const v of vals) check(`NRPN ${p.key} ${v}`, pr.fromD(p, pr.toD(p, v)) === v);
}
const vals = pr.defaults();
vals[pr.BYKEY.CUTOFF.id] = 2345; vals[pr.BYKEY.FENV_AMT.id] = -2000;
const dump = pr.patchDump(5, "Test patch", vals, 0);
const pd = pr.rdPatch(pr.parseSysex(dump).data);
check("patch dump round trip", pd.slot === 5 && pd.name === "Test patch" && pd.values.every((v, i) => v === vals[i]));
check("patch dump 7-bit", dump.slice(1, -1).every((b) => b < 0x80));
check("patch dump size", dump.length === 6 + 1 + 16 + 192 + 1, String(dump.length));
const setup = { parts: [], tuning: -77, flags: 1 };
for (let k = 0; k < 8; k++) setup.parts.push({ channel: k + 1, keyLo: k, keyHi: 120 - k, mask: 0xA5 >> (k % 2), mode: k % 5,
                                                program: 63 - k, volume: 100 - k, transpose: k * 6 - 24, pan: k * 16 });
const su = pr.rdSetup(pr.parseSysex(pr.setupDump(setup)).data);
check("setup round trip", JSON.stringify(su) === JSON.stringify(setup), JSON.stringify(su));
const cards = [];
for (let s = 0; s < 8; s++) cards.push({ present: s < 5, kind: s === 0 ? 1 : 0, uid: [1, 2, 3, 4, 5, 6, 7, 200 + s],
                                         fw: 3, caps: s & 1, state: 3, ppm: -450 + s, load: 23, crc: 1000 + s,
                                         late: 7, underruns: 65535, calibrated: !!(s & 1), busy: s === 2 });
const cd = pr.rdCards(pr.parseSysex(pr.cardsMsg(cards)).data);
check("cards round trip", cd.length === 8 && cd.every((c, s) => c.present === cards[s].present && c.kind === cards[s].kind &&
      c.uid.join() === cards[s].uid.join() && c.ppm === cards[s].ppm && c.crc === cards[s].crc &&
      c.underruns === 65535 && c.calibrated === cards[s].calibrated && c.busy === cards[s].busy));
const names = [];
for (let i = 0; i < 64; i++) names.push("Name " + i);
check("names round trip", pr.rdNames(pr.parseSysex(pr.namesMsg(names)).data).join() === names.join());
check("name padding / non-ASCII", pr.rdNames(pr.parseSysex(pr.namesMsg(["Größe"])).data)[0] === "Gr??e");

/* 2. the emulator against the protocol */
(async () => {
  const got = [];
  const emu = new TSP.Emulator((b) => got.push(b));
  const ask = async (msg, cmd) => {
    got.length = 0; emu.receive(msg); await wait(15);
    return got.map((b) => pr.parseSysex(b)).filter((m) => m && (cmd === undefined || m.cmd === cmd));
  };
  let r = await ask(pr.sysex(C.NAMES_REQ), C.NAMES);
  check("emulator NAMES", r.length === 1 && pr.rdNames(r[0].data)[0] === "Moog Lead");
  r = await ask(pr.sysex(C.SETUP_REQ), C.SETUP_DUMP);
  const s0 = pr.rdSetup(r[0].data);
  check("emulator default setup", s0.parts[0].channel === 1 && s0.parts[0].mask === 0xFF && s0.parts[1].channel === 0);
  r = await ask(pr.sysex(C.PATCH_REQ, [pr.EDIT + 0]), C.PATCH_DUMP);
  const e0 = pr.rdPatch(r[0].data);
  check("emulator edit buffer = program 1", e0.name === "Moog Lead");
  /* NRPN edit */
  for (const m of pr.nrpn(1, pr.BYKEY.CUTOFF.id, 777)) emu.receive(m);
  r = await ask(pr.sysex(C.PATCH_REQ, [pr.EDIT + 0]), C.PATCH_DUMP);
  check("NRPN edits the part's edit buffer", pr.rdPatch(r[0].data).values[pr.BYKEY.CUTOFF.id] === 777);
  /* program change, store */
  emu.receive([0xC0, 3]);
  r = await ask(pr.sysex(C.PATCH_REQ, [pr.EDIT + 0]), C.PATCH_DUMP);
  check("program change loads program 4", pr.rdPatch(r[0].data).name === "Acid Bass");
  await ask(pr.patchDump(pr.EDIT + 0, "My Acid", pr.rdPatch(r[0].data).values));
  r = await ask(pr.sysex(C.STORE, [0, 40]), C.ACK);
  check("STORE acknowledged", r.length === 1 && r[0].data[0] === C.STORE && r[0].data[1] === 0);
  r = await ask(pr.sysex(C.NAMES_REQ), C.NAMES);
  check("stored name in the bank", pr.rdNames(r[0].data)[40] === "My Acid");
  /* setup write */
  s0.parts[1].channel = 2; s0.parts[1].program = 15;
  r = await ask(pr.setupDump(s0), C.ACK);
  check("SETUP_DUMP acknowledged", r.length === 1 && r[0].data[1] === 0);
  r = await ask(pr.sysex(C.SETUP_REQ), C.SETUP_DUMP);
  check("setup written", pr.rdSetup(r[0].data).parts[1].channel === 2);
  /* cards, calibration */
  r = await ask(pr.sysex(C.CARDS_REQ), C.CARDS);
  const c0 = pr.rdCards(r[0].data);
  check("six cards present", c0.filter((c) => c.present).length === 6 && !c0[6].present);
  r = await ask(pr.sysex(C.CALIBRATE, [0x01, 0]), C.ACK);
  r = await ask(pr.sysex(C.CARDS_REQ), C.CARDS);
  check("calibration running on slot 1", pr.rdCards(r[0].data)[0].busy);
  /* voices: notes allocate slots */
  emu.receive([0x90, 60, 100]); emu.receive([0x90, 64, 100]); emu.receive([0x90, 67, 100]);
  const act = emu.activeSlots();
  check("three notes on three slots (slot 1 calibrating)", Object.keys(act).length === 3 && !act[0], JSON.stringify(act));
  emu.receive([0x80, 64, 0]);
  check("note off releases", Object.values(emu.activeSlots()).filter((x) => x === 2).length === 2);
  /* identity, unknown command, foreign SysEx */
  got.length = 0; emu.receive(pr.IDENTITY_REQ); await wait(15);
  check("identity reply", got.length === 1 && got[0][1] === 0x7E && got[0][4] === 0x02 && got[0][5] === 0x7D);
  r = await ask(pr.sysex(0x55, []), C.ACK);
  check("unknown command -> ACK status 1", r.length === 1 && r[0].data[1] === 1);
  got.length = 0; emu.receive([0xF0, 0x41, 0x10, 0x42, 0xF7]); await wait(15);
  check("foreign SysEx ignored", got.length === 0);
  emu.close();
  console.log(`${n - fails} of ${n} checks passed`);
  process.exit(fails ? 1 : 0);
})();
