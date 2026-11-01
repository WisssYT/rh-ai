import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, fmt } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Drawer, Empty, ErrorBox, Loading, Notice, ScoreBar, SkeletonRows, Stat, StateBadge } from "../../components/ui";

export function JobNav({ job }: { job: any }) {
  return (
    <>
      <div className="page-head" style={{ marginBottom: 10 }}>
        <div>
          <p className="crumb"><Link to="/hr">Overview</Link> / Jobs</p>
          <h1>{job.title} <StateBadge state={job.status} /></h1>
          <div className="ws-meta">
            <span>rubric r{job.rubric?.revision ?? "-"}</span>
            <span>weights r{job.weights?.revision ?? "-"}</span>
            <span>{job.applications} applications</span>
            {job.contact_review > 0 && <span>{job.contact_review} contact review</span>}
            <span>{job.approved_shortlist ? `shortlist r${job.approved_shortlist.revision} · ${job.approved_shortlist.members} approved` : "no approved shortlist"}</span>
          </div>
        </div>
      </div>
      <nav className="ws-tabs" aria-label="Job sections">
        <NavLink to={`/hr/jobs/${job.id}/applications`}>Applications</NavLink>
        <NavLink to={`/hr/jobs/${job.id}/shortlist`}>Ranking & shortlist</NavLink>
        <NavLink to={`/hr/jobs/${job.id}/rubric`}>Job & criteria</NavLink>
      </nav>
    </>
  );
}

export function useJob(id: string | undefined) {
  const [job, setJob] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    if (!id) return;
    api(`/api/hr/jobs/${id}`).then(setJob).catch((e) => setError(e.message));
  }, [id]);
  useEffect(reload, [reload]);
  return { job, error, reload, setJob };
}

