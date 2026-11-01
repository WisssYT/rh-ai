import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, fmt } from "../../api";
import { useAuth } from "../../auth";
import { ChartCard, CoverageGrid, Funnel, Ledger, LineChart, Meter, ScoreSpread, StackedBars } from "../../components/charts";
import { Badge, Empty, ErrorBox, SkeletonRows, Stat } from "../../components/ui";
import { EvidenceDrawer } from "./HrJobs";

const REFRESH_MS = 8000;

function hours(h: number | null | undefined) {
  if (h === null || h === undefined) return "-";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} d`;
}

export function DashboardPage() {
  const { status } = useAuth();
  const nav = useNavigate();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string>("");
  const [days, setDays] = useState(30);
  const [live, setLive] = useState(true);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [drawer, setDrawer] = useState<string | null>(null);
  const [counts, setCounts] = useState<any>(null);
  const inflight = useRef(false);

  const load = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    try {
      const q = new URLSearchParams({ days: String(days) });
      if (jobId) q.set("job_id", jobId);
      const [d, c] = await Promise.all([api(`/api/hr/dashboard?${q}`), api("/api/hr/nav-counts")]);
      setData(d);
      setCounts(c);
      setUpdated(new Date());
      setError(null);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      inflight.current = false;
    }
  }, [days, jobId]);
  useEffect(() => {
    void load();
  }, [load]);
  // Live refresh while the tab is visible: charts fill in as the worker evaluates and people approve.
  useEffect(() => {
    if (!live) return;
    const t = window.setInterval(() => document.visibilityState === "visible" && load(), REFRESH_MS);
    return () => window.clearInterval(t);
  }, [live, load]);

  const tz = status?.timezone ?? data?.timezone;
  if (!data) {
    return (
      <div className="page">
        <div className="page-head"><div><h1>Dashboard</h1><p className="muted">Recorded facts from your assigned jobs.</p></div></div>
        <ErrorBox error={error} onRetry={load} />
        {!error && <SkeletonRows rows={6} cols={4} />}
      </div>
    );
  }
  const k = data.kpis;
  const sp = data.score_spread;
  const sec = data.security;
  const ai = data.ai;
  const dec = data.decisions;
  const cal = data.calendar;
  const synthetic = (k.evaluation_sources?.replay ?? 0) > 0;
  const toApps = (stage?: string) => {
    if (stage) nav(`/hr/candidates?stage=${stage}`);
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Computed from recorded facts in {data.jobs.length === 1 ? "your assigned job" : `${data.jobs.length} jobs`} - no model calls, nothing decided here.</p>
          <div className="dash-head-meta" style={{ marginTop: 6 }}>
            <span><span className={`live-dot${live ? "" : " paused"}`} aria-hidden />{live ? `live · every ${REFRESH_MS / 1000}s` : "paused"}</span>
            {updated && <span>updated {updated.toLocaleTimeString("en-GB")}</span>}
            <span>llm calls: {data.llm_calls}</span>
          </div>
        </div>
        <div className="row">
          <label className="sr-only" htmlFor="dash-job">Job for score charts</label>
          <select id="dash-job" value={jobId} onChange={(e) => setJobId(e.target.value)} style={{ width: "auto" }}>
            <option value="">Score charts: busiest job</option>
            {data.jobs.map((j: any) => <option key={j.id} value={j.id}>{j.title}</option>)}
          </select>
          <label className="sr-only" htmlFor="dash-days">Time range</label>
          <select id="dash-days" value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ width: "auto" }}>
            {[14, 30, 60, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
          <button className="btn" onClick={() => setLive(!live)} aria-pressed={live}>{live ? "Pause" : "Resume"} live</button>
        </div>
      </div>
      <ErrorBox error={error} onRetry={load} />

      <div className="stats" style={{ marginBottom: 16 }}>
        <Stat label="active applications" value={k.applications} />
        <Stat label="evaluated" value={k.evaluated} />
        <Stat label="shortlisted" value={k.shortlisted} />
        <Stat label="invited" value={k.invited} />
        <Stat label="interviews booked" value={k.booked} />
        <Stat label="interviewed" value={k.interviewed} />
        <Stat label="waiting for approval" value={counts?.approvals ?? "-"} />
        <Stat label="open review items" value={counts?.review ?? "-"} />
      </div>

      <div className="grid grid-dash">
        <ChartCard id="c-funnel" title="Hiring funnel" note="How many active applications reached at least each stage. Click a stage to list those candidates."
          aside={k.declined || k.withdrawn ? <span className="small muted mono">{k.declined} declined · {k.withdrawn} withdrawn</span> : undefined}>
          {k.applications ? <Funnel steps={data.funnel} onSelect={toApps} /> : <Empty title="No applications yet" />}
        </ChartCard>
        <ChartCard id="c-spread" title={`Score spread${sp ? ` · ${sp.job.title}` : ""}`}
          note="Dot = evidence-backed lower bound; hatch = what unknown criteria could still add. Order is provisional - not a decision."
          aside={sp && <span className="row" style={{ gap: 6 }}>{synthetic && <Badge tone="neutral">replay · synthetic</Badge>}<Link className="small" to={`/hr/jobs/${sp.job.id}/shortlist`}>Ranking →</Link></span>}>
          {sp && sp.points.length ? (
            <>
              <ScoreSpread points={sp.points} cutoff={sp.cutoff} minScore={sp.min_suggest_score} onPick={setDrawer} />
              {sp.unscored > 0 && <p className="small muted" style={{ margin: "6px 0 0" }}>{sp.unscored} not scored yet (not evaluated, stale or needs manual review).</p>}
            </>
          ) : <Empty title="Nothing scored yet">Authorize an analysis run on the job's Applications tab.</Empty>}
        </ChartCard>
      </div>

      <div className="grid grid-dash">
        <ChartCard id="c-time" title="Applications over time" note={`Daily submissions per job, last ${data.days} days (${tz}).`}>
          <LineChart days={data.timeline.days} series={data.timeline.series.map((s: any) => ({ key: s.job_id, label: s.title, values: s.values }))} annotations={data.timeline.annotations} />
        </ChartCard>
        <ChartCard id="c-cov" title={`Evidence coverage${data.coverage ? ` · ${data.coverage.job.title}` : ""}`}
          note="Top candidates × criteria. Darker = stronger cited evidence (0-4); hatched = the CV gives no evidence. * required. Hatched cells are what interview kits ask about.">
          {data.coverage && data.coverage.rows.length ? (
            <CoverageGrid criteria={data.coverage.criteria} rows={data.coverage.rows} onPick={setDrawer} />
          ) : <Empty title="No evaluated candidates yet" />}
        </ChartCard>
      </div>

      <div className="grid grid-dash-3">
        <ChartCard id="c-sec" title="Security ledger" note="What the guardrails caught. Nothing here was acted on automatically."
          aside={<Link className="small" to="/hr/review">Review queue →</Link>}>
          <Ledger rows={[
            { label: "Prompt-injection attempts in CVs", value: sec.injection_flags, tone: sec.injection_flags ? "bad" : "muted" },
            { label: "Suspicious inbound emails", value: sec.suspicious_messages, tone: sec.suspicious_messages ? "bad" : "muted" },
            { label: "AI outputs rejected by schema", value: sec.schema_rejections, tone: sec.schema_rejections ? "warn" : "muted", hint: "company-wide" },
            { label: "Evaluations failing quote checks", value: sec.quote_check_rejections, tone: sec.quote_check_rejections ? "warn" : "muted" },
            { label: "Contact mismatches held back", value: sec.contact_mismatch, tone: sec.contact_mismatch ? "warn" : "muted" },
            { label: "Documents routed to a human", value: sec.manual_review_documents, tone: sec.manual_review_documents ? "warn" : "muted" },
            { label: "Emails blocked at dispatch", value: sec.emails_blocked, tone: sec.emails_blocked ? "bad" : "muted" },
          ]} />
        </ChartCard>
        <ChartCard id="c-ai" title="AI usage" note="Company-wide, last 14 days. Token figures come only from provider usage metadata."
          aside={<Badge tone={ai.mode === "live" ? "ai" : "neutral"}>{ai.mode === "live" ? "live" : "replay · synthetic"}</Badge>}>
          <Meter value={ai.live_calls_today} max={ai.daily_budget} label="Live calls today vs daily budget" />
          <StackedBars label="AI calls per day" days={ai.days} height={110} layers={[
            { key: "live", label: "live LLM", values: ai.live, fill: "var(--green)" },
            { key: "replay", label: "replay (not an LLM)", values: ai.replay, fill: "var(--rule-strong)", hatch: true },
          ]} />
          <Ledger rows={[
            { label: "Prompt-prefix cache share", value: ai.cached_share === null ? "not observed" : `${ai.cached_share}%`, tone: ai.cached_share === null ? "muted" : "good" },
            { label: "Calls with reported usage", value: ai.tokens.reported_calls, tone: "muted" },
            ...Object.entries(ai.purposes as Record<string, number>).map(([p, n]) => ({ label: `· ${p}`, value: n, tone: "muted" as const })),
          ]} />
        </ChartCard>
        <ChartCard id="c-cal" title="Calendar & decisions" note={`Interview slots for the next 14 days (${tz}) and how fast people decide.`}
          aside={<Link className="small" to="/hr/calendar">Calendar →</Link>}>
          <StackedBars label="Interview slots per day" days={cal.days} height={110} layers={[
            { key: "booked", label: "booked", values: cal.booked, fill: "var(--ink)" },
            { key: "held", label: "requested", values: cal.held, fill: "var(--warn)" },
            { key: "available", label: "free", values: cal.available, fill: "#a9c7b8" },
          ]} />
          <Ledger rows={[
            { label: "Invitation → time requested (median)", value: hours(cal.invite_to_request_hours.median), tone: "muted" },
            { label: "Draft → email approved (median)", value: hours(dec.email_approval_hours.median) },
            { label: "Shortlist draft → approved (median)", value: hours(dec.shortlist_approval_hours.median) },
            { label: "Emails waiting for a human", value: dec.pending_drafts, tone: dec.pending_drafts ? "warn" : "muted" },
            { label: "Sent via outbox", value: dec.outbox.sent ?? 0, tone: "good" },
            { label: "Failed / delivery unknown", value: (dec.outbox.failed ?? 0) + (dec.outbox.delivery_unknown ?? 0), tone: (dec.outbox.failed ?? 0) + (dec.outbox.delivery_unknown ?? 0) ? "bad" : "muted" },
          ]} />
        </ChartCard>
      </div>
      <p className="small muted" style={{ marginTop: 14 }}>Generated {fmt.dateTime(data.generated_at, tz)}. Hours are measured between recorded timestamps; no estimates or invented metrics.</p>
      <EvidenceDrawer appId={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}
