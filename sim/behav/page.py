"""Build the 'TouchSynth Sound Tour' listening page (HTML + mp3 + spectrogram PNGs in light and dark)."""
import os, sys, json, shutil, wave, html
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import behav as B
import plotstyle as ps

AUD = os.path.join(B.ROOT, "docs", "audio", "features")
OUTDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(B.ROOT, "docs", "tour")

THEMES = {
    "light": dict(bg="#FFFFFF", fg="#1B2420", mut="#5B6A62", line="#1E6B47"),
    "dark": dict(bg="#161D1A", fg="#E4EAE6", mut="#97A69E", line="#5CC08E"),
}


def read_wav(p):
    with wave.open(p) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32767
    return x * 2.0


def spectro(y, path, th):
    import matplotlib.pyplot as plt
    from scipy.signal import spectrogram
    c = THEMES[th]
    with plt.rc_context({"text.color": c["fg"], "axes.labelcolor": c["fg"], "xtick.color": c["mut"],
                         "ytick.color": c["mut"], "axes.edgecolor": c["mut"], "font.family": "sans-serif"}):
        f, ax = plt.subplots(2, 1, figsize=(6.0, 2.4), gridspec_kw=dict(height_ratios=[1, 2.6]), sharex=True)
        f.patch.set_facecolor(c["bg"])
        for a in ax:
            a.set_facecolor(c["bg"]); a.grid(False)
        t = np.arange(len(y)) / B.FS_OUT
        ax[0].plot(t, y, color=c["line"], lw=0.35)
        ax[0].set(ylim=(-2, 2), yticks=[-2, 0, 2]); ax[0].set_ylabel("V", fontsize=8)
        fq, tt, S = spectrogram(y, B.FS_OUT, nperseg=4096, noverlap=3584)
        ax[1].pcolormesh(tt, np.maximum(fq, 1) / 1000, 10 * np.log10(S + 1e-14), shading="auto", cmap="magma",
                         vmin=-120, vmax=-40, rasterized=True)
        ax[1].set_yscale("log"); ax[1].set_ylim(0.04, 12)
        ax[1].set_yticks([0.1, 1, 10]); ax[1].set_yticklabels(["100 Hz", "1 kHz", "10 kHz"])
        ax[1].set_xlabel("seconds", fontsize=8)
        for a in ax:
            a.tick_params(labelsize=7)
            for s in a.spines.values():
                s.set_linewidth(0.5)
        f.tight_layout(h_pad=0.15, pad=0.3)
        f.savefig(path, dpi=130, facecolor=c["bg"])
        plt.close(f)


CSS = """
:root{--bg:#F3F5F2;--surface:#FFFFFF;--ink:#1B2420;--muted:#5B6A62;--line:#D5DDD8;--accent:#1E6B47;--copper:#B06A2B;
--chip:#E7EDE9;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0F1412;--surface:#161D1A;--ink:#E4EAE6;--muted:#97A69E;
--line:#2A3530;--accent:#5CC08E;--copper:#D9955A;--chip:#202A26;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0F1412;--surface:#161D1A;--ink:#E4EAE6;--muted:#97A69E;--line:#2A3530;--accent:#5CC08E;
--copper:#D9955A;--chip:#202A26;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:16px/1.55 "Source Sans 3",system-ui,sans-serif;padding-inline:16px;padding-block:28px 64px}
.wrap{max-width:1000px;margin:0 auto;display:grid;gap:36px}
h1,h2,h3{font-family:"Barlow Semi Condensed","Arial Narrow",sans-serif;font-weight:600;text-wrap:balance;margin:0;line-height:1.15}
h1{font-size:clamp(34px,6vw,52px);letter-spacing:.2px}
h2{font-size:26px;color:var(--accent);display:flex;align-items:baseline;gap:12px}
h2 small{font:500 13px "JetBrains Mono",ui-monospace,monospace;color:var(--muted);letter-spacing:.3px}
h3{font-size:20px}
p{margin:0;max-width:68ch}
.lede{display:grid;gap:14px}
.eyebrow{font:600 12px "JetBrains Mono",ui-monospace,monospace;letter-spacing:1.4px;text-transform:uppercase;color:var(--copper)}
.facts{display:flex;flex-wrap:wrap;gap:8px}
.chip{font:500 12.5px "JetBrains Mono",ui-monospace,monospace;background:var(--chip);color:var(--ink);border-radius:4px;
padding:3px 8px;font-variant-numeric:tabular-nums}
section{display:grid;gap:14px}
.row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:22px;align-items:start;background:var(--surface);
border:1px solid var(--line);border-radius:6px;padding:18px}
.row.playing{border-color:var(--copper);box-shadow:inset 3px 0 0 var(--copper)}
.txt{display:grid;gap:10px;align-content:start}
.txt .id{font:500 12px "JetBrains Mono",ui-monospace,monospace;color:var(--muted)}
audio{width:100%;height:36px}
figure{margin:0}
figure img{display:block;width:100%;height:auto;border-radius:3px}
.dk{display:none}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .dk{display:block}:root:not([data-theme="light"]) .lt{display:none}}
:root[data-theme="dark"] .dk{display:block}:root[data-theme="dark"] .lt{display:none}
.note{font-size:14.5px;color:var(--muted)}
.val{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.val div{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px}
.val b{display:block;font:600 22px "Barlow Semi Condensed",sans-serif;color:var(--accent);font-variant-numeric:tabular-nums}
.val span{font-size:13.5px;color:var(--muted)}
footer{font-size:13.5px;color:var(--muted);border-top:1px solid var(--line);padding-top:16px}
code{font:13px "JetBrains Mono",ui-monospace,monospace;background:var(--chip);padding:1px 5px;border-radius:3px}
@media (max-width:720px){.row{grid-template-columns:1fr}}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--copper);outline-offset:2px}
"""

