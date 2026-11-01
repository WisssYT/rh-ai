"""Real-time screen recording of the local Talent Detective demo via the Chrome DevTools screencast.
Frames are saved with their capture timestamps; clicks are logged so a cursor can be drawn in the edit.
Usage: python record.py <clip-name>     (clips defined below)"""
import json, re, sys, time, base64, pathlib
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5173"
W, H, DSF = 1440, 810, 2
ROOT = pathlib.Path(__file__).resolve().parent.parent / "rec" / "clips"
demo = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "DEMO.md").read_text()
PW = re.search(r"Supervisor \| \S+ \| `([^`]+)`", demo).group(1)
BACKEND = "0e20e829143d481e8b45a8331c46e5e3"
ANALYST = "82a1074a09474ded99c10db1ea934cb7"


class Rec:
    def __init__(self, page, name):
        self.page, self.dir = page, ROOT / name
        self.dir.mkdir(parents=True, exist_ok=True)
        for f in self.dir.glob("*.jpg"):
            f.unlink()
        self.frames, self.events, self.t0 = [], [], None
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, ev):
        ts = ev["metadata"]["timestamp"]
        if self.t0 is None:
            self.t0 = ts
        fn = f"f{len(self.frames):05d}.jpg"
        (self.dir / fn).write_bytes(base64.b64decode(ev["data"]))
        self.frames.append([round(ts - self.t0, 3), fn])
        self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})

    def start(self):
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88, "maxWidth": W * DSF, "maxHeight": H * DSF})
        self.wait(400)

    def now(self):
        return round(time.time() - self.wall0, 3)

    def mark(self, label):
        self.events.append({"t": self.now(), "type": "mark", "label": label})

    def wait(self, ms):
        self.page.wait_for_timeout(ms)

    def click(self, loc, pause=750, label=None):
        loc.scroll_into_view_if_needed()
        bb = loc.bounding_box()
        x, y = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
        self.events.append({"t": self.now(), "type": "move", "x": x, "y": y, "label": label})
        self.wait(pause)
        self.events.append({"t": self.now(), "type": "click", "x": x, "y": y, "label": label})
        loc.click()

    def stop(self):
        self.wait(500)
        self.cdp.send("Page.stopScreencast")
        self.wait(200)
        json.dump({"frames": self.frames, "events": self.events, "w": W, "h": H, "dsf": DSF},
                  open(self.dir / "index.json", "w"))
        print(self.dir.name, "frames", len(self.frames), "dur", self.frames[-1][0] if self.frames else 0,
              "events", [(e["t"], e["type"], e.get("label")) for e in self.events])


CAND_PW = re.search(r"Strong candidate \| \S+ \| `([^`]+)`", demo).group(1)


def login(ctx, email):
    pg = ctx.new_page()
    cand = email.endswith("@example.test")
    pg.goto(BASE + ("/login" if cand else "/hr/login"))
    pg.fill("#email", email)
    pg.fill("#password", CAND_PW if cand else PW)
    with pg.expect_response(lambda r: "login" in r.url and r.request.method == "POST") as ri:
        pg.press("#password", "Enter")
    assert ri.value.status == 200, ri.value.status
    pg.wait_for_url(lambda u: "/login" not in u)
    return pg


def clip_analysis(pg):
    pg.goto(f"{BASE}/hr/jobs/{BACKEND}/applications"); pg.wait_for_timeout(1500)
    r = Rec(pg, "analysis"); r.wall0 = time.time(); r.start()
    r.wait(1200)
    r.click(pg.get_by_role("button", name=re.compile("Select all not evaluated")), label="select")
    r.wait(700)
    r.click(pg.get_by_role("button", name=re.compile("Review & authorize analysis")), label="review")
    r.wait(2200); r.mark("confirm")
    r.click(pg.get_by_role("button", name=re.compile("^Authorize run")), label="authorize")
    r.mark("running")
    for _ in range(90):
        r.wait(1000)
        txt = pg.locator("[aria-label='Latest analysis run']").inner_text() if pg.locator("[aria-label='Latest analysis run']").count() else ""
        if re.search(r"complet|finished|done", txt, re.I):
            break
    r.mark("done"); r.wait(1500)
    r.stop()


def clip_evidence(pg):
    pg.goto(f"{BASE}/hr/jobs/{BACKEND}/shortlist"); pg.wait_for_timeout(2000)
    r = Rec(pg, "evidence"); r.wall0 = time.time(); r.start()
    r.wait(1500); r.mark("ranking")
    row = pg.locator("tr", has_text="Amira")
    btn = row.get_by_role("button", name="Evidence") if row.count() else pg.get_by_role("button", name="Evidence")
    r.click(btn.first, label="evidence")
    r.wait(4500); r.mark("drawer")
    pg.mouse.wheel(0, 500); r.wait(2000)
    pg.keyboard.press("Escape"); r.wait(1200)
    sl = pg.locator("input[type=range]").first
    sl.scroll_into_view_if_needed(); r.wait(600)
    bb = sl.bounding_box()
    x0, y0 = bb["x"] + bb["width"] * 0.5, bb["y"] + bb["height"] / 2
    r.events.append({"t": r.now(), "type": "move", "x": x0, "y": y0, "label": "slider"}); r.wait(700)
    r.events.append({"t": r.now(), "type": "down", "x": x0, "y": y0})
    pg.mouse.move(x0, y0); pg.mouse.down()
    for i in range(1, 21):
        x = x0 + bb["width"] * 0.45 * i / 20
        pg.mouse.move(x, y0); r.events.append({"t": r.now(), "type": "drag", "x": x, "y": y0}); r.wait(60)
    pg.mouse.up(); r.events.append({"t": r.now(), "type": "up", "x": x, "y": y0})
    r.wait(3500); r.mark("reweighted")
    r.stop()


