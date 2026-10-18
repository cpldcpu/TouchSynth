"""Minimal MusicXML (partwise) reader: notes with absolute times in quarter notes, ties merged, plus the tempo
and text directions per measure. Enough for keyboard scores (chords, several voices via backup/forward)."""
import xml.etree.ElementTree as ET

STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def read(path):
    """Returns (notes, measures, fermatas): notes = [dict(part, start, dur, midi, measure, voice, orn)], times in
    quarters, orn = set of ornaments ('mordent', 'inverted-mordent', 'trill-mark', 'fermata');
    measures = {number: dict(start, length, tempo, words)} from the first part; fermatas = [(start, dur)] of all
    notes and rests that carry a fermata."""
    root = ET.parse(path).getroot()
    notes, measures, fermatas = [], {}, []
    for pi, part in enumerate(root.findall("part")):
        t, div, open_ties = 0.0, 1, {}
        for m in part.findall("measure"):
            num = int("".join(c for c in m.get("number") if c.isdigit()) or 0)
            m_start, pos, m_len, last_start = t, 0.0, 0.0, 0.0
            info = measures.setdefault(num, dict(start=m_start, length=0.0, tempo=None, words=[]))
            for el in m:
                if el.tag == "attributes" and el.find("divisions") is not None:
                    div = int(el.find("divisions").text)
                elif el.tag == "direction" and pi == 0:
                    s = el.find("sound")
                    if s is not None and s.get("tempo"):
                        info["tempo"] = float(s.get("tempo"))
                    for w in el.iter("words"):
                        if w.text and w.text.strip():
                            info["words"].append(w.text.strip())
                elif el.tag == "backup":
                    pos -= int(el.find("duration").text) / div
                elif el.tag == "forward":
                    pos += int(el.find("duration").text) / div
                    m_len = max(m_len, pos)
                elif el.tag == "note":
                    if el.find("grace") is not None:
                        continue
                    dur = int(el.find("duration").text) / div if el.find("duration") is not None else 0.0
                    chord = el.find("chord") is not None
                    start = last_start if chord else pos
                    if not chord:
                        last_start = pos
                        pos += dur
                        m_len = max(m_len, pos)
                    orn = {c.tag for o in el.findall("notations") for c in o.iter()
                           if c.tag in ("fermata", "mordent", "inverted-mordent", "trill-mark", "turn")}
                    if "fermata" in orn:
                        fermatas.append((m_start + start, dur))
                    if el.find("rest") is not None:
                        continue
                    p = el.find("pitch")
                    midi = 12 * (int(p.find("octave").text) + 1) + STEP[p.find("step").text] + \
                        int(float(p.find("alter").text)) if p.find("alter") is not None else \
                        12 * (int(p.find("octave").text) + 1) + STEP[p.find("step").text]
                    ties = {x.get("type") for x in el.findall("tie")}
                    voice = el.find("voice").text if el.find("voice") is not None else "1"
                    key = (pi, midi)
                    if "stop" in ties and key in open_ties:          # continuation of a tied note
                        n = open_ties[key]
                        n["dur"] = m_start + start + dur - n["start"]
                        if "start" not in ties:
                            del open_ties[key]
                        continue
                    n = dict(part=pi, start=m_start + start, dur=dur, midi=midi, measure=num, voice=voice, orn=orn)
                    notes.append(n)
                    if "start" in ties:
                        open_ties[key] = n
            t = m_start + m_len
            if pi == 0:
                info["length"] = m_len
    return notes, measures, fermatas
