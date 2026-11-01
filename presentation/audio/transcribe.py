"""Word-level transcript of the voiceover (offline faster-whisper)."""
import json, sys
from faster_whisper import WhisperModel

src, out = sys.argv[1], sys.argv[2]
import wave, numpy as np
with wave.open(src) as w:
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
model = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=2)
segs, info = model.transcribe(audio, word_timestamps=True, vad_filter=False, beam_size=2,
                              condition_on_previous_text=False)
words, lines = [], []
part = open(out + ".partial", "w")
for s in segs:
    part.write(f"{s.start:7.2f}-{s.end:7.2f}  {s.text.strip()}\n"); part.flush()
    lines.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
    for w in s.words:
        words.append({"start": round(w.start, 2), "end": round(w.end, 2), "w": w.word, "p": round(w.probability, 2)})
json.dump({"lang": info.language, "segments": lines, "words": words}, open(out, "w"), ensure_ascii=False, indent=0)
print("lang", info.language, info.language_probability)
for l in lines:
    print(f"{l['start']:7.2f}-{l['end']:7.2f}  {l['text']}")
