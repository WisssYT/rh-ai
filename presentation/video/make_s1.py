"""Write film_s1.html: the opening scene alone, retimed to last D seconds (counter + falling CVs scaled to fit)."""
import sys, pathlib
HERE = pathlib.Path(__file__).resolve().parent
D = float(sys.argv[1]) if len(sys.argv) > 1 else 4.5
s = (HERE / "film.html").read_text(encoding="utf-8")
count_end = round(max(1.6, D * 0.62), 2)          # counter reaches 1,000 at ~62 % of the scene
stagger = round((count_end - 0.15) / 70, 4)       # 70 sheets land while the counter climbs
rep = [
    ('const SC=[["s1",0,9],["s2",9,17],["s3",17,26],["s4",26,41],["s5",41,55],["s6",55,71],["s7",71,82],["s8",82,93],["s9",93,101],["s10",101,110]];',
     f'const SC=[["s1",0,{D}]];'),
    ("window.DURATION=110;", f"window.DURATION={D};"),
    ("t0=0.3+i*0.085;", f"t0=0.15+i*{stagger};"),
    ("P(t,.3,6.6)", f"P(t,.15,{count_end})"),
    ("E(P(t,s.t0,s.t0+.7))", "E(P(t,s.t0,s.t0+.45))"),
]
for a, b in rep:
    assert a in s, a
    s = s.replace(a, b)
(HERE / "film_s1.html").write_text(s, encoding="utf-8")
print("film_s1.html", D, count_end, stagger)
