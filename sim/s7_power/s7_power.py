"""S7 - power: SS14 + 78L05 + VREF buffer; supply ripple -> audio (hum), current budget, power-up.

The complete voice is instantiated in a quiet state (DCO held in reset, filter open, VCA fully open) and
the input carries 200 mVpp of 100 Hz ripple. MCU-generated CVs are modelled ratiometric to the +5 V rail.
"""
import os, sys, re
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import spice
import plotstyle as ps
import voice

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

POWER = """
* ---- input, reverse protection, bulk ----
VIN vinr 0 {vin_src}
RIN vinr vin 0.5
DREV vin vp DSS14
CBULK vp 0 10u
CHF vp 0 100n
* ---- 5 V ----
XREG vp v5 0 REG78L05
C5 v5 0 1u
C5B v5 0 100n
ILOGIC v5 0 {i_logic}
* ---- references from +5 V ----
RV1 v5 vrd 1k
RV2 vrd 0 9.1k
CVR vrd 0 10u
* VREF: TL072 follower, output snubber 10R + 1u (no bare capacitor on the op-amp output)
XVREF vrd vref vp 0 vref TL072
RSN vref vsn 10
CSN vsn 0 1u
RB1A v5 vbias 3.3k
RB1B vbias 0 1.5k
CBIA vbias 0 1u
R25A v5 v25 10k
R25B v25 0 10k
C25 v25 0 1u
"""


def voice_quiet(cv_cut=5.0, cv_res=0.0, cv_vca=5.0):
    ratiom = lambda node, duty: f"B{node} {node} 0 V = v(v5) * {duty / 5.0}\n"
    return (ratiom("cva", 0.0) + voice.CVNET_LIN.format(n="A", src="cva", x="xamp") + """
XUA xamp veA vp 0 uoA LM324
RBA uoA bqA 1k
QVA n bqA veA MMBT3904
REA veA 0 33k
XDCO vref n vp 0 saw TL072
CI saw n 10n
MRST saw g n 2N7002
RGS gd g 2.2k
RGP vp gd 10k
QLS gd b2 0 MMBT3904
RLSB 0 b2 4.7k
""" + voice.BIAS + ratiom("cvc", cv_cut) + voice.CVNET_EXP.format(n="C", src="cvc")
            + voice.EXPO.format(cvcut="bC") + voice.LADDER.format(clad="33n")
            + voice.MIXER.format(saw="saw", pulse="0", sub="0", noise="0")
            + ratiom("cvr", cv_res) + voice.CVNET_LIN.format(n="R", src="cvr", x="xres")
            + voice.VI.format(n="R", x="xres", col="rtail", re="6.2k")
            + voice.RESVCA.format(fbneg="rc1", fbpos="rc2", rfb="22k")
            + ratiom("cvv", cv_vca) + voice.CVNET_LIN.format(n="V", src="cvv", x="xvv")
            + voice.VCA.format(inp="lpf", vbe_off=0, rc2="4.7k", n="V", x="xvv", rg="22k")
            + "VTR vdac 0 2.025\nRDAC vdac vtrim 100k\n")


def run_ripple(vin):
    name = f"ripple_{vin}".replace(".", "p")
    net = f"""* S7 ripple
{spice.PREAMBLE}
{POWER.format(vin_src=f'SIN({vin} 0.1 100)', i_logic='15m')}
{voice_quiet()}
{spice.CTRL_HEAD}
tran 20u 0.5 0 20u
meas tran vp_pp PP v(vp) from=0.4 to=0.5
meas tran v5_pp PP v(v5) from=0.4 to=0.5
meas tran vref_pp PP v(vref) from=0.4 to=0.5
meas tran out_pp PP v(lineout) from=0.4 to=0.5
meas tran iin AVG i(VIN) from=0.4 to=0.5
wrdata {{OUT}}/{name}.dat v(lineout) v(vp) v(v5) v(vref)
.endc
.end
"""
    log = spice.run(net, OUT, name)
    g = lambda k: float(re.search(rf"{k}\s*=\s*([-\d.e+]+)", log).group(1))
    return {k: g(k) for k in ("vp_pp", "v5_pp", "vref_pp", "out_pp", "iin")}


