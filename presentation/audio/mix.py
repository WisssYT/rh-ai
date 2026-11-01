"""Voiceover edit + music bed for the 5-minute film.

1. Clean the voiceover (rumble filter, light denoise, gentle compression).
2. Cut it into lines, keeping only clean takes (the stumbled economics restarts are dropped).
3. Place every line on its scene in the re-timed video (opening scene now 4.5 s instead of 9 s).
4. Loop the music under the whole film, ducked under the voice, with fades.
"""
import json, subprocess, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
FF = __import__("os").environ.get("FFMPEG", "ffmpeg")
VO = str(HERE / "talent.m4a")
SHIFT = 4.5            # opening scene shortened from 9 s to 4.5 s -> every later scene moves up 4.5 s
VIDEO_DUR = 299.5 - SHIFT

# (name, source start, source end, scene start in the ORIGINAL 5-min cut, offset into scene)
# source times come from the word-level transcript; ends are padded and edge silence is trimmed below.
LINES = [
    ("one_role",      0.00,   2.95,   0.0, 0.35),
    ("66_days",       3.70,   9.55,   9.0, 0.30),
    ("title",        10.45,  14.55,  17.0, 0.80),
    ("candidates",   15.20,  23.00,  26.0, 0.80),
    ("phone",        23.55,  27.80,  50.0, 0.60),
    ("workflow",     28.45,  34.05,  60.0, 0.60),
    ("criteria",     35.30,  41.20,  75.0, 0.60),
    ("authorize",    42.05,  46.95,  87.0, 0.60),
    ("evidence",     49.05,  55.85, 102.5, 0.60),
    ("quotes",       56.70,  63.65, 116.5, 0.80),
    ("security",     65.50,  71.60, 133.5, 0.80),
    ("attacker",     72.15,  75.55, 149.5, 0.60),
    ("email",        75.65,  79.80, 157.5, 0.50),
    ("dashboard",    81.25,  87.40, 165.5, 0.50),
    ("approve",      88.85,  94.20, 174.5, 0.50),
    ("books",        96.20, 100.00, 193.5, 0.80),
    ("hr_waits",    101.55, 106.55, 208.5, 0.50),
    ("kit",         107.40, 112.95, 217.5, 0.80),
    ("followups",   113.95, 120.35, 232.5, 0.80),
    ("supervisor",  121.90, 126.85, 248.5, 0.80),
    ("traction",    127.30, 132.70, 260.5, 0.60),
    # 133.5 - 157.6: stumbled restarts of the economics line -> dropped; clean take follows
    ("economics",   157.75, 165.95, 271.5, 0.60),
    ("research",    166.75, 170.85, 282.5, 0.50),
    ("close",       173.05, 176.85, 290.5, 1.00),
]

def run(args):
    subprocess.run([FF, "-y", "-loglevel", "error"] + args, check=True)

def dur(path):
    out = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = out.split("Duration: ")[1].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

# 1. cleaned voiceover at a consistent level
run(["-i", VO, "-af", "highpass=f=80,lowpass=f=12000,afftdn=nf=-28:nr=10,"
     "acompressor=threshold=-22dB:ratio=3:attack=8:release=120:makeup=4,"
     "loudnorm=I=-16:TP=-2:LRA=8", "-ar", "48000", "-ac", "1", str(HERE / "vo_clean.wav")])

# 2. cut lines; trim edge silence; tiny fades against clicks
EDGE = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.06," \
       "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse"
placed = []
for name, a, b, scene, off in LINES:
    out = HERE / f"line_{name}.wav"
    run(["-ss", f"{a:.2f}", "-to", f"{b:.2f}", "-i", str(HERE / "vo_clean.wav"),
         "-af", EDGE + ",afade=t=in:d=0.02", str(out)])
    d = dur(out)
    run(["-i", str(out), "-af", f"afade=t=out:st={max(0, d - 0.06):.3f}:d=0.06", str(HERE / f"lf_{name}.wav")])
    at = max(0.0, scene - (SHIFT if scene >= 9.0 else 0.0) + off)
    placed.append((name, at, d))

# sanity: no overlaps between consecutive lines
for (n1, a1, d1), (n2, a2, _) in zip(placed, placed[1:]):
    if a1 + d1 > a2 - 0.2:
        print(f"WARNING overlap/tight: {n1} ends {a1 + d1:.2f} > {n2} starts {a2:.2f}")

# 3. voice track on the video timeline
inputs, chains, labels = [], [], []
for i, (name, at, d) in enumerate(placed):
    inputs += ["-i", str(HERE / f"lf_{name}.wav")]
    ms = int(round(at * 1000))
    chains.append(f"[{i}:a]adelay={ms}|{ms}[v{i}]")
    labels.append(f"[v{i}]")
fc = ";".join(chains) + ";" + "".join(labels) + \
     f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad,atrim=0:{VIDEO_DUR}[vo]"
run(inputs + ["-filter_complex", fc, "-map", "[vo]", "-ar", "48000", "-ac", "1", str(HERE / "vo_track.wav")])

# 4a. music loop: three copies joined with 3 s crossfades (longer than the film)
if not (HERE / "music_loop.wav").exists():
    M = str(HERE / "cinematic-electronic-background.mp3")
    run(["-i", M, "-i", M, "-i", M, "-filter_complex",
         "[0:a][1:a]acrossfade=d=3:c1=tri:c2=tri[a];[a][2:a]acrossfade=d=3:c1=tri:c2=tri,aresample=48000[out]",
         "-map", "[out]", "-c:a", "pcm_s16le", str(HERE / "music_loop.wav")])

# 4. music bed: looped, quiet, ducked by the voice, faded; then final mix
fc = (f"[1:a]atrim=0:{VIDEO_DUR},asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo,volume=-15dB,"
      f"afade=t=in:d=2,afade=t=out:st={VIDEO_DUR - 5:.2f}:d=5[mus];"
      "[0:a]aformat=channel_layouts=stereo,asplit=2[vo][sc];"
      "[mus][sc]sidechaincompress=threshold=0.05:ratio=3:attack=80:release=600:makeup=1[duck];"
      "[vo][duck]amix=inputs=2:normalize=0,alimiter=limit=0.89[mix]")
run(["-i", str(HERE / "vo_track.wav"), "-i", str(HERE / "music_loop.wav"), "-filter_complex", fc,
     "-map", "[mix]", "-ar", "48000", str(HERE / "final_mix.wav")])

json.dump([{"line": n, "at": round(a, 2), "dur": round(d, 2)} for n, a, d in placed],
          open(HERE / "placement.json", "w"), indent=1)
for n, a, d in placed:
    print(f"{n:12s} at {int(a // 60)}:{a % 60:05.2f}  ({d:.1f}s)")
print("video duration", VIDEO_DUR)
