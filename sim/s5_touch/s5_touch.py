"""S5 - capacitive touch through a CD4051, ch32fun ADC slope method (TOUCH_SLOPE = 1).

Sequence per sample (ch32v00x_touch.h): pin driven high -> ADC started -> pin released to the internal
pull-down (R_PD 35/45/55 k) -> ADC S/H (R_ADC 1 k, C_ADC 3 pF V003 / 4 pF V002) samples the falling slope
for 15 ADC cycles @ 24 MHz (0.625 us). Larger pad capacitance -> slower decay -> higher code.
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import spice
import plotstyle as ps

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

T_REL = 1e-6          # pin released at 1 us
T_SMP0 = T_REL - 40e-9  # ADC sampling starts just before the release (n = 0 NOPs)
T_SMP = 15 / 24e6     # sample window
C_PAD = 6e-12         # pad to hatched ground
C_TRACE = 3e-12       # 30 mm trace on bottom layer
C_PIN = 5e-12         # MCU pad + package

NET = """* S5 touch {name}
{PRE}
.model swm sw vt=0.5 vh=0.05 ron=1 roff=1e12
VDD vdd 0 5
* MCU pin: push-pull high until T_REL, then released to pull-down
VDRV drv 0 PULSE(1 0 {trel} 1n 1n 1 2)
SDRV vdd p drv 0 swm
RDRV p pdrv 50
.model swpd sw vt=0.5 vh=0.05 ron={rpd} roff=1e12
VPD pdc 0 PULSE(0 1 {trel} 1n 1n 1 2)
SPD p 0 pdc 0 swpd
CPIN p 0 {cpin}
* ADC sample-and-hold: switch closed during the sample window
VSMP smp 0 PULSE(0 1 {ts0} 1n 1n {tsw} 2)
.model swadc sw vt=0.5 vh=0.05 ron={radc} roff=1e12
SADC p sh smp 0 swadc
CSH sh 0 {cadc} IC=0
{path}
CPAD x 0 {cpad}
CFING x 0 {cfing}
{CTRL}
tran 1n 3u 0 1n uic
wrdata {{OUT}}/{name}.dat v(p) v(sh) v(x)
.endc
.end
"""
MUX = """* CD4051: common pin (Cos 30 pF) on p, channel switch 470R, channel pin Cis 5 pF + trace
CCOM p 0 30p
RON p ch 470
CCH ch 0 5p
CTR ch x {ctrace}"""
DIRECT = """RTR p x 1
CTR p 0 {ctrace}"""
# the 'CTR ... ' lines above represent trace capacitance to ground; fix node for direct case
DIRECT = """RTR p x 1
CTR x 0 {ctrace}"""
MUX = MUX.replace("CTR ch x {ctrace}", "RTR ch x 1\nCTR x 0 {ctrace}")


def sample(cfing, rpd=45e3, cadc=3e-12, mux=True):
    name = f"t_{'mux' if mux else 'dir'}_c{cfing*1e12:.1f}_r{rpd/1e3:.0f}_a{cadc*1e12:.0f}".replace(".", "p")
    path = (MUX if mux else DIRECT).format(ctrace=C_TRACE)
    net = NET.format(name=name, PRE=spice.PREAMBLE, CTRL=spice.CTRL_HEAD, trel=T_REL, ts0=T_SMP0, tsw=T_SMP,
                     rpd=rpd, radc=1e3, cadc=cadc, cpin=C_PIN, cpad=C_PAD, cfing=max(cfing, 1e-18), path=path)
    net = net.replace("CSH sh 0 {} IC=0".format(cadc), f"CSH sh 0 {cadc} IC=0")
    spice.run(net, OUT, name)
    d = spice.load(os.path.join(OUT, name + ".dat"))
    t = d["time"]
    v_hold = np.interp(T_SMP0 + T_SMP, t, d["v(sh)"])
    return v_hold, d


def main():
    os.makedirs(OUT, exist_ok=True)
    cf = [0, 1, 2, 5, 10, 20]
    rows = []
    curves = {}
    for chip, cadc, bits in (("CH32V003", 3e-12, 10), ("CH32V002", 4e-12, 12)):
        for mux in (True, False):
            for rpd in (35e3, 45e3, 55e3):
                v = [sample(c * 1e-12, rpd, cadc, mux)[0] for c in cf]
                codes = np.array(v) / 5 * (2 ** bits)
                sens = (codes[3] - codes[0]) / 5   # LSB / pF around a 5 pF touch
                curves[(chip, mux, rpd)] = codes
                rows.append([chip, "mux" if mux else "direct", rpd, codes[0], sens, codes[3] - codes[0]])
                print(f"{chip} {'mux   ' if mux else 'direct'} RPD {rpd/1e3:.0f}k: base {codes[0]:.0f} LSB, "
                      f"{sens:.1f} LSB/pF, 5 pF touch = {codes[3]-codes[0]:.1f} LSB/sample")
    ps.save_csv("s5_touch", ["chip", "path", "r_pd_ohm", "code_no_touch", "lsb_per_pf", "delta_5pf_lsb"], rows)

    # detection margin: 16 samples averaged per pad, ADC noise assumed 1.5 LSB rms per sample
    print("\nSNR for a 5 pF touch, 16-sample average, 1.5 LSB rms noise per sample (worst case over R_PD):")
    for chip in ("CH32V003", "CH32V002"):
        r = min([x for x in rows if x[0] == chip and x[1] == "mux"], key=lambda x: x[5])
        snr = r[5] / (1.5 / 4)
        print(f"  {chip} (R_PD {r[2]/1e3:.0f}k): delta {r[5]:.1f} LSB, noise {1.5/4:.2f} LSB -> SNR {snr:.0f}")
    t_scan = 16 * 16 * 2.7e-6
    print(f"scan time 16 pads x 16 samples x 2.7 us = {t_scan*1e3:.2f} ms -> {1/t_scan:.0f} Hz")

    # figure: (a) slope at the pin with / without finger, (b) code vs finger capacitance
    f, ax = ps.fig(2, 1, aspect=0.75)
    for i, c in enumerate((0, 5, 20)):
        _, d = sample(c * 1e-12)
        t = (d["time"] - T_REL) * 1e6
        ax[0].plot(t, d["v(p)"], color=ps.C[i], label=f"{c} pF")
    ax[0].axvspan((T_SMP0 - T_REL) * 1e6, (T_SMP0 + T_SMP - T_REL) * 1e6, color=ps.C[6], alpha=0.08, lw=0,
                  label="ADC sample")
    ax[0].set(xlabel="$t$ after release [µs]", ylabel="pin voltage [V]", xlim=(-0.2, 1.5))
    ax[0].legend(title="finger", loc="lower left")
    for i, (chip, mux, rpd) in enumerate([("CH32V003", True, 45e3), ("CH32V003", False, 45e3),
                                          ("CH32V002", True, 45e3), ("CH32V002", False, 45e3)]):
        codes = curves[(chip, mux, rpd)]
        ax[1].plot(cf, codes - codes[0], "o-" if mux else "s--", color=ps.C[i // 2 * 2 + (0 if mux else 1)],
                   label=f"{chip[-4:]} {'via CD4051' if mux else 'direct'}")
    ax[1].set(xlabel="finger capacitance [pF]", ylabel="code increase [LSB / sample]")
    ax[1].legend(loc="upper left")
    ps.label_panels(ax)
    f.tight_layout()
    ps.save(f, "s5_touch")


if __name__ == "__main__":
    main()
