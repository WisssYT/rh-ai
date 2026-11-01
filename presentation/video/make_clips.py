"""Cut clean deck clips from the raw recordings (real-time frames) and from the rendered film."""
import json, subprocess, pathlib
S = pathlib.Path(__file__).resolve().parent.parent
FF = str(S / "ff" / "ffmpeg")
OUT = pathlib.Path(__file__).resolve().parent
REC = S / "rec" / "clips"

def from_frames(name, clip, t0, t1, hold=1.5, jump=None):
    fr = json.load(open(REC / clip / "index.json"))["frames"]
    segs = [(t0, t1)] if not jump else jump
    lines = []
    for a, b in segs:
        cur = [f for f in fr if f[0] <= a][-1:] + [f for f in fr if a < f[0] < b]
        for i, (ts, fn) in enumerate(cur):
            start = max(ts, a)
            end = cur[i + 1][0] if i + 1 < len(cur) else b
            d = max(0.034, end - start)
            lines.append(f"file '{REC / clip / fn}'\nduration {d:.3f}")
    last = lines[-1].split("\n")[0]
    lines.append(f"{last}\nduration {hold:.3f}\n{last}")
    lst = OUT / f"{name}.txt"
    lst.write_text("\n".join(lines) + "\n")
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-vf", ("scale=780:-2" if name == "phone" else "scale=1440:810") + ":flags=lanczos,fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "22", "-movflags", "+faststart", str(OUT / f"{name}.mp4")], check=True)
    still(name, max(0.5, (t1 - t0) * 0.8 if not jump else 4))

def from_film(name, src, t0, t1):
    subprocess.run([FF, "-y", "-loglevel", "error", "-ss", str(t0), "-to", str(t1), "-i", str(S / "video" / src),
                    "-vf", "scale=1440:810:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-an", "-movflags", "+faststart", str(OUT / f"{name}.mp4")], check=True)
    still(name, (t1 - t0) * 0.75)

def still(name, t):
    subprocess.run([FF, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(OUT / f"{name}.mp4"), "-frames:v", "1",
                    "-q:v", "3", str(OUT / f"{name}.jpg")], check=True)

if __name__ == "__main__":
    from_frames("careers", "careers", 0.0, 15.8, hold=2.5)
    from_frames("phone", "phone", 0.0, 7.8, hold=2.0)
    from_frames("rubric", "rubric", 0.0, 6.0, hold=2.0)
    from_frames("analysis", "analysis", 1.2, 14.6, hold=2.5)
    from_frames("evidence", "evidence", 1.8, 14.7, hold=2.5)
    from_frames("attacker", "attacker", 0.8, 2.6, hold=5.0)
    from_frames("inbox", "inbox", 0, 0, hold=4.0, jump=[(0.5, 2.6), (8.2, 9.3)])
    from_frames("send", "send", 1.4, 5.64, hold=3.5)
    from_frames("book", "book", 1.4, 8.88, hold=3.5)
    from_frames("dashboard", "dashboard", 0.0, 6.09, hold=2.5)
    from_frames("supervisor", "supervisor", 1.5, 7.6, hold=3.0)
    from_frames("kit", "kit", 1.5, 10.39, hold=3.0)
    from_film("m_overload", "talent-detective-pitch.mp4", 0.0, 9.0)
    from_film("m_workflow", "talent-detective-pitch.mp4", 26.0, 41.0)
    from_film("m_security", "talent-detective-pitch.mp4", 55.0, 71.0)
    from_film("m_traction", "talent-detective-pitch.mp4", 71.0, 82.0)
    print("ok")