JS = """
document.querySelectorAll('audio').forEach(a=>{
  a.addEventListener('play',()=>{document.querySelectorAll('audio').forEach(b=>{if(b!==a)b.pause()});
    document.querySelectorAll('.row').forEach(r=>r.classList.toggle('playing',r.contains(a)))});
  a.addEventListener('pause',()=>a.closest('.row').classList.remove('playing'));
  a.addEventListener('ended',()=>a.closest('.row').classList.remove('playing'));
});
"""


def main():
    man = json.load(open(os.path.join(AUD, "manifest.json"), encoding="utf-8"))
    val = {r[0]: float(r[1]) for r in [l.strip().split(",") for l in open(os.path.join(B.RES, "behav_validation.csv"),
                                                                           encoding="utf-8").readlines()[1:]]}
    os.makedirs(os.path.join(OUTDIR, "audio"), exist_ok=True)
    os.makedirs(os.path.join(OUTDIR, "img"), exist_ok=True)
    groups = []
    for m in man:
        shutil.copy(os.path.join(AUD, m["id"] + ".mp3"), os.path.join(OUTDIR, "audio", m["id"] + ".mp3"))
        y = read_wav(os.path.join(AUD, m["id"] + ".wav"))
        for th in THEMES:
            spectro(y, os.path.join(OUTDIR, "img", f"{m['id']}_{th}.png"), th)
        if not groups or groups[-1][0] != m["group"]:
            groups.append((m["group"], []))
        groups[-1][1].append(m)
    e = html.escape
    parts = []
    for gname, items in groups:
        rows = []
        for m in items:
            chips = [f"{m['seconds']:.1f} s", f"peak {m['peak_v']:.2f} V"]
            if "bpm" in m:
                chips = [f"{m['bpm']} bpm", f"preset “{m['preset']}”", f"{m['steps']} steps = {m['flash_bytes']} B flash"] + chips
            rows.append(f"""<article class="row" id="{m['id']}">
  <div class="txt"><span class="id">{e(m['id'])}</span><h3>{e(m['title'])}</h3><p>{e(m['what'])}</p>
    <div class="facts">{''.join(f'<span class="chip">{e(c)}</span>' for c in chips)}</div>
    <audio controls preload="none" src="audio/{m['id']}.mp3"></audio></div>
  <figure><img class="lt" src="img/{m['id']}_light.png" alt="Waveform and spectrogram of {e(m['title'])}" loading="lazy">
    <img class="dk" src="img/{m['id']}_dark.png" alt="Waveform and spectrogram of {e(m['title'])}" loading="lazy"></figure>
</article>""")
        parts.append(f'<section><h2>{e(gname)} <small>{len(items)} clip{"s" if len(items) > 1 else ""}</small></h2>\n'
                     + "\n".join(rows) + "</section>")
    page = f"""<title>TouchSynth Sound Tour</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600&family=JetBrains+Mono:wght@500;600&family=Source+Sans+3:wght@400;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
<header class="lede">
  <span class="eyebrow">TouchSynth · behavioural model · before the first PCB</span>
  <h1>TouchSynth Sound Tour</h1>
  <p>Every feature of the MCU-controlled analog mono synth, one clip each, followed by the demo tunes that will
  live in the CH32V flash. The clips come from a fast behavioural model of the circuit: DCO with timer reset,
  transistor ladder filter with resonance, differential-pair VCA and the firmware (envelopes, LFO, glide,
  arpeggiator). Its constants are fitted to the ngspice simulations of the actual schematic.</p>
  <div class="facts"><span class="chip">48 kHz render, 192 kHz internal</span><span class="chip">same level scale for all clips: 2 V = full scale</span><span class="chip">line-out voltage shown</span></div>
</header>
<section>
  <h2>How close is the model? <small>vs ngspice, full-voice score</small></h2>
  <div class="val">
    <div><b>{val['level_mean_db']:+.1f} dB</b><span>mean level difference (rms {val['level_rms_db']:.1f} dB)</span></div>
    <div><b>&lt; 2 %</b><span>self-oscillation pitch error, CV_RES 3.4…5 V</span></div>
    <div><b>&lt; 7 %</b><span>self-oscillation amplitude error</span></div>
    <div><b>{val['centroid_mean_cent']:+.0f} cent</b><span>brightness (spectral centroid); differs most right at the resonance threshold</span></div>
  </div>
  <p class="note">The model is a guide to the sound, not a promise: real parts add tolerances (the filter drifts about
  −13 cent per kelvin), and resonance exactly at the self-oscillation threshold is sensitive in both the model and the circuit.</p>
</section>
{''.join(parts)}
<footer>Generated from <code>sim/behav/examples.py</code> and <code>sim/behav/page.py</code>. Tunes: original acid line;
J.&nbsp;S.&nbsp;Bach, Prelude in C major BWV 846 and L.&nbsp;v.&nbsp;Beethoven, “Ode to Joy” (both public domain).</footer>
</div>
<script>{JS}</script>
"""
    with open(os.path.join(OUTDIR, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print("written", OUTDIR)


if __name__ == "__main__":
    main()