def clip_attacker(pg):
    pg.goto(f"{BASE}/hr/jobs/{BACKEND}/shortlist"); pg.wait_for_timeout(2000)
    r = Rec(pg, "attacker"); r.wall0 = time.time(); r.start()
    r.wait(800)
    row = pg.locator("tr", has_text="Omar Saidi")
    r.click(row.get_by_role("button", name="Evidence").first, label="omar")
    r.wait(4500); r.mark("flag")
    r.stop()


def clip_inbox(pg):
    pg.goto(f"{BASE}/hr/inbox"); pg.wait_for_timeout(1500)
    r = Rec(pg, "inbox"); r.wall0 = time.time(); r.start()
    r.wait(800)
    b = pg.get_by_role("button", name=re.compile("Prepare brief"))
    if b.count():
        r.click(b.first, label="brief")
    r.wait(6000); r.mark("brief")
    sus = pg.get_by_text(re.compile("Urgent: update to my file"))
    if sus.count():
        r.click(sus.first, label="suspicious"); r.wait(3500)
    r.stop()


def clip_dashboard(pg):
    pg.goto(f"{BASE}/hr/dashboard"); pg.wait_for_timeout(2500)
    r = Rec(pg, "dashboard"); r.wall0 = time.time(); r.start()
    r.wait(2500); r.mark("top")
    pg.mouse.move(900, 500)
    for i in range(14):
        pg.mouse.wheel(0, 60); r.wait(70)
    r.wait(1200)
    for i in range(14):
        pg.mouse.wheel(0, 60); r.wait(70)
    r.wait(3500); r.mark("coverage")
    r.stop()


def clip_approvals(pg):
    pg.goto(f"{BASE}/hr/approvals"); pg.wait_for_timeout(2000)
    r = Rec(pg, "approvals"); r.wall0 = time.time(); r.start()
    r.wait(3500); r.mark("card")
    pg.mouse.wheel(0, 300); r.wait(2000)
    r.click(pg.get_by_role("link", name=re.compile("Calendar")).first, label="calendar")
    r.wait(3500)
    r.stop()


def clip_careers(pg):
    pg.goto(f"{BASE}/candidate"); pg.wait_for_timeout(800)
    r = Rec(pg, "careers"); r.wall0 = time.time(); r.start()
    pg.goto(f"{BASE}/jobs"); r.wait(3800); r.mark("hero")
    r.click(pg.get_by_role("link", name=re.compile("Backend Developer")).first, label="job")
    r.wait(2200)
    pg.mouse.move(700, 500)
    for i in range(12):
        pg.mouse.wheel(0, 70); r.wait(80)
    r.wait(1500)
    pg.set_input_files("#cv", str(pathlib.Path(__file__).resolve().parents[2] / "frontend" / "e2e" / "fixtures" / "dana_cv.pdf")); r.wait(1200)
    r.click(pg.locator("input[type=checkbox]").last, label="ack", pause=500); r.wait(600)
    r.click(pg.get_by_role("button", name=re.compile("Submit application")), label="submit")
    r.wait(4500); r.mark("tracker")
    r.stop()


def clip_phone(pg):
    pg.goto(f"{BASE}/jobs"); pg.wait_for_timeout(500)
    r = Rec(pg, "phone"); r.wall0 = time.time(); r.start()
    pg.reload(); r.wait(3000)
    for i in range(16):
        pg.evaluate('window.scrollBy(0, 60)'); r.wait(90)
    r.wait(1200)
    r.click(pg.get_by_role("link", name=re.compile("Data Analyst")).first, label="job")
    r.wait(3000)
    r.stop()


def clip_rubric(pg):
    pg.goto(f"{BASE}/hr/jobs/{BACKEND}/rubric"); pg.wait_for_timeout(2000)
    r = Rec(pg, "rubric"); r.wall0 = time.time(); r.start()
    r.wait(2500)
    pg.mouse.move(800, 500)
    for i in range(18):
        pg.mouse.wheel(0, 60); r.wait(90)
    r.wait(3000)
    r.stop()


