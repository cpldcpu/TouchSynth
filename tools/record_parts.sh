#!/bin/bash
# Record multitrack parts from the line out, one take per part (run on the lab PC, in LAB_DIR).
#
#   ./record_parts.sh SECONDS name:tune [name:tune ...]      e.g.  ./record_parts.sh 200 march_timp:15
#
# For each part: stop the voice, start a single-shot scope capture of SECONDS (scope.py record) that triggers on
# the part's sync pulse (falling edge at -15 mV), then disable the touch keys ('keys 0', so nothing can stop the
# tune) and start tune <tune>. Writes <name>.f32 (+ .txt rate, .log console log). Tune numbers: the order of
# PART_NAMES in firmware/touchsynth/tables.h, after the demos. Mix with tools/mix_parts.py.
cd "$(dirname "$0")" || exit 1
[ -f lab.conf ] && . ./lab.conf
export MINICHLINK=${MINICHLINK:-ch32fun/minichlink/minichlink}
secs=$1; shift
for pair in "$@"; do
  p=${pair%%:*}; i=${pair##*:}
  sleep 3
  python3 synthtest.py off "cv vca 0" > /dev/null
  sleep 3
  echo "$(date +%T) recording $p (tune $i)"
  TRIG=-0.015 timeout 1200 python3 scope.py record "$p.f32" "$secs" "keys 0" "tune $i" || echo "FAILED $p"
  grep -q "tune $i" "$p.f32.log" && echo "  tune $i ran; last: $(grep "^t=" "$p.f32.log" | tail -1 | cut -c1-50)"
done
echo "$(date +%T) done"