def run_powerup():
    net = f"""* S7 power-up
{spice.PREAMBLE}
{POWER.format(vin_src='PWL(0 0 1m 9)', i_logic='15m')}
{voice_quiet()}
{spice.CTRL_HEAD}
option method=gear
tran 20u 0.4 0 20u
wrdata {{OUT}}/powerup.dat v(vp) v(v5) v(vref) v(vb0) v(lpf) v(lineout)
.endc
.end
"""
    spice.run(net, OUT, "powerup")
    return spice.load(os.path.join(OUT, "powerup.dat"))


def run_vref_step():
    net = f"""* S7 VREF buffer load step (stability)
{spice.PREAMBLE}
{POWER.format(vin_src='9', i_logic='15m')}
ISTEP vref 0 PULSE(0 1m 5m 1u 1u 5m 20m)
{spice.CTRL_HEAD}
tran 1u 15m 0 1u
wrdata {{OUT}}/vrefstep.dat v(vref)
.endc
.end
"""
    spice.run(net, OUT, "vrefstep")
    return spice.load(os.path.join(OUT, "vrefstep.dat"))


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for vin in (9.0, 12.0):
        r = run_ripple(vin)
        hum_db = 20 * np.log10((r["out_pp"] / 2 / np.sqrt(2)) / (1.33 / 2 / np.sqrt(2)))
        rows.append([vin, r["vp_pp"], r["v5_pp"], r["vref_pp"], r["out_pp"], hum_db, -r["iin"]])
        print(f"Vin {vin} V + 200 mVpp/100 Hz: V+ {r['vp_pp']*1e3:.0f} mVpp, +5V {r['v5_pp']*1e3:.2f} mVpp, "
              f"VREF {r['vref_pp']*1e6:.0f} uVpp, line out {r['out_pp']*1e6:.0f} uVpp "
              f"({hum_db:.0f} dB re 1.33 Vpp), I_in {-r['iin']*1e3:.1f} mA (incl. 15 mA logic)")
    ps.save_csv("s7_power", ["vin_v", "vp_ripple_vpp", "v5_ripple_vpp", "vref_ripple_vpp", "out_ripple_vpp",
                             "hum_db_re_nominal", "i_in_a"], rows)
    d = run_powerup()
    t = d["time"]
    ok = np.where(np.abs(d["v(vref)"] - 4.5) > 0.01)[0]
    t_ref = t[ok[-1]] if len(ok) else 0
    ok2 = np.where(np.abs(d["v(lineout)"]) > 0.01)[0]
    t_out = t[ok2[-1]] if len(ok2) else 0
    print(f"power-up: VREF within 10 mV after {t_ref*1e3:.1f} ms, line out within 10 mV after {t_out*1e3:.0f} ms")
    s = run_vref_step()
    ts = s["time"]; v = s["v(vref)"]
    sel = (ts > 5e-3) & (ts < 7e-3)
    print(f"VREF 1 mA load step: dip {1e3*(v[ts<5e-3][-1]-v[sel].min()):.2f} mV, "
          f"ring pp after 1 ms {1e3*np.ptp(v[(ts>6e-3)&(ts<9.9e-3)]):.3f} mV")

    f, ax = ps.fig(2, 1, aspect=0.75)
    for i, (k, lab) in enumerate([("v(vp)", "$V_+$"), ("v(v5)", "+5 V"), ("v(vref)", "VREF"), ("v(vb0)", "VB0")]):
        ax[0].plot(t * 1e3, d[k], color=ps.C[i], label=lab)
    ax[0].plot(t * 1e3, d["v(lineout)"], color=ps.C[6], lw=0.8, label="line out")
    ax[0].set(xlabel="$t$ [ms]", ylabel="[V]", xlim=(0, 400))
    ax[0].legend(loc="center right", ncol=1)
    ax[1].plot((ts - 5e-3) * 1e3, (v - v[ts < 5e-3][-1]) * 1e3, color=ps.C[0])
    ax[1].set(xlabel="$t$ after 1 mA load step [ms]", ylabel=r"$\Delta V_\mathrm{REF}$ [mV]", xlim=(-0.5, 7))
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, "s7_power")


if __name__ == "__main__":
    main()