def clip_send(pg):
    pg.goto(f"{BASE}/hr/approvals"); pg.wait_for_timeout(2000)
    r = Rec(pg, "send"); r.wall0 = time.time(); r.start()
    r.wait(1500)
    r.click(pg.get_by_role("button", name=re.compile("Approve & send this exact message")).first, label="send")
    r.wait(1500)
    dlg = pg.get_by_role("button", name=re.compile("^(Confirm|Approve|Send)", re.I))
    if dlg.count() and dlg.first.is_visible():
        r.click(dlg.first, label="confirm")
    r.wait(4000); r.mark("sent")
    r.stop()


def clip_book(pg):
    pg.goto(f"{BASE}/candidate"); pg.wait_for_timeout(1500)
    r = Rec(pg, "book"); r.wall0 = time.time(); r.start()
    r.wait(1500)
    link = pg.locator("a[href*='/candidate/interviews/']")
    r.click(link.first, label="invite")
    r.wait(2500)
    slot = pg.locator("button", has_text=re.compile(r"\d{1,2}:\d{2}")).first
    r.click(slot, label="slot"); r.wait(1200)
    r.click(pg.get_by_role("button", name=re.compile("Request this time")), label="request")
    r.wait(3500); r.mark("requested")
    r.stop()


def clip_confirm(pg):
    pg.goto(f"{BASE}/hr/calendar"); pg.wait_for_timeout(2500)
    r = Rec(pg, "confirm"); r.wall0 = time.time(); r.start()
    r.wait(1500)
    b = pg.get_by_role("button", name=re.compile("Confirm interview"))
    if b.count():
        r.click(b.first, label="confirm")
    r.wait(3500); r.mark("confirmed")
    r.stop()


def clip_kit(pg):
    pg.goto(f"{BASE}/hr/interviews"); pg.wait_for_timeout(2000)
    r = Rec(pg, "kit"); r.wall0 = time.time(); r.start()
    r.wait(1500)
    lk = pg.locator("a[href*='/hr/interviews/']")
    r.click(lk.first, label="open"); r.wait(2200)
    b = pg.get_by_role("button", name=re.compile("Prepare with AI|Regenerate with AI"))
    if b.count():
        r.click(b.first, label="kit")
    r.wait(4000)
    pg.mouse.move(800, 500)
    for i in range(10):
        pg.mouse.wheel(0, 60); r.wait(90)
    r.wait(2500)
    r.stop()


def clip_followups(pg):
    pg.goto(f"{BASE}/hr/followups"); pg.wait_for_timeout(2000)
    r = Rec(pg, "followups"); r.wall0 = time.time(); r.start()
    r.wait(3000)
    r.click(pg.get_by_role("link", name=re.compile("^Reports")).first, label="reports"); r.wait(2000)
    r.click(pg.get_by_role("link", name=re.compile("Open report")).first, label="report"); r.wait(3000)
    pg.mouse.move(800, 500)
    for i in range(10):
        pg.mouse.wheel(0, 70); r.wait(90)
    r.wait(2000)
    r.stop()


def clip_supervisor(pg):
    pg.goto(f"{BASE}/supervisor"); pg.wait_for_timeout(2500)
    r = Rec(pg, "supervisor"); r.wall0 = time.time(); r.start()
    r.wait(2500)
    for name in ["Approvals", "Audit"]:
        t = pg.get_by_role("tab", name=re.compile(name))
        if not t.count():
            t = pg.get_by_role("button", name=re.compile("^" + name))
        r.click(t.first, label=name.lower()); r.wait(3200)
    r.stop()


CLIPS = {"analysis": ("recruiter", clip_analysis), "evidence": ("recruiter", clip_evidence),
         "attacker": ("recruiter", clip_attacker), "inbox": ("recruiter", clip_inbox),
         "dashboard": ("recruiter", clip_dashboard), "approvals": ("analyst.recruiter", clip_approvals),
         "careers": ("demo.candidate", clip_careers), "phone": ("demo.candidate", clip_phone),
         "rubric": ("recruiter", clip_rubric), "send": ("analyst.recruiter", clip_send),
         "book": ("samir.belhadj", clip_book), "confirm": ("analyst.recruiter", clip_confirm),
         "kit": ("analyst.recruiter", clip_kit), "followups": ("analyst.recruiter", clip_followups),
         "supervisor": ("supervisor", clip_supervisor)}

if __name__ == "__main__":
    names = sys.argv[1:] or list(CLIPS)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for n in names:
            who, fn = CLIPS[n]
            vp = {"width": 390, "height": 844} if n == "phone" else {"width": W, "height": H}
            ctx = b.new_context(viewport=vp, device_scale_factor=DSF, is_mobile=(n == "phone"), has_touch=(n == "phone"))
            dom = "example.test" if who in ("demo.candidate", "samir.belhadj") else "nordlicht.example.test"
            pg = login(ctx, f"{who}@{dom}")
            try:
                fn(pg)
            except Exception as e:
                print(n, "FAILED", type(e).__name__, str(e)[:300])
                pg.screenshot(path=str(ROOT / f"{n}_fail.jpg"), type="jpeg", quality=50)
            ctx.close()
        b.close()
