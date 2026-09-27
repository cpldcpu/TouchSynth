/* TouchSynth voice engine: mono, last-note priority, 1 kHz control rate (mirrors sim/behav/behav.py) */
#ifndef SYNTH_H
#define SYNTH_H

#include <stdint.h>

enum { WAVE_SAW = 1, WAVE_PULSE = 2, WAVE_SUB = 4, WAVE_NOISE = 8 };
enum { STEP_SLIDE = 1, STEP_ACCENT = 2 };

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
} patch_t;

typedef struct { uint8_t note, len, flags; } tune_step_t;
typedef struct { const tune_step_t *steps; uint16_t n; uint8_t bpm, preset; } tune_t;

extern patch_t patch;
extern const uint8_t synth_n_presets, synth_n_tunes;
extern volatile uint8_t synth_manual;  /* 1: CVs and DCO are set by the console, the engine is paused */

void synth_init(void);
void synth_tick(void);              /* 1 kHz, from the SysTick interrupt */
void synth_note_on(uint8_t note, uint8_t flags);
void synth_note_off(uint8_t note);
void synth_all_off(void);
void synth_preset(int i);
int synth_preset_index(void);
const char *synth_preset_name(int i);
void synth_tune_play(int i);        /* -1 stops */
int synth_tune_playing(void);
const char *synth_tune_name(int i);
uint16_t synth_held_mask(int base); /* held notes as a key mask (for the LEDs), bit = note - base */
void synth_dco_note(uint16_t pitch256);   /* set the DCO directly (console), pitch in 1/256 semitone */

#endif
