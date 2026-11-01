"""Render film.html frame by frame to an MP4 (or stills with --stills t1,t2,...)."""
import os, subprocess, sys, pathlib
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")  # needs an ffmpeg build with libx264
FPS = 30

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="film.html"); ap.add_argument("--out", default="talent-detective-pitch.mp4")
    ap.add_argument("--stills"); ap.add_argument("--range"); ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()
    stills = [float(x) for x in a.stills.split(",")] if a.stills else None
    out = HERE / a.out
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto((HERE / a.html).as_uri())
        pg.wait_for_load_state("networkidle")
        pg.evaluate("document.fonts.ready")
        if stills:
            for t in stills:
                pg.evaluate(f"render({t})")
                pg.screenshot(path=str(HERE / f"still_{a.html[:4]}_{t:06.2f}.jpg"), type="jpeg", quality=80)
            return
        global FPS
        FPS = a.fps
        dur = pg.evaluate("DURATION")
        n0, n = 0, int(dur * FPS)
        if a.range:
            r0, r1 = (float(x) for x in a.range.split(","))
            n0, n = int(r0 * FPS), min(n, int(r1 * FPS))
        ff = subprocess.Popen([FFMPEG, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
                               "-c:v", "mjpeg", "-i", "-", "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
        for i in range(n0, n):
            pg.evaluate(f"render({i / FPS})")
            ff.stdin.write(pg.screenshot(type="jpeg", quality=92))
            if i % 300 == 0:
                print(f"frame {i}/{n}", flush=True)
        ff.stdin.close(); ff.wait()
        b.close()
    print("done", out)

if __name__ == "__main__":
    main()
