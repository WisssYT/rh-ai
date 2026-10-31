import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, fmt } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Drawer, Empty, ErrorBox, Loading, Notice, ScoreBar, Stat, StateBadge } from "../../components/ui";

export function JobNav({ job }: { job: any }) {
  return (
    <div className="page-head">
      <div>
        <p className="small"><Link to="/hr">← All jobs</Link></p>
        <h1>{job.title} <StateBadge state={job.status} /></h1>
        <p className="muted small">
          Rubric r{job.rubric?.revision ?? "-"} · weights r{job.weights?.revision ?? "-"} · {job.applications} applications
          {job.approved_shortlist && <> · approved shortlist r{job.approved_shortlist.revision} ({job.approved_shortlist.members})</>}
        </p>
      </div>
      <nav className="tabs" aria-label="Job sections" style={{ marginBottom: 0, borderBottom: 0 }}>
        <NavLink className="btn btn-small" to={`/hr/jobs/${job.id}/applications`}>Applications & analysis</NavLink>
        <NavLink className="btn btn-small" to={`/hr/jobs/${job.id}/shortlist`}>Ranking & shortlist</NavLink>
        <NavLink className="btn btn-small" to={`/hr/jobs/${job.id}/rubric`}>Job & rubric</NavLink>
      </nav>
    </div>
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
  const load = useCallback(() => {
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
          <h1>Recruiting dashboard</h1>
          <p className="muted">{user?.role === "supervisor" ? "Company-wide view (supervisor)." : "Jobs assigned to you."}</p>
        </div>
        <form className="row" onSubmit={create}>
          <label htmlFor="newjob" className="small">New job</label>
          <input id="newjob" placeholder="Job title" value={title} onChange={(e) => setTitle(e.target.value)} minLength={3} required style={{ width: 220 }} />
          <button className="btn">Create draft</button>
        </form>
      </div>
      {status?.preflight?.map((p) => <Notice key={p} tone="warn">{p}</Notice>)}
      <ErrorBox error={error} onRetry={load} />
      {!jobs && !error && <Loading />}
      {jobs?.length === 0 && <Empty title="No jobs assigned">A supervisor assigns jobs to recruiters.</Empty>}
      <div className="grid grid-2">
        {jobs?.map((j) => (
          <div key={j.id} className="card">
            <div className="spread">
              <h2>{j.title}</h2>
              <StateBadge state={j.status} />
            </div>
            <div className="stats">
              <Stat label="applications" value={j.applications} />
              <Stat label="contact review" value={j.contact_review} />
              <Stat label="shortlist" value={j.approved_shortlist ? `r${j.approved_shortlist.revision} · ${j.approved_shortlist.members}` : "none"} />
            </div>
            <p className="small muted">Assigned: {j.assignees.map((a: any) => a.full_name).join(", ") || "-"}</p>
            <div className="row">
              <Link className="btn btn-primary btn-small" to={`/hr/jobs/${j.id}/applications`}>Applications</Link>
              <Link className="btn btn-small" to={`/hr/jobs/${j.id}/shortlist`}>Shortlist</Link>
              <Link className="btn btn-small" to={`/hr/jobs/${j.id}/rubric`}>Rubric</Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------

function RunPanel({ jobId, onFinished }: { jobId: string; onFinished: () => void }) {
  const [runs, setRuns] = useState<any[]>([]);
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
  const r = runs[0];
  if (!r) return <ErrorBox error={error} />;
  const done = (r.tasks.done ?? 0) + (r.tasks.needs_review ?? 0) + (r.tasks.failed ?? 0);
  const u = r.usage;
  return (
    <div className="card">
      <div className="spread">
        <h2>
          Latest analysis run <StateBadge state={r.status} /> <StateBadge state={r.mode} label={r.mode === "live" ? `live · ${r.model_id}` : "replay · synthetic"} />
        </h2>
        <div className="row">
          {["queued", "running"].includes(r.status) && <button className="btn btn-small" onClick={() => control(r.id, "pause")}>Pause</button>}
          {r.status === "quota_paused" && <button className="btn btn-small btn-primary" onClick={() => control(r.id, "resume")}>Resume</button>}
          {["queued", "running", "quota_paused"].includes(r.status) && <button className="btn btn-small btn-danger" onClick={() => control(r.id, "cancel")}>Cancel</button>}
        </div>
      </div>
      {r.pause_reason && <Notice tone="warn">Paused: {r.pause_reason}. Completed work is kept; resume when quota recovers. Replay is never substituted automatically.</Notice>}
      <ErrorBox error={error} />
      <p className="small muted">
        Authorized by {r.authorized_by} ({r.authorized_role}) on {fmt.dateTime(r.authorized_at)} for {r.application_count} applications · rubric r{r.rubric_revision} · prompt {r.prompt_version}
      </p>
      <progress max={r.application_count} value={done} style={{ width: "100%" }} aria-label="Analysis progress" />
      <div className="stats">
        <Stat label="processed" value={`${done}/${r.application_count}`} />
        <Stat label="needs review" value={r.tasks.needs_review ?? 0} />
        <Stat label="queued" value={(r.tasks.queued ?? 0) + (r.tasks.running ?? 0)} />
        <Stat label="saved-evaluation reuse" value={u.saved_evaluation_reuse} hint="Application-result cache in PostgreSQL: identical dependencies, zero model calls" />
        {r.mode === "live" ? (
          <>
            <Stat label="provider calls" value={u.provider_attempts} hint="Including retries and 429 responses" />
            <Stat label="input / output tokens" value={u.prompt_tokens === null ? "not reported" : `${u.prompt_tokens} / ${u.output_tokens ?? "-"}`} />
            <Stat
              label="provider prefix-cache tokens"
              value={u.cached_tokens_reported_calls ? u.cached_tokens : "not observed"}
              hint="Only from provider usage metadata (cached_content_token_count). Missing = unknown, never assumed."
            />
            <Stat label="thinking tokens" value={u.thinking_tokens ?? "not reported"} />
            <Stat label="avg latency" value={u.avg_latency_ms !== null ? `${u.avg_latency_ms} ms` : "-"} />
            <Stat label="invalid outputs / 429s" value={`${u.invalid_output} / ${u.quota_responses}`} />
          </>
        ) : (
          <Stat label="replay generations" value={u.replay_generations} hint="Synthetic deterministic adapter - not an LLM; no provider usage" />
        )}
      </div>
    </div>
  );
}

export function EvidenceDrawer({ appId, onClose }: { appId: string | null; onClose: () => void }) {
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setD(null);
    setError(null);
    if (appId) api(`/api/hr/applications/${appId}`).then(setD).catch((e) => setError(e.message));
  }, [appId]);
  const ev = d?.current_evaluation;
  const crit = new Map((d?.rubric ?? []).map((c: any) => [c.id, c]));
  const per = new Map((d?.score?.per_criterion ?? []).map((p: any) => [p.criterion_id, p]));
  return (
    <Drawer open={!!appId} title={d ? `Evidence · ${d.candidate_name}` : "Evidence"} onClose={onClose}>
      <ErrorBox error={error} />
      {!d && !error && <Loading />}
      {d && (
        <div className="stack">
          <div className="row">
            <StateBadge state={d.contact_status} label={`contact: ${d.contact_status.replace("_", " ")}`} />
            <StateBadge state={d.parse_status} label={`document: ${d.parse_status.replace("_", " ")}`} />
            {ev && <StateBadge state={ev.state} label={`evaluation: ${ev.state.replace("_", " ")}`} />}
            {ev && <Badge tone={ev.source === "live" ? "ai" : "neutral"}>{ev.source === "live" ? `LLM · ${ev.model_id}` : ev.source === "replay" ? "REPLAY synthetic" : ev.source}</Badge>}
            {ev?.stale && <Badge tone="warn">stale - rubric changed</Badge>}
            <a className="btn btn-small" href={`/api/hr/applications/${d.id}/resume`}>Download original PDF</a>
          </div>
          {d.contact_status !== "ok" && <Notice tone="warn">{d.contact_reason}. Invitations are blocked until the candidate corrects their CV. Account: {d.account_email}; CV: {d.cv_email ?? "none"}.</Notice>}
          {d.parse_flags?.length > 0 && <Notice tone="warn">Document flags: {d.parse_flags.join(", ")}</Notice>}
          {!ev && <Empty title="Not evaluated">Authorize an analysis run to create a provisional assessment.</Empty>}
          {ev && (
            <>
              {d.score && (
                <div className="stats">
                  <Stat label="evidence score (lower bound)" value={fmt.num(d.score.lower)} />
                  <Stat label="possible upper bound" value={fmt.num(d.score.upper)} />
                  <Stat label="evidence coverage" value={`${fmt.num(d.score.coverage, 0)}%`} />
                </div>
              )}
              {ev.flags.length > 0 && <Notice tone="warn">Review flags: {ev.flags.join(", ")}</Notice>}
              {ev.validation_errors.length > 0 && (
                <Notice tone="warn">
                  Model output was rejected after bounded retries and no scores are used. Errors: {ev.validation_errors.slice(0, 4).join("; ")}
                </Notice>
              )}
              <p className="small"><strong>Summary (provisional):</strong> {ev.result.job_related_summary || "-"}</p>
              {ev.result.criteria?.map((c: any) => {
                const def: any = crit.get(c.criterion_id);
                const p: any = per.get(c.criterion_id);
                return (
                  <div key={c.criterion_id} className="criterion">
                    <div className="spread">
                      <strong>{def?.label ?? c.criterion_id} {def?.required && <Badge tone="info">required</Badge>}</strong>
                      <span>
                        {c.status === "supported" ? <Badge tone="good">rating {c.rating}/4</Badge> : <Badge tone="warn">unknown</Badge>}
                        {p && <span className="small muted"> · weight {fmt.num(p.weight, 0)} → +{fmt.num(p.contribution)}</span>}
                      </span>
                    </div>
                    {c.status === "supported" && def?.anchors && <div className="small muted">Anchor {c.rating}: {def.anchors[String(c.rating)]}</div>}
                    {c.explanation && <p className="small">{c.explanation}</p>}
                    {c.evidence.map((e: any, i: number) => (
                      <div key={i} className="quote">
                        “{e.quote}” <span className="ref">page {e.page} · {e.segment_id} · candidate claim, not verified</span>
                      </div>
                    ))}
                    {c.unknowns?.length > 0 && <div className="small muted">Open questions: {c.unknowns.join("; ")}</div>}
                  </div>
                );
              })}
              <p className="small muted">Prompt {ev.prompt_version} · rubric r{ev.rubric_revision} · created {fmt.dateTime(ev.created_at)}. A matching quotation does not prove the interpretation is right - review it.</p>
            </>
          )}
          <h3>Extracted text (plain, untrusted)</h3>
          <div className="cvtext">
            {d.extracted_pages?.length ? d.extracted_pages.map((p: any) => `--- page ${p.page} ---\n` + p.segments.map((s: any) => `[${s.id}] ${s.text}`).join("\n")).join("\n\n") : "No extractable text (possibly scanned) - manual review needed."}
          </div>
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
  const [drawer, setDrawer] = useState<string | null>(null);
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
      await api(`/api/hr/jobs/${id}/analysis-runs`, {
        body: { application_ids: [...selected], rubric_revision: job.rubric.revision, confirm_scope: true },
      });
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
  if (jobError) return <div className="page"><ErrorBox error={jobError} /></div>;
  if (!job) return <div className="page"><Loading /></div>;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <div className="page">
      <JobNav job={job} />
      <RunPanel key={runKey} jobId={job.id} onFinished={onRunFinished} />
      <div className="card">
        <div className="spread">
          <h2>Applications</h2>
          <div className="row">
            <button className="btn btn-small" onClick={() => setSelected(new Set(data?.items.map((a: any) => a.id)))} disabled={!data?.items.length}>Select page</button>
            <button className="btn btn-small" onClick={() => setSelected(new Set(data?.unevaluated_ids))} disabled={!data?.unevaluated_ids.length}>
              Select all not evaluated ({data?.unevaluated_ids.length ?? 0})
            </button>
            <button className="btn btn-small" onClick={() => setSelected(new Set())} disabled={!selected.size}>Clear</button>
            <button className="btn btn-primary" disabled={!selected.size || !job.rubric} title={!job.rubric ? "Approve a rubric first" : !selected.size ? "Select applications first" : undefined} onClick={() => setConfirming(true)}>
              Review & authorize analysis ({selected.size})
            </button>
          </div>
        </div>
        {confirming && (
          <div className="alert alert-info" role="dialog" aria-label="Confirm analysis scope">
            <div>
              <strong>Authorize analysis?</strong> Job “{job.title}”, rubric revision {job.rubric.revision}, {selected.size} selected application(s), AI mode{" "}
              <strong>{status?.ai_mode === "live" ? `LIVE (${status.model_id}) - uses free-tier quota` : "REPLAY (synthetic, not an LLM)"}</strong>.
              <div className="small">This permits storing provisional evaluations and run logs for exactly this scope. It does not shortlist, reject or contact anyone.</div>
            </div>
            <div className="row">
              <button className="btn btn-primary" onClick={authorize} disabled={busy}>{busy ? "Authorizing…" : "Authorize run"}</button>
              <button className="btn" onClick={() => setConfirming(false)}>Cancel</button>
            </div>
          </div>
        )}
        <ErrorBox error={error} />
        <div className="row" style={{ margin: "12px 0" }}>
          <input aria-label="Search name or email" placeholder="Search name or email" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value, page: 1 })} style={{ maxWidth: 240 }} />
          <select aria-label="Document filter" value={filters.parse_status} onChange={(e) => setFilters({ ...filters, parse_status: e.target.value, page: 1 })} style={{ maxWidth: 190 }}>
            <option value="">All documents</option>
            <option value="parsed">Parsed</option>
            <option value="needs_review">Needs manual review</option>
          </select>
          <select aria-label="Contact filter" value={filters.contact_status} onChange={(e) => setFilters({ ...filters, contact_status: e.target.value, page: 1 })} style={{ maxWidth: 190 }}>
            <option value="">All contacts</option>
            <option value="ok">Contact OK</option>
            <option value="review_required">Contact review</option>
          </select>
          <select aria-label="Evaluation filter" value={filters.evaluation} onChange={(e) => setFilters({ ...filters, evaluation: e.target.value, page: 1 })} style={{ maxWidth: 190 }}>
            <option value="">All evaluations</option>
            <option value="none">Not evaluated</option>
            <option value="provisional">Provisional</option>
            <option value="needs_review">Needs review</option>
            <option value="invalid">Invalid output</option>
          </select>
        </div>
        {!data && <Loading />}
        {data && data.items.length === 0 && <Empty title="No applications match" />}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col"><span className="sr-only">Select</span></th>
                  <th scope="col">Candidate</th>
                  <th scope="col">Submitted</th>
                  <th scope="col">Document</th>
                  <th scope="col">Contact</th>
                  <th scope="col">Evaluation</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((a: any) => (
                  <tr key={a.id} className={selected.has(a.id) ? "selected" : ""}>
                    <td><input type="checkbox" aria-label={`Select ${a.candidate_name}`} checked={selected.has(a.id)} onChange={() => toggle(a.id)} /></td>
                    <td><strong>{a.candidate_name}</strong><div className="small muted">{a.account_email}</div></td>
                    <td className="small">{fmt.dateTime(a.submitted_at, status?.timezone)}{a.revision > 1 && <div><Badge tone="info">revision {a.revision}</Badge></div>}</td>
                    <td className="small">
                      <StateBadge state={a.parse_status} /> <a href={`/api/hr/applications/${a.id}/resume`}>PDF</a>
                      <div className="muted">{a.pages} page(s)</div>
                    </td>
                    <td><StateBadge state={a.contact_status} label={a.contact_status === "ok" ? "ok" : "review"} /></td>
                    <td>
                      {a.evaluation ? (
                        <>
                          <StateBadge state={a.evaluation.state} /> <Badge tone={a.evaluation.source === "live" ? "ai" : "neutral"}>{a.evaluation.source}</Badge>
                          {a.evaluation.rubric_revision !== job.rubric?.revision && <Badge tone="warn">stale</Badge>}
                        </>
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
        {data && pages > 1 && (
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn-small" disabled={filters.page <= 1} onClick={() => setFilters({ ...filters, page: filters.page - 1 })}>Previous</button>
            <span className="small">Page {filters.page} of {pages} · {data.total} total</span>
            <button className="btn btn-small" disabled={filters.page >= pages} onClick={() => setFilters({ ...filters, page: filters.page + 1 })}>Next</button>
          </div>
        )}
      </div>
      <EvidenceDrawer appId={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}

export { ScoreBar };