export function HrDashboard() {
  const { status, user } = useAuth();
  const nav = useNavigate();
  const [jobs, setJobs] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const load = useCallback(() => {
    setError(null);
    api("/api/hr/jobs").then((r) => setJobs(r.items)).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      const j = await api("/api/hr/jobs", { body: { title } });
      nav(`/hr/jobs/${j.id}/rubric`);
    } catch (err) {
      setError((err as ApiError).message);
    }
  }
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="muted">{user?.role === "supervisor" ? "All jobs in the company." : "Jobs assigned to you."}</p>
        </div>
        {creating ? (
          <form className="row" onSubmit={create}>
            <label htmlFor="newjob" className="sr-only">Job title</label>
            <input id="newjob" placeholder="Job title" value={title} onChange={(e) => setTitle(e.target.value)} minLength={3} required style={{ width: 240 }} autoFocus />
            <button className="btn btn-primary">Create draft</button>
            <button type="button" className="btn btn-ghost" onClick={() => setCreating(false)}>Cancel</button>
          </form>
        ) : (
          <button className="btn" onClick={() => setCreating(true)}>New job</button>
        )}
      </div>
      {status?.preflight?.map((p) => <Notice key={p} tone="warn"><span>{p}</span></Notice>)}
      <ErrorBox error={error} onRetry={load} />
      {!jobs && !error && <SkeletonRows rows={3} cols={6} />}
      {jobs?.length === 0 && <div className="card"><Empty title="No jobs assigned to you" icon="doc">A supervisor assigns recruiters to jobs.</Empty></div>}
      {jobs && jobs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th className="num">Applications</th>
                <th className="num">Contact review</th>
                <th>Criteria</th>
                <th>Shortlist</th>
                <th>Assigned</th>
                <th><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td>
                    <Link to={`/hr/jobs/${j.id}/applications`}><strong>{j.title}</strong></Link>
                    <div className="small muted">{j.location}</div>
                  </td>
                  <td className="num">{j.applications}</td>
                  <td className="num">{j.contact_review || <span className="muted">0</span>}</td>
                  <td>{j.rubric ? <span className="mono">r{j.rubric.revision}</span> : <Badge tone="warn">not approved</Badge>} {j.rubric_draft_pending && j.rubric && <Badge tone="warn">draft pending</Badge>}</td>
                  <td>{j.approved_shortlist ? <><StateBadge state="human_approved" /> <span className="mono small">r{j.approved_shortlist.revision} · {j.approved_shortlist.members}</span></> : <span className="muted">-</span>}</td>
                  <td className="small">{j.assignees.map((a: any) => a.full_name).join(", ") || <span className="muted">-</span>}</td>
                  <td><StateBadge state={j.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------

function RunPanel({ jobId, onFinished }: { jobId: string; onFinished: () => void }) {
  const [runs, setRuns] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number>();
  const load = useCallback(() => {
    api(`/api/hr/jobs/${jobId}/analysis-runs`)
      .then((r) => {
        setRuns(r.items);
        const active = r.items[0] && ["queued", "running"].includes(r.items[0].status);
        window.clearTimeout(timer.current);
        if (active) timer.current = window.setTimeout(load, 1500);
        else onFinished();
      })
      .catch((e) => setError(e.message));
  }, [jobId, onFinished]);
  useEffect(() => {
    load();
    return () => window.clearTimeout(timer.current);
  }, [load]);
  async function control(id: string, action: string) {
    try {
      await api(`/api/hr/analysis-runs/${id}/${action}`, { method: "POST" });
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  if (!runs) return null;
  const r = runs[0];
  if (!r) return <ErrorBox error={error} />;
  const done = (r.tasks.done ?? 0) + (r.tasks.needs_review ?? 0) + (r.tasks.failed ?? 0);
  const u = r.usage;
  return (
    <section className="card" aria-label="Latest analysis run">
      <div className="spread">
        <h2 style={{ margin: 0 }}>
          Analysis run <StateBadge state={r.status} /> <Badge tone={r.mode === "live" ? "ai" : "neutral"} plain>{r.mode === "live" ? `live · ${r.model_id}` : "replay · synthetic"}</Badge>
        </h2>
        <div className="row">
          {["queued", "running"].includes(r.status) && <button className="btn btn-small" onClick={() => control(r.id, "pause")}>Pause</button>}
          {r.status === "quota_paused" && <button className="btn btn-small btn-primary" onClick={() => control(r.id, "resume")}>Resume</button>}
          {["queued", "running", "quota_paused"].includes(r.status) && <button className="btn btn-small btn-danger" onClick={() => control(r.id, "cancel")}>Cancel</button>}
        </div>
      </div>
      <p className="small muted" style={{ margin: "6px 0 0" }}>
        Authorized by {r.authorized_by} ({r.authorized_role}), {fmt.dateTime(r.authorized_at)} · {r.application_count} applications · rubric r{r.rubric_revision} · prompt <span className="mono">{r.prompt_version}</span>
      </p>
      {r.pause_reason && <Notice tone="warn"><span>Paused: {r.pause_reason}. Finished work is kept; resume when quota recovers. Replay is never substituted automatically.</span></Notice>}
      <ErrorBox error={error} />
      <progress max={r.application_count} value={done} aria-label="Analysis progress" />
      <div className="stats">
        <Stat label="processed" value={`${done}/${r.application_count}`} />
        <Stat label="needs review" value={r.tasks.needs_review ?? 0} />
        <Stat label="waiting" value={(r.tasks.queued ?? 0) + (r.tasks.running ?? 0)} />
        <Stat label="saved-evaluation reuse" value={u.saved_evaluation_reuse} hint="Identical dependencies found in PostgreSQL: zero model calls" />
        {r.mode === "live" ? (
          <>
            <Stat label="provider calls" value={u.provider_attempts} hint="Including retries and 429 responses" />
            <Stat label="input / output tokens" value={u.prompt_tokens === null ? "not reported" : `${u.prompt_tokens} / ${u.output_tokens ?? "-"}`} />
            <Stat label="prefix-cache tokens" value={u.cached_tokens_reported_calls ? u.cached_tokens : "not observed"} hint="Only from provider usage metadata; missing means unknown" />
            <Stat label="thinking tokens" value={u.thinking_tokens ?? "not reported"} />
            <Stat label="avg latency" value={u.avg_latency_ms !== null ? `${u.avg_latency_ms} ms` : "-"} />
            <Stat label="invalid / 429" value={`${u.invalid_output} / ${u.quota_responses}`} />
          </>
        ) : (
          <Stat label="replay generations" value={u.replay_generations} hint="Synthetic deterministic adapter - not an LLM; no provider usage" />
        )}
      </div>
    </section>
  );
}

function Rating({ value }: { value: number }) {
  return (
    <span className="rating" aria-hidden>
      {[1, 2, 3, 4].map((i) => <i key={i} className={i <= value ? "on" : ""} />)}
    </span>
  );
}

export function EvidenceDrawer({ appId, onClose }: { appId: string | null; onClose: () => void }) {
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);
  useEffect(() => {
    setD(null);
    setError(null);
    setShowText(false);
    if (appId) api(`/api/hr/applications/${appId}`).then(setD).catch((e) => setError(e.message));
  }, [appId]);
  const ev = d?.current_evaluation;
  const crit = new Map((d?.rubric ?? []).map((c: any) => [c.id, c]));
  const per = new Map((d?.score?.per_criterion ?? []).map((p: any) => [p.criterion_id, p]));
  return (
    <Drawer open={!!appId} title={d ? d.candidate_name : "Evidence"} onClose={onClose}>
      <ErrorBox error={error} />
      {!d && !error && <Loading />}
      {d && (
        <div className="stack">
          <div className="spread">
            <div className="row">
              <StateBadge state={d.contact_status} label={d.contact_status === "ok" ? "contact ok" : "contact review"} />
              <StateBadge state={d.parse_status} label={d.parse_status === "parsed" ? "text extracted" : "manual review"} />
              {ev && <StateBadge state={ev.state} />}
              {ev && <Badge tone={ev.source === "live" ? "ai" : "neutral"} plain>{ev.source === "live" ? `LLM · ${ev.model_id}` : ev.source === "replay" ? "replay · synthetic" : ev.source}</Badge>}
              {ev?.stale && <Badge tone="warn">stale</Badge>}
            </div>
            <a className="btn btn-small" href={`/api/hr/applications/${d.id}/resume`}>Original PDF</a>
          </div>
          <div className="email-preview">
            <dl>
              <dt>account</dt><dd>{d.account_email}</dd>
              <dt>CV email</dt><dd>{d.cv_email ?? <span className="muted">none / ambiguous</span>}</dd>
              <dt>submitted</dt><dd>{fmt.dateTime(d.submitted_at)} · version {d.revision}</dd>
            </dl>
          </div>
          {d.contact_status !== "ok" && <Notice tone="warn"><span>{d.contact_reason}. Invitations are blocked until the candidate corrects their CV.</span></Notice>}
          {d.parse_flags?.length > 0 && <Notice tone="warn"><span>Document flags: <span className="mono">{d.parse_flags.join(", ")}</span></span></Notice>}
          {!ev && <Empty title="Not evaluated yet">Authorize an analysis run to create a provisional assessment.</Empty>}
          {ev && (
            <>
              {d.score && (
                <div className="stats">
                  <Stat label="evidence score (lower bound)" value={fmt.num(d.score.lower)} />
                  <Stat label="possible upper bound" value={fmt.num(d.score.upper)} />
                  <Stat label="evidence coverage" value={`${fmt.num(d.score.coverage, 0)}%`} />
                </div>
              )}
              {ev.flags.length > 0 && <Notice tone="warn"><span>Review flags: <span className="mono">{ev.flags.join(", ")}</span></span></Notice>}
              {ev.validation_errors.length > 0 && (
                <Notice tone="warn"><span>Model output was rejected after bounded retries; no scores are used. {ev.validation_errors.slice(0, 3).join("; ")}</span></Notice>
              )}
              {ev.result.job_related_summary && <p style={{ margin: 0 }}><span className="muted small">Provisional summary · </span>{ev.result.job_related_summary}</p>}
              <div>
                {ev.result.criteria?.map((c: any) => {
                  const def: any = crit.get(c.criterion_id);
                  const p: any = per.get(c.criterion_id);
                  return (
                    <div key={c.criterion_id} className="criterion">
                      <div className="spread">
                        <strong>{def?.label ?? c.criterion_id}{def?.required && <span className="mono muted small"> · required</span>}</strong>
                        <span className="small">
                          {c.status === "supported" ? <><Rating value={c.rating} />{c.rating}/4</> : <Badge tone="warn">unknown</Badge>}
                          {p && <span className="mono muted"> · w{fmt.num(p.weight, 0)} → +{fmt.num(p.contribution)}</span>}
                        </span>
                      </div>
                      {c.status === "supported" && def?.anchors && <div className="small muted">Anchor {c.rating}: {def.anchors[String(c.rating)]}</div>}
                      {c.explanation && <p className="small" style={{ margin: "6px 0" }}>{c.explanation}</p>}
                      {c.evidence.map((e: any, i: number) => (
                        <p key={i} className="quote">
                          <q>{e.quote}</q>
                          <span className="ref">p{e.page} · {e.segment_id}</span>
                        </p>
                      ))}
                      {c.unknowns?.length > 0 && <div className="small muted">Open: {c.unknowns.join("; ")}</div>}
                    </div>
                  );
                })}
              </div>
              <p className="small muted">
                Quotes are candidate claims, not verified facts. A matching quote does not prove the interpretation - review it. Prompt <span className="mono">{ev.prompt_version}</span> · rubric r{ev.rubric_revision} · {fmt.dateTime(ev.created_at)}
              </p>
            </>
          )}
          <button className="btn btn-small" onClick={() => setShowText(!showText)} aria-expanded={showText}>{showText ? "Hide" : "Show"} extracted text</button>
          {showText && (
            <div className="cvtext">
              {d.extracted_pages?.length ? d.extracted_pages.map((p: any) => `--- page ${p.page} ---\n` + p.segments.map((s: any) => `[${s.id}] ${s.text}`).join("\n")).join("\n\n") : "No extractable text (possibly scanned) - review the original PDF."}
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}

export function ApplicationsPage() {
  const { id } = useParams();
  const { job, error: jobError, reload: reloadJob } = useJob(id);
  const { status } = useAuth();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({ q: "", parse_status: "", contact_status: "", evaluation: "", page: 1 });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sp, setSp] = useSearchParams();
  const [drawer, setDrawerState] = useState<string | null>(sp.get("evidence"));
  // Deep link from the dashboard / review queue: ?evidence=<application id>
  const setDrawer = (v: string | null) => {
    setDrawerState(v);
    if (!v && sp.has("evidence")) {
      const n = new URLSearchParams(sp);
      n.delete("evidence");
      setSp(n, { replace: true });
    }
  };
  const [confirming, setConfirming] = useState(false);
  const [runKey, setRunKey] = useState(0);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    const p = new URLSearchParams({ page: String(filters.page), page_size: "25" });
    for (const k of ["q", "parse_status", "contact_status", "evaluation"] as const) if (filters[k]) p.set(k, filters[k]);
    api(`/api/hr/jobs/${id}/applications?${p}`).then(setData).catch((e) => setError(e.message));
  }, [id, filters]);
  useEffect(load, [load]);
  const onRunFinished = useCallback(() => load(), [load]);

  function toggle(aid: string) {
    const s = new Set(selected);
    s.has(aid) ? s.delete(aid) : s.add(aid);
    setSelected(s);
  }
  async function authorize() {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/hr/jobs/${id}/analysis-runs`, { body: { application_ids: [...selected], rubric_revision: job.rubric.revision, confirm_scope: true } });
      setConfirming(false);
      setSelected(new Set());
      setRunKey((k) => k + 1);
      reloadJob();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  if (jobError) return <ErrorBox error={jobError} />;
  if (!job) return <SkeletonRows rows={8} cols={6} />;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const filtered = filters.q || filters.parse_status || filters.contact_status || filters.evaluation;
  const pageIds: string[] = data?.items.map((a: any) => a.id) ?? [];
  const allOnPage = pageIds.length > 0 && pageIds.every((x) => selected.has(x));
  return (
    <div className="page">
      <JobNav job={job} />
      <RunPanel key={runKey} jobId={job.id} onFinished={onRunFinished} />
      <section className="card" aria-label="Applications">
        <div className="toolbar">
          <div className="filters">
            <label className="sr-only" htmlFor="q">Search name or email</label>
            <input id="q" type="search" placeholder="Search name or email" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value, page: 1 })} />
            <select aria-label="Document" value={filters.parse_status} onChange={(e) => setFilters({ ...filters, parse_status: e.target.value, page: 1 })}>
              <option value="">Any document</option>
              <option value="parsed">Text extracted</option>
              <option value="needs_review">Needs manual review</option>
            </select>
            <select aria-label="Contact" value={filters.contact_status} onChange={(e) => setFilters({ ...filters, contact_status: e.target.value, page: 1 })}>
              <option value="">Any contact status</option>
              <option value="ok">Contact ok</option>
              <option value="review_required">Contact review</option>
            </select>
            <select aria-label="Evaluation" value={filters.evaluation} onChange={(e) => setFilters({ ...filters, evaluation: e.target.value, page: 1 })}>
              <option value="">Any evaluation</option>
              <option value="none">Not evaluated</option>
              <option value="provisional">Provisional</option>
              <option value="needs_review">Needs review</option>
              <option value="invalid">Invalid output</option>
            </select>
            {filtered && <button className="btn btn-ghost btn-small" onClick={() => setFilters({ q: "", parse_status: "", contact_status: "", evaluation: "", page: 1 })}>Clear filters</button>}
          </div>
          <div className="row">
            <button className="btn btn-small" onClick={() => setSelected(new Set(data?.unevaluated_ids))} disabled={!data?.unevaluated_ids.length}>
              Select all not evaluated ({data?.unevaluated_ids.length ?? 0})
            </button>
            <button className="btn btn-primary btn-small" disabled={!selected.size || !job.rubric} title={!job.rubric ? "Approve the criteria first" : !selected.size ? "Select applications first" : undefined} onClick={() => setConfirming(true)}>
              Review & authorize analysis ({selected.size})
            </button>
          </div>
        </div>
        {confirming && (
          <div className="confirm" role="dialog" aria-label="Confirm analysis scope">
            <div>
              <strong>Authorize analysis of {selected.size} application{selected.size === 1 ? "" : "s"}?</strong>
              <div className="small">
                {job.title} · rubric r{job.rubric.revision} · AI mode{" "}
                <strong>{status?.ai_mode === "live" ? `LIVE (${status.model_id}) - uses free-tier quota` : "REPLAY (synthetic, not an LLM)"}</strong>
              </div>
              <div className="small muted">Stores provisional evaluations and run logs for exactly this scope. It does not shortlist, reject or contact anyone.</div>
            </div>
            <div className="row">
              <button className="btn btn-primary" onClick={authorize} disabled={busy}>{busy ? "Authorizing…" : "Authorize run"}</button>
              <button className="btn" onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          </div>
        )}
        <ErrorBox error={error} onRetry={load} />
        {!data && <SkeletonRows rows={8} cols={6} />}
        {data && data.items.length === 0 && (
          <Empty title={filtered ? "No applications match these filters" : "No applications yet"} icon="search">
            {filtered ? "Clear the filters to see everyone." : "Applications appear here as soon as candidates submit them."}
          </Empty>
        )}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 36 }}>
                    <input type="checkbox" aria-label="Select all on this page" checked={allOnPage}
                      onChange={() => { const s = new Set(selected); pageIds.forEach((x) => (allOnPage ? s.delete(x) : s.add(x))); setSelected(s); }} />
                  </th>
                  <th>Candidate</th>
                  <th>Submitted</th>
                  <th>Document</th>
                  <th>Contact</th>
                  <th>Evaluation</th>
                  <th><span className="sr-only">Details</span></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((a: any) => (
                  <tr key={a.id} className={selected.has(a.id) ? "selected" : ""}>
                    <td><input type="checkbox" aria-label={`Select ${a.candidate_name}`} checked={selected.has(a.id)} onChange={() => toggle(a.id)} /></td>
                    <td><strong>{a.candidate_name}</strong><div className="small muted">{a.account_email}</div></td>
                    <td className="small mono">{fmt.dateTime(a.submitted_at, status?.timezone)}{a.revision > 1 && <div>v{a.revision}</div>}</td>
                    <td className="small">
                      <StateBadge state={a.parse_status} label={a.parse_status === "parsed" ? "extracted" : "manual review"} />{" "}
                      <a href={`/api/hr/applications/${a.id}/resume`} aria-label={`PDF of ${a.candidate_name}`}>PDF</a> <span className="muted mono">{a.pages}p</span>
                    </td>
                    <td><StateBadge state={a.contact_status} /></td>
                    <td>
                      {a.evaluation ? (
                        <span className="row" style={{ gap: 4 }}>
                          <StateBadge state={a.evaluation.state} />
                          <span className="mono small muted">{a.evaluation.source}</span>
                          {a.evaluation.rubric_revision !== job.rubric?.revision && <Badge tone="warn">stale</Badge>}
                        </span>
                      ) : (
                        <StateBadge state="not_evaluated" />
                      )}
                    </td>
                    <td><button className="btn btn-small" onClick={() => setDrawer(a.id)}>Evidence</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <div className="spread" style={{ marginTop: 10 }}>
            <span className="small muted">{data.total} total{selected.size > 0 && ` · ${selected.size} selected`}{selected.size > 0 && <> · <button className="btn btn-ghost btn-small" onClick={() => setSelected(new Set())}>clear selection</button></>}</span>
            {pages > 1 && (
              <div className="row">
                <button className="btn btn-small" disabled={filters.page <= 1} onClick={() => setFilters({ ...filters, page: filters.page - 1 })}>Previous</button>
                <span className="small mono">{filters.page} / {pages}</span>
                <button className="btn btn-small" disabled={filters.page >= pages} onClick={() => setFilters({ ...filters, page: filters.page + 1 })}>Next</button>
              </div>
            )}
          </div>
        )}
      </section>
      <EvidenceDrawer appId={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}

export { ScoreBar };
