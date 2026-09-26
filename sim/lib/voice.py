"""Shared sub-circuits of the TouchSynth voice (netlist snippets), used by S3..S7.

Node conventions: vp = V+ (analog rail), v5 = +5 V, vref = 4.5 V buffered reference,
vbias = 1.5 V expo base reference, v25 = 2.5 V expo op-amp reference.
Everything is a Python format string; {…} fields are filled by the caller.
"""

# Ladder bias chain: V+ -2k2- VB4 -1k- VB3 -1k- VB2 -1k- VB1 -1k- VB0 -2k4- GND, each tap 10 uF
BIAS = """
RB5 vp vb4 2.2k
RB4 vb4 vb3 1k
RB3 vb3 vb2 1k
RB2 vb2 vb1 1k
RB1 vb1 vb0 1k
RB0 vb0 0 2.4k
CB4 vb4 0 10u
CB3 vb3 0 10u
CB2 vb2 0 10u
CB1 vb1 0 10u
CB0 vb0 0 10u
"""

# Exponential converter for cutoff. Input: filtered CV network node 'xcut' (see S2 EXP network).
EXPO = """
* expo divider on the EXP network output {cvcut}: 33k / 1k5 || 100n to vbias
R33X {cvcut} xcut 33k
R12X xcut vbias 1.5k
C12X xcut vbias 100n
QEA na vbias ee BC847B
QEB tail xcut ee BC847B
RREF v5 na 300k
XUEXP v25 na vp 0 uexo LM324
REXP uexo ee 1k
CEXP uexo na 1n
"""

# Moog ladder: input pair (bin1, bin2), rungs P1..P3, load pair P4, 4 x C_LAD
LADDER = """
Q1 n1a bin1 tail BC847B
Q2 n1b bin2 tail BC847B
Q3 n2a vb1 n1a BC847B
Q4 n2b vb1 n1b BC847B
Q5 n3a vb2 n2a BC847B
Q6 n3b vb2 n2b BC847B
Q7 n4a vb3 n3a BC847B
Q8 n4b vb3 n3b BC847B
Q9 vp vb4 n4a BC847B
Q10 vp vb4 n4b BC847B
CL1 n1a n1b {clad}
CL2 n2a n2b {clad}
CL3 n3a n3b {clad}
CL4 n4a n4b {clad}
* input bias (matched 10k on both bases to cancel base-current offset)
RBI1 bin1 vb0 10k
RBI2 bin2 vb0 10k
* two-op-amp instrumentation amp across CL4, G = 11, output referenced to vref
XINA1 n4a ia vp 0 oa TL072
RI1 ia vref 100k
RI2 oa ia 10k
XINA2 n4b ib vp 0 lpf TL072
RI3 oa ib 10k
RI4 lpf ib 100k
"""

# Mixer: sources -> mx (10k to vb0 keeps mx low-Z so the coupling cap settles fast) -> 1 uF -> bin1 (10k to vb0)
# saw 150k (2 Vpp -> ~63 mVpp at bin1), pulse/sub/noise 470k each (5 Vpp -> ~51 mVpp)
MIXER = """
RMS {saw} mx 150k
RMP {pulse} mx 470k
RMU {sub} mx 470k
RMN {noise} mx 470k
RMX mx vb0 10k
CMX mx bin1 1u
"""

# Generic linear V->I sink: CV node (filtered, 0..3 V at 'x') -> LM324 follower + NPN, Re
VI = """
XU{n} {x} ve{n} vp 0 uo{n} LM324
RBV{n} uo{n} bq{n} 1k
QV{n} {col} bq{n} ve{n} MMBT3904
REV{n} ve{n} 0 {re}
"""

# Resonance VCA: diff pair on vb2 bias, input from lpf AC-coupled and attenuated 1:13 (120k / 10k),
# collectors 4.7k, TL072 difference amp (unity, ref vref) cancels CV-dependent collector common mode,
# output AC-coupled through {rfb} into bin2 (10k to vb0).
RESVCA = """
CRI lpf ri 1u
RRA ri rin1 120k
RRB1 rin1 vb2 10k
RRB2 rin2 vb2 10k
QR1 rc1 rin1 rtail BC847B
QR2 rc2 rin2 rtail BC847B
RRC1 vp rc1 4.7k
RRC2 vp rc2 4.7k
RRD1 {fbneg} rdm 10k
RRD2 rdm resout 10k
RRD3 {fbpos} rdp 10k
RRD4 rdp vref 10k
XRDIF rdp rdm vp 0 resout TL072
CRF resout rfb 4.7u
RRF rfb bin2 {rfb}
"""

# Main VCA: diff pair biased from vref (supply-independent trim), V->I R_E 4.7k (max gain ~ +7 dB), input lpf AC-coupled and attenuated 1:34, tail = V->I (CV_VCA) with
# 470k anti-offset pull-up on the emitter (guarantees I = 0 at CV = 0 despite LM324 offset),
# collectors 4.7k to V+, TL072 difference amp (gain R2/R1) referenced to vref, then AC-coupled line out.
VCA = """
CVI {inp} vi 1u
RVA vi vin1 33k
RVB1 vin1 vref 1k
RVB2 vin2 vref 1k
* offset trim: 8-bit R-2R DAC (Rout 100k) -> 1M into vin2, fixed 2M vin1 -> GND (range ~ -1.8 .. +2.7 mV)
RTRM vtrim vin2 1Meg
RTRF vin1 0 2Meg
QA1 vc1 vin1 vtail BC847B
QA2 vc2 vin2m vtail BC847B
VOSV vin2m vin2 {vbe_off}
RVC1 vp vc1 4.7k
RVC2 vp vc2 {rc2}
XU{n} {x} ve{n} vp 0 uo{n} LM324
RBV{n} uo{n} bq{n} 1k
QV{n} vtail bq{n} ve{n} MMBT3904
REV{n} ve{n} 0 4.7k
ROFF{n} v5 ve{n} 470k
RD1 vc1 dm 10k
RD2 dm vcaout {rg}
RD3 vc2 dp 10k
RD4 dp vref {rg}
XDIF dp dm vp 0 vcaout TL072
COUT vcaout lineout 10u
RLOAD lineout 0 10k
"""

# S2 filter networks driven by the MCU PWM (ideal PWM-average source {src}); output node {x}.
# Load-aware: the DC ratio includes the series resistance of the first two stages.
# LIN: 1k/100n -> 4k7/33n -> 4k7 / 15k||22n  (DC ratio 15/25.4 = 0.591)
CVNET_LIN = """
R1{n} {src} a{n} 1k
C1{n} a{n} 0 100n
R2{n} a{n} b{n} 4.7k
C2{n} b{n} 0 33n
R3{n} b{n} {x} 4.7k
R4{n} {x} 0 15k
C3{n} {x} 0 22n
"""
# EXP: 1k/100n -> 4k7/33n -> node b{n}; the expo divider (33k / 1k5 || 100n to vbias) is in EXPO
CVNET_EXP = """
R1{n} {src} a{n} 1k
C1{n} a{n} 0 100n
R2{n} a{n} b{n} 4.7k
C2{n} b{n} 0 33n
"""
LIN_RATIO = 15 / (1 + 4.7 + 4.7 + 15)
EXP_RATIO = 1.5 / (1 + 4.7 + 33 + 1.5)
