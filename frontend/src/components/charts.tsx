// Hand-drawn SVG/CSS charts in the "evidence on paper" language: 1px ink rules, ledger green for data,
// hatching for "unknown / could still add", mono figures and direct margin-note labels instead of legends.
// Marker yellow is NOT used here - it stays reserved for quoted evidence.
// Motion: one draw-in on mount (removed under prefers-reduced-motion), nothing runs when idle.
import { useEffect, useId, useRef, useState, type MouseEvent, type ReactNode } from "react";

export const SERIES = ["var(--ink)", "var(--green)", "var(--info)", "var(--warn)", "var(--bad)"];

export function useWidth<T extends HTMLElement>(fallback = 560) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((e) => setW(Math.max(220, Math.floor(e[0].contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function Hatch({ id, color = "var(--rule-strong)" }: { id: string; color?: string }) {
  return (
    <pattern id={id} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">
      <rect width="5" height="5" fill="transparent" />
      <line x1="0" y1="0" x2="0" y2="5" stroke={color} strokeWidth="2" />
    </pattern>
  );
}

function niceMax(v: number) {
  if (v <= 4) return 4;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

const shortDay = (iso: string) => new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" }).format(new Date(iso + "T00:00:00Z"));

export function ChartCard({ title, note, children, aside, id }: { title: string; note?: ReactNode; children: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <section className="card chart-card" aria-labelledby={id}>
      <div className="chart-head">
        <h2 id={id}>{title}</h2>
        {aside}
      </div>
      {note && <p className="chart-note">{note}</p>}
      {children}
    </section>
  );
}

/* ---------- Funnel: ledger rows, one bar per stage, drop-off as a margin figure ---------- */
export function Funnel({ steps, onSelect }: { steps: { stage: string; label: string; count: number }[]; onSelect?: (stage: string) => void }) {
  const max = Math.max(1, steps[0]?.count ?? 1);
  return (
    <ol className="funnel" aria-label="Hiring funnel">
      {steps.map((s, i) => {
        const drop = i > 0 ? steps[i - 1].count - s.count : 0;
        const pct = max ? Math.round((s.count * 100) / max) : 0;
        return (
          <li key={s.stage} style={{ animationDelay: `${i * 60}ms` }}>
            <button type="button" className="funnel-row" onClick={() => onSelect?.(s.stage)} disabled={!onSelect} aria-label={`${s.label}: ${s.count}`}>
              <span className="funnel-label">{s.label}</span>
              <span className="funnel-track">
                <span className="funnel-bar" style={{ width: `${Math.max(s.count ? 1.5 : 0, (s.count * 100) / max)}%`, animationDelay: `${i * 60}ms` }} />
              </span>
              <span className="funnel-n">{s.count}</span>
              <span className="funnel-drop">{i === 0 ? "" : drop > 0 ? `−${drop}` : "·"}</span>
              <span className="funnel-pct">{i === 0 ? "" : `${pct}%`}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/* ---------- Line chart: daily counts, direct end labels, annotations as margin notes ---------- */
export function LineChart({ days, series, annotations = [], height = 200 }: {
  days: string[]; series: { key: string; label: string; values: number[] }[]; annotations?: { date: string; label: string }[]; height?: number;
}) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const notes = annotations.filter((a) => days.includes(a.date)).sort((a, b) => days.indexOf(a.date) - days.indexOf(b.date)).slice(0, 3);
  const padL = 30, padR = 118, padT = 22 + 12 * Math.max(0, notes.length - 1), padB = 24;
  const iw = Math.max(40, w - padL - padR), ih = height - padT - padB;
  const max = niceMax(Math.max(1, ...series.flatMap((s) => s.values)));
  const x = (i: number) => padL + (days.length <= 1 ? 0 : (i * iw) / (days.length - 1));
  const y = (v: number) => padT + ih - (v * ih) / max;
  const ticks = [0, max / 2, max];
  const step = Math.max(1, Math.ceil(days.length / Math.max(2, Math.floor(iw / 70))));
  function onMove(e: MouseEvent<SVGRectElement>) {
    const r = (e.target as SVGRectElement).getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (days.length - 1));
    setHover(Math.max(0, Math.min(days.length - 1, i)));
  }
  // de-collide end labels
  const ends = series.map((s, k) => ({ k, y: y(s.values[s.values.length - 1] ?? 0) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;
  const endY = Object.fromEntries(ends.map((e) => [e.k, e.y]));
  return (
    <div ref={ref} className="chart-wrap">
      <svg width={w} height={height} role="img" aria-label={`Applications per day over ${days.length} days: ` + series.map((s) => `${s.label} ${s.values.reduce((a, b) => a + b, 0)}`).join(", ")}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={padL + iw} y1={y(t)} y2={y(t)} className={t === 0 ? "axis" : "grid"} />
            <text x={padL - 6} y={y(t) + 4} textAnchor="end" className="tick">{Math.round(t)}</text>
          </g>
        ))}
        {days.map((d, i) => (i % step === 0 || i === days.length - 1) && (
          <text key={d} x={x(i)} y={height - 6} textAnchor={i === 0 ? "start" : i === days.length - 1 ? "end" : "middle"} className="tick">{shortDay(d)}</text>
        ))}
        {notes.map((a, n) => {
          // stacked margin notes so close publication dates never overprint each other
          const i = days.indexOf(a.date);
          const ty = 11 + n * 12;
          const text = a.label.length > 34 ? a.label.slice(0, 33) + "…" : a.label;
          const right = x(i) + text.length * 6.2 + 12 > w; // anchor left of the line when the note would overflow
          return (
            <g key={a.label}>
              <line x1={x(i)} x2={x(i)} y1={ty + 3} y2={padT + ih} className="annot" />
              <text x={right ? x(i) - 4 : x(i) + 4} y={ty} textAnchor={right ? "end" : "start"} className="annot-text">{right ? `${text} ↓` : `↓ ${text}`}</text>
            </g>
          );
        })}
        {series.map((s, k) => {
          const d = s.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
          const last = s.values.length - 1;
          return (
            <g key={s.key}>
              <path d={d} pathLength={1} className="line draw" stroke={SERIES[k % SERIES.length]} style={{ animationDelay: `${k * 120}ms` }} />
              <circle cx={x(last)} cy={y(s.values[last] ?? 0)} r={2.6} fill={SERIES[k % SERIES.length]} />
              <text x={padL + iw + 8} y={endY[k] + 4} className="end-label" fill={SERIES[k % SERIES.length]}>
                {s.label.length > 15 ? s.label.slice(0, 14) + "…" : s.label} · {s.values.reduce((a, b) => a + b, 0)}
              </text>
            </g>
          );
        })}
        {hover !== null && (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={padT} y2={padT + ih} className="cursor" />
            {series.map((s, k) => <circle key={s.key} cx={x(hover)} cy={y(s.values[hover])} r={3.2} fill="#fff" stroke={SERIES[k % SERIES.length]} strokeWidth={1.5} />)}
          </g>
        )}
        <rect x={padL} y={padT} width={iw} height={ih} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
      </svg>
      {hover !== null && (
        <div className="tip" style={{ left: Math.min(w - 170, x(hover) + 10), top: 8 }} role="status">
          <div className="tip-h">{shortDay(days[hover])}</div>
          {series.map((s, k) => <div key={s.key}><i style={{ background: SERIES[k % SERIES.length] }} />{s.label}<b>{s.values[hover]}</b></div>)}
        </div>
      )}
    </div>
  );
}

/* ---------- Score spread: one row per candidate, dot = evidence lower bound, hatch = could still add ---------- */
export interface SpreadPoint { application_id: string; name: string; lower: number; upper: number; coverage: number; proposed: boolean; flagged: boolean; near_tie: boolean; position: number }
export function ScoreSpread({ points, cutoff, minScore, onPick, limit = 24 }: { points: SpreadPoint[]; cutoff: number | null; minScore: number; onPick?: (id: string) => void; limit?: number }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [all, setAll] = useState(false);
  const [hover, setHover] = useState<SpreadPoint | null>(null);
  const hid = useId().replace(/:/g, "");
  const shown = all ? points : points.slice(0, limit);
  const rowH = 20, padL = Math.min(150, Math.max(96, w * 0.26)), padR = 12, padT = 18, padB = 22;
  const iw = Math.max(60, w - padL - padR);
  const h = padT + shown.length * rowH + padB;
  const x = (v: number) => padL + (v * iw) / 100;
  return (
    <div ref={ref} className="chart-wrap">
      <svg width={w} height={h} role="img" aria-label={`Score spread for ${points.length} evaluated candidates; cutoff ${cutoff ?? "-"}`}>
        <defs><Hatch id={`h${hid}`} /></defs>
        {[0, 25, 50, 75, 100].map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={padT - 4} y2={h - padB} className="grid" />
            <text x={x(t)} y={h - 6} textAnchor="middle" className="tick">{t}</text>
          </g>
        ))}
        {cutoff !== null && (
          <g>
            <line x1={x(cutoff)} x2={x(cutoff)} y1={padT - 10} y2={h - padB} className="cutoff" />
            <text x={x(cutoff) + 4} y={padT - 8} className="annot-text">cutoff {cutoff.toFixed(0)}{cutoff === minScore ? " (minimum)" : ""}</text>
          </g>
        )}
        {shown.map((p, i) => {
          const cy = padT + i * rowH + rowH / 2;
          return (
            <g key={p.application_id} className={`spread-row${onPick ? " pick" : ""}`} onClick={() => onPick?.(p.application_id)}
               onMouseEnter={() => setHover(p)} onMouseLeave={() => setHover(null)} tabIndex={onPick ? 0 : -1}
               onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onPick?.(p.application_id)}
               role={onPick ? "button" : undefined} aria-label={`${p.name}: evidence ${p.lower.toFixed(1)}, up to ${p.upper.toFixed(1)}${p.proposed ? ", in proposal" : ""}${p.flagged ? ", flagged" : ""}`}>
              <rect x={0} y={cy - rowH / 2} width={w} height={rowH} className="row-hit" />
              <text x={padL - 10} y={cy + 4} textAnchor="end" className={`row-label${p.proposed ? " strong" : ""}`}>
                {p.name.length > 20 ? p.name.slice(0, 19) + "…" : p.name}
              </text>
              <line x1={x(0)} x2={x(100)} y1={cy} y2={cy} className="baseline" />
              {p.upper > p.lower && <rect x={x(p.lower)} y={cy - 4} width={x(p.upper) - x(p.lower)} height={8} fill={`url(#h${hid})`} className="grow" />}
              <line x1={x(0)} x2={x(p.lower)} y1={cy} y2={cy} className={`stem grow${p.proposed ? " on" : ""}`} />
              <circle cx={x(p.lower)} cy={cy} r={4.2} className={`dot${p.proposed ? " on" : ""}${p.flagged ? " flagged" : ""}`} />
              {p.near_tie && <text x={x(p.upper) + 6} y={cy + 4} className="tick">≈</text>}
            </g>
          );
        })}
      </svg>
      {hover && (
        <div className="tip" style={{ left: Math.min(w - 190, x(hover.upper) + 12), top: padT + shown.indexOf(hover) * rowH - 6 }} role="status">
          <div className="tip-h">#{hover.position} · {hover.name}</div>
          <div>evidence<b>{hover.lower.toFixed(1)}</b></div>
          <div>could reach<b>{hover.upper.toFixed(1)}</b></div>
          <div>coverage<b>{hover.coverage.toFixed(0)}%</b></div>
          {hover.flagged && <div className="tip-flag">instruction-like text in CV</div>}
        </div>
      )}
      <div className="chart-legend">
        <span><i className="lg-dot on" />in proposal</span><span><i className="lg-dot" />not proposed</span>
        <span><i className="lg-dot flagged" />flagged</span><span><i className="lg-hatch" />unknown criteria could add</span>
        {points.length > limit && <button className="btn btn-ghost btn-small" onClick={() => setAll(!all)}>{all ? `Top ${limit} only` : `Show all ${points.length}`}</button>}
      </div>
    </div>
  );
}

/* ---------- Evidence coverage grid: candidates × criteria, darker = stronger rating, hatch = no evidence ---------- */
export function CoverageGrid({ criteria, rows, onPick }: { criteria: { id: string; label: string; required: boolean }[]; rows: { application_id: string; name: string; ratings: Record<string, number | null> }[]; onPick?: (id: string) => void }) {
  const missing = Object.fromEntries(criteria.map((c) => [c.id, rows.filter((r) => r.ratings[c.id] == null).length]));
  return (
    <div className="cov-wrap">
      <table className="cov" aria-label="Evidence coverage per criterion">
        <thead>
          <tr>
            <th scope="col"><span className="sr-only">Candidate</span></th>
            {criteria.map((c) => <th key={c.id} scope="col" title={c.label}><span>{c.label}{c.required ? " *" : ""}</span></th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.application_id} style={{ animationDelay: `${i * 25}ms` }}>
              <th scope="row">{onPick ? <button type="button" className="linkish" onClick={() => onPick(r.application_id)}>{r.name}</button> : r.name}</th>
              {criteria.map((c) => {
                const v = r.ratings[c.id];
                return (
                  <td key={c.id} className={v == null ? "cov-unknown" : `cov-${v}`} title={`${r.name} · ${c.label}: ${v == null ? "no evidence" : `${v}/4`}`}>
                    {v == null ? <span className="sr-only">no evidence</span> : v}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" className="muted">no evidence</th>
            {criteria.map((c) => <td key={c.id} className="cov-foot">{missing[c.id]}/{rows.length}</td>)}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/* ---------- Stacked daily bars (AI calls, calendar load) ---------- */
export function StackedBars({ days, layers, height = 120, label }: {
  days: string[]; layers: { key: string; label: string; values: number[]; fill: string; hatch?: boolean }[]; height?: number; label: string;
}) {
  const [ref, w] = useWidth<HTMLDivElement>(320);
  const [hover, setHover] = useState<number | null>(null);
  const hid = useId().replace(/:/g, "");
  const padL = 22, padR = 4, padT = 8, padB = 20;
  const iw = w - padL - padR, ih = height - padT - padB;
  const totals = days.map((_, i) => layers.reduce((a, l) => a + (l.values[i] ?? 0), 0));
  const max = niceMax(Math.max(1, ...totals));
  const bw = iw / days.length;
  return (
    <div ref={ref} className="chart-wrap">
      <svg width={w} height={height} role="img" aria-label={`${label}: ` + layers.map((l) => `${l.label} ${l.values.reduce((a, b) => a + b, 0)}`).join(", ")}>
        <defs><Hatch id={`s${hid}`} color="var(--ink-2)" /></defs>
        <line x1={padL} x2={padL + iw} y1={padT + ih} y2={padT + ih} className="axis" />
        <line x1={padL} x2={padL + iw} y1={padT} y2={padT} className="grid" />
        <text x={padL - 4} y={padT + 4} textAnchor="end" className="tick">{max}</text>
        <text x={padL - 4} y={padT + ih + 3} textAnchor="end" className="tick">0</text>
        {days.map((d, i) => {
          let acc = 0;
          return (
            <g key={d} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={padL + i * bw} y={padT} width={bw} height={ih} fill="transparent" />
              {layers.map((l) => {
                const v = l.values[i] ?? 0;
                if (!v) return null;
                const hgt = (v * ih) / max;
                acc += hgt;
                return <rect key={l.key} className="bar grow-y" x={padL + i * bw + bw * 0.18} width={bw * 0.64} y={padT + ih - acc} height={hgt}
                  fill={l.hatch ? `url(#s${hid})` : l.fill} stroke={l.hatch ? "var(--ink-2)" : "none"} strokeWidth={l.hatch ? 0.75 : 0} />;
              })}
              {(i === 0 || i === days.length - 1 || i === Math.floor(days.length / 2)) && (
                <text x={padL + i * bw + bw / 2} y={height - 5} textAnchor="middle" className="tick">{shortDay(d)}</text>
              )}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div className="tip" style={{ left: Math.min(w - 150, padL + hover * bw + bw), top: 2 }} role="status">
          <div className="tip-h">{shortDay(days[hover])}</div>
          {layers.map((l) => <div key={l.key}><i style={{ background: l.hatch ? "var(--rule-strong)" : l.fill }} />{l.label}<b>{l.values[hover] ?? 0}</b></div>)}
        </div>
      )}
      <div className="chart-legend">
        {layers.map((l) => <span key={l.key}><i className={l.hatch ? "lg-hatch" : "lg-sq"} style={l.hatch ? undefined : { background: l.fill }} />{l.label} · {l.values.reduce((a, b) => a + b, 0)}</span>)}
      </div>
    </div>
  );
}

/* ---------- Thin gauge ---------- */
export function Meter({ value, max, label, tone = "green" }: { value: number; max: number; label: string; tone?: "green" | "warn" | "bad" | "ink" }) {
  const pct = max ? Math.min(100, (value * 100) / max) : 0;
  return (
    <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
      <div className="meter-track"><div className={`meter-fill meter-${pct >= 90 ? "bad" : pct >= 70 ? "warn" : tone}`} style={{ width: `${pct}%` }} /></div>
      <div className="meter-label"><span>{label}</span><span className="mono">{value}/{max}</span></div>
    </div>
  );
}

/* ---------- Ledger list: label · dotted leader · figure ---------- */
export function Ledger({ rows }: { rows: { label: ReactNode; value: ReactNode; tone?: "bad" | "warn" | "good" | "muted"; hint?: string }[] }) {
  return (
    <dl className="ledger">
      {rows.map((r, i) => (
        <div key={i} className={r.tone ? `ledger-${r.tone}` : undefined} title={r.hint}>
          <dt>{r.label}</dt>
          <dd>{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}
