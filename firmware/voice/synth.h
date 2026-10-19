/* TouchSynth voice engine: mono, last-note priority, 1 kHz control rate (mirrors sim/behav/behav.py) */
#ifndef SYNTH_H
#define SYNTH_H

#include <stdint.h>

enum { WAVE_SAW = 1, WAVE_PULSE = 2, WAVE_SUB = 4, WAVE_NOISE = 8 };
enum { STEP_SLIDE = 1, STEP_ACCENT = 2, STEP_SYNC = 4, STEP_HOLD = 8, STEP_TIE = 16 };   /* HOLD: no release at
   the end of the step; TIE: continue the previous note (no retrigger) - together they split long notes */
/* control steps in tunes: note = CTRL_*, len = value (no time). CUT: cutoff in 1/16 octave above CUT_F0_HZ,
   RAMP: glide time for the next CUT / RES targets in 16ths, RES: 200 = self-oscillation threshold,
   ENV: filter envelope depth in 1/16 octave, WAVE: WAVE_* mask, VOL: 0...255 */
enum { CTRL_BASE = 128, CTRL_CUT = 128, CTRL_RAMP, CTRL_RES, CTRL_ENV, CTRL_WAVE, CTRL_VOL };   /* SYNC: 4 ms full-open VCA pulse (multitrack alignment) */

typedef struct {
	uint8_t wave;          /* WAVE_* bits */
	uint8_t pw;            /* pulse width 0...255 */
	int16_t cutoff;        /* 1/256 octave above CUT_F0_HZ */
	uint8_t res;           /* 200 = self-oscillation threshold */
	int16_t env_amt;       /* filter envelope depth, 1/256 octave */
	uint8_t keytrack;      /* 0...255 = 0...1 octave per octave */
	uint8_t fenv[4];       /* A, D (time index), S (0...255), R (time index) */
	uint8_t aenv[4];
	uint8_t glide;         /* time index, 0 = off */
	uint16_t lfo_rate;     /* 0.01 Hz */
	uint8_t lfo_pitch;     /* vibrato depth, cent */
	uint8_t lfo_pw;        /* pulse-width modulation depth 0...255 */
	uint8_t vol;           /* 0...255 */
	int16_t acc_env_amt;   /* accent overrides */
	uint8_t acc_vol;
	uint8_t slide_glide;   /* glide time index for slide steps */
	int8_t penv_amt;       /* pitch envelope (percussion): offset at the attack, semitones, decays to the note */
	uint8_t penv_dec;      /*   with this time index */
	uint8_t wave2;         /* WAVE_* mask from wave_ms after each attack (0 ms = off), e.g. tone + noise -> noise */
	uint8_t wave_ms;
	uint8_t dsp;           /* digital voice on the PWM DAC (CH32V006): DSP_PATCH_TABLE entry, 0 = analog DCO */
} patch_t;

typedef struct { uint8_t note, len, flags; } tune_step_t;
typedef struct { const tune_step_t *steps; uint16_t n; uint8_t step_ms, preset; } tune_t;   /* ms per step (16th for demos) */

extern patch_t patch;
extern const uint8_t synth_n_presets, synth_n_tunes, synth_n_demos;   /* demos first, then multitrack parts */
extern volatile uint8_t synth_manual;  /* 1: CVs and DCO are set by the console, the engine is paused */
extern volatile uint8_t synth_mute;    /* 1: VCA closed (bus: SYNC lost) */

void synth_init(void);
void synth_tick(void);              /* 1 kHz control tick: the SYNC edge on the card, else SysTick */
void synth_note_on(uint8_t note, uint8_t flags);
void synth_note_off(uint8_t note);
void synth_all_off(void);
void synth_preset(int i);
int synth_preset_index(void);
const char *synth_preset_name(int i);
void synth_tune_play(int i);        /* -1 stops */
int synth_tune_playing(void);
const char *synth_tune_name(int i);
void synth_dco_note(uint16_t pitch256);   /* set the DCO directly (console), pitch in 1/256 semitone */

/* voice bus events (bus.md 5.1), from the control tick only (no locking); pitch in 1/256 semitone */
enum { SYNTH_RETRIG = 1, SYNTH_PHASE = 2, SYNTH_LEGATO = 4 };   /* NOTE_ON flags */
void synth_bus_note_on(int32_t pitch, uint8_t vel, uint8_t flags);
void synth_bus_note_off(void);
void synth_bus_pitch(int32_t pitch);
int synth_bus_state(int gate, int32_t pitch);       /* VOICE_STATE; 1 if the voice was corrected */
void synth_bus_ctrl(uint8_t id, int16_t value);
int synth_bus_param(uint8_t id, int16_t value);     /* 1 if the ID is implemented */
void synth_bus_tuning(int16_t t);
void synth_bus_preset(int i);
int synth_gate(void);
int32_t synth_pitch(void);                          /* the last tick's oscillator pitch, 1/256 semitone */
uint32_t synth_pitch_counts(int32_t pitch256);   /* 48 MHz timer ticks per period */

#endif
