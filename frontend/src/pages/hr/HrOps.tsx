import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, fmt } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Empty, ErrorBox, Loading, Notice, StateBadge } from "../../components/ui";
import { Icon } from "../../components/Icon";
import { JobNav, useJob } from "./HrJobs";

// ---- Job & rubric editor -------------------------------------------------------------

const EMPTY_CRITERION = {
  id: "new_criterion", label: "New criterion", description: "Describe the job-related evidence you look for.", required: false, weight: 10,
  anchors: { "0": "No evidence of this", "1": "Listed as a skill only", "2": "Used in projects or study", "3": "Professional use", "4": "Professional use with clear scope or impact" },
  evidence_signals: [] as string[],
};

export function RubricPage() {
  const { id } = useParams();
  const { job, error: jobError, setJob } = useJob(id);
  const [form, setForm] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (job) setForm({ title: job.title, location: job.location, employment_type: job.employment_type, summary: job.summary, description: job.description, criteria_draft: job.criteria_draft });
  }, [job]);
  const dirty = useMemo(() => job && form && JSON.stringify({ ...form }) !== JSON.stringify({ title: job.title, location: job.location, employment_type: job.employment_type, summary: job.summary, description: job.description, criteria_draft: job.criteria_draft }), [job, form]);

  async function run(fn: () => Promise<any>, ok: string) {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      setJob(await fn());
      setMsg(ok);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  const setCrit = (i: number, patch: any) => setForm({ ...form, criteria_draft: form.criteria_draft.map((c: any, j: number) => (j === i ? { ...c, ...patch } : c)) });

  if (jobError) return <div className="page"><ErrorBox error={jobError} /></div>;
  if (!job || !form) return <div className="page"><Loading /></div>;
  const totalW = form.criteria_draft.reduce((s: number, c: any) => s + Number(c.weight || 0), 0);
  return (
    <div className="page">
      <JobNav job={job} />
      {msg && <Notice tone="good">{msg}</Notice>}
      <ErrorBox error={error} />
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void run(() => api(`/api/hr/jobs/${job.id}`, { method: "PUT", body: form }), "Saved. Approve the rubric to make changes effective for analysis.");
        }}
      >
        <div className="card">
          <h2>Job details</h2>
          <div className="grid grid-2">
            <div className="field"><label htmlFor="t">Title</label><input id="t" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
            <div className="field"><label htmlFor="l">Location</label><input id="l" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></div>
          </div>
          <div className="field"><label htmlFor="s">Summary</label><input id="s" value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} /></div>
          <div className="field"><label htmlFor="d">Description</label><textarea id="d" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
        </div>
        <div className="card">
          <div className="spread">
            <h2>Rubric (draft) {job.rubric_draft_pending ? <Badge tone="warn">differs from approved r{job.rubric?.revision ?? "-"}</Badge> : <Badge tone="good">matches approved r{job.rubric?.revision}</Badge>}</h2>
            <button type="button" className="btn btn-small" onClick={() => setForm({ ...form, criteria_draft: [...form.criteria_draft, { ...EMPTY_CRITERION, id: `criterion_${form.criteria_draft.length + 1}` }] })}>Add criterion</button>
          </div>
          <p className="small muted">Job-related criteria only, with explicit 0-4 anchors. Weights total {totalW} → normalized to 100. Changing a description or anchor creates a new rubric revision and makes existing evaluations stale; weight-only changes do not.</p>
          {form.criteria_draft.map((c: any, i: number) => (
            <div key={i} className="criterion">
              <div className="grid grid-3">
                <div className="field"><label htmlFor={`cid${i}`}>Criterion ID</label><input id={`cid${i}`} className="mono" value={c.id} onChange={(e) => setCrit(i, { id: e.target.value })} pattern="^[a-z][a-z0-9_]{1,40}$" /></div>
                <div className="field"><label htmlFor={`cl${i}`}>Label</label><input id={`cl${i}`} value={c.label} onChange={(e) => setCrit(i, { label: e.target.value })} /></div>
                <div className="field"><label htmlFor={`cw${i}`}>Weight</label><input id={`cw${i}`} type="number" min={0} max={100} value={c.weight} onChange={(e) => setCrit(i, { weight: Number(e.target.value) })} /></div>
              </div>
              <div className="field"><label htmlFor={`cd${i}`}>Description</label><input id={`cd${i}`} value={c.description} onChange={(e) => setCrit(i, { description: e.target.value })} /></div>
              <div className="grid grid-3">
                {(["0", "1", "2", "3", "4"] as const).map((k) => (
                  <div key={k} className="field"><label htmlFor={`a${i}${k}`}>Anchor {k}</label><input id={`a${i}${k}`} value={c.anchors[k]} onChange={(e) => setCrit(i, { anchors: { ...c.anchors, [k]: e.target.value } })} /></div>
                ))}
                <div className="field"><label htmlFor={`sg${i}`}>Evidence signals (replay keywords)</label><input id={`sg${i}`} value={(c.evidence_signals ?? []).join(", ")} onChange={(e) => setCrit(i, { evidence_signals: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></div>
              </div>
              <div className="spread">
                <label className="check"><input type="checkbox" checked={c.required} onChange={(e) => setCrit(i, { required: e.target.checked })} /> Required (unknown stays visible for review; never an automatic rejection)</label>
                <button type="button" className="btn btn-small btn-danger" onClick={() => setForm({ ...form, criteria_draft: form.criteria_draft.filter((_: any, j: number) => j !== i) })}>Remove</button>
              </div>
            </div>
          ))}
          <div className="row">
            <button className="btn" disabled={!dirty || busy}>Save draft</button>
            <button
              type="button"
              className="btn btn-good"
              disabled={dirty || busy || !form.criteria_draft.length}
              title={dirty ? "Save the draft first" : undefined}
              onClick={() => run(() => api(`/api/hr/jobs/${job.id}/rubric/approve`, { body: { criteria_draft_digest: job.criteria_draft_digest } }), "Rubric approved.")}
            >
              Approve rubric & weights
            </button>
            {job.status !== "published" ? (
              <button type="button" className="btn btn-primary" disabled={!job.rubric || busy} title={!job.rubric ? "Approve a rubric first" : undefined} onClick={() => run(() => api(`/api/hr/jobs/${job.id}/publish`, { method: "POST" }), "Published on the careers site.")}>Publish job</button>
            ) : (
              <button type="button" className="btn" disabled={busy} onClick={() => run(() => api(`/api/hr/jobs/${job.id}/close`, { method: "POST" }), "Closed for new applications.")}>Close job</button>
            )}
          </div>
        </div>
      </form>
      <SettingsCard job={job} onSaved={setJob} />
    </div>
  );
}

function SettingsCard({ job, onSaved }: { job: any; onSaved: (j: any) => void }) {
  const [size, setSize] = useState(job.shortlist_size);
  const [min, setMin] = useState(job.min_suggest_score);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="card">
      <h2>Shortlist settings</h2>
      <div className="row">
        <div className="field"><label htmlFor="ss">Shortlist size (proposal)</label><input id="ss" type="number" min={1} max={200} value={size} onChange={(e) => setSize(Number(e.target.value))} /></div>
        <div className="field"><label htmlFor="ms">Minimum evidence score to be proposed</label><input id="ms" type="number" min={0} max={100} value={min} onChange={(e) => setMin(Number(e.target.value))} /></div>
        <button className="btn" onClick={() => api(`/api/hr/jobs/${job.id}/settings`, { method: "PATCH", body: { shortlist_size: size, min_suggest_score: min } }).then(onSaved).catch((e) => setError(e.message))}>Save</button>
      </div>
      <p className="small muted">The proposal never fills up with unsuitable applicants to reach the size. You may still select anyone with a recorded reason.</p>
      <ErrorBox error={error} />
    </div>
  );
}

// ---- Calendar ------------------------------------------------------------------------

/** Rolling 7-day window starting at the given day (local midnight). */
function startOfDay(d: Date) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

/** Converts a wall-clock date+time in the company timezone to a UTC ISO string. */
function zonedToIso(date: string, time: string, tz: string): string {
  const guess = new Date(`${date}T${time}:00Z`);
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(guess);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"));
  return new Date(guess.getTime() - (asUtc - guess.getTime())).toISOString();
}

export function CalendarPage() {
  const { status, user } = useAuth();
  const tz = status?.timezone ?? "UTC";
  const [week, setWeek] = useState(() => startOfDay(new Date()));
  const [jobs, setJobs] = useState<any[]>([]);
  const [jobId, setJobId] = useState("");
  const [items, setItems] = useState<any[] | null>(null);
  const [bookings, setBookings] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [interviewers, setInterviewers] = useState<any[]>([]);
  const [f, setF] = useState({ date: "", start: "10:00", minutes: 45, count: 1, location: "Video call (link sent in confirmation)", interviewer: "" });

  useEffect(() => {
    api("/api/hr/jobs").then((r) => {
      setJobs(r.items);
      if (r.items[0]) setJobId(r.items[0].id);
    });
  }, []);
  useEffect(() => {
    if (jobId) api(`/api/hr/interviewers?job_id=${jobId}`).then((r) => setInterviewers(r.items)).catch(() => setInterviewers([]));
  }, [jobId]);
  const load = useCallback(() => {
    const end = new Date(week);
    end.setDate(end.getDate() + 7);
    Promise.all([
      api(`/api/hr/calendar?start=${encodeURIComponent(week.toISOString())}&end=${encodeURIComponent(end.toISOString())}${jobId ? `&job_id=${jobId}` : ""}`),
      api("/api/hr/booking-requests?status=requested"),
    ])
      .then(([c, b]) => {
        setItems(c.items);
        setBookings(b.items);
      })
      .catch((e) => setError(e.message));
  }, [week, jobId]);
  useEffect(load, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMsg(null);
    const slots = [];
    let t = zonedToIso(f.date, f.start, tz);
    for (let i = 0; i < f.count; i++) {
      const st = new Date(t);
      const en = new Date(st.getTime() + f.minutes * 60000);
      slots.push({ starts_at: st.toISOString(), ends_at: en.toISOString(), location: f.location });
      t = new Date(en.getTime() + 15 * 60000).toISOString();
    }
    try {
      await api("/api/hr/slots", { body: { job_id: jobId, interviewer_id: f.interviewer || null, slots } });
      setMsg(`${slots.length} slot(s) published for this job.`);
      load();
    } catch (err) {
      setError((err as ApiError).message);
    }
  }
  async function act(path: string, method = "POST", body: any = {}) {
    setError(null);
    try {
      await api(path, { method, body: method === "DELETE" ? undefined : body });
      load();
    } catch (err) {
      setError((err as ApiError).message);
    }
  }
  const days = [...Array(7)].map((_, i) => {
    const d = new Date(week);
    d.setDate(d.getDate() + i);
    return d;
  });
  const multipleInterviewers = new Set((items ?? []).map((s) => s.interviewer.id)).size > 1;
  const dayKey = (iso: string | Date) => new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date(iso));
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Interview calendar</h1>
          <p className="muted">Times in <strong>{tz}</strong> (company timezone). Each slot holds one interview.</p>
        </div>
        <div className="row">
          <label htmlFor="cj" className="small">Job</label>
          <select id="cj" value={jobId} onChange={(e) => setJobId(e.target.value)} style={{ width: 240 }}>
            {jobs.map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}
          </select>
          <button className="btn btn-small" onClick={() => setWeek(new Date(week.getTime() - 7 * 864e5))} aria-label="Previous week"><Icon name="back" /></button>
          <span className="small">{fmt.day(week.toISOString(), tz)} – {fmt.day(days[6].toISOString(), tz)}</span>
          <button className="btn btn-small" onClick={() => setWeek(new Date(week.getTime() + 7 * 864e5))} aria-label="Next week"><Icon name="arrow" /></button>
          <button className="btn btn-small" onClick={() => setWeek(startOfDay(new Date()))}>Today</button>
        </div>
      </div>
      {msg && <Notice tone="good">{msg}</Notice>}
      <ErrorBox error={error} />
      {bookings.length > 0 && (
        <div className="card">
          <h2>Pending requests ({bookings.length})</h2>
          {bookings.map((b) => (
            <div key={b.id} className="spread criterion">
              <div>
                <strong>{b.candidate_name}</strong> · {b.job.title} · {fmt.dateTime(b.slot.starts_at, tz)}
                <div className="small muted">{b.hold_expired ? "Hold expired - cannot be confirmed" : `Held until ${fmt.dateTime(b.hold_expires_at, tz)}`}</div>
              </div>
              <div className="row">
                <button className="btn btn-good btn-small" disabled={b.hold_expired} onClick={() => act(`/api/hr/booking-requests/${b.id}/confirm`)}>Confirm interview</button>
                <button className="btn btn-small" onClick={() => act(`/api/hr/booking-requests/${b.id}/decline`)}>Decline</button>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="card">
        <h2>Publish availability</h2>
        <form className="row" onSubmit={create} style={{ alignItems: "flex-end" }}>
          <div className="field"><label htmlFor="sd">Date</label><input id="sd" type="date" required value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></div>
          <div className="field"><label htmlFor="st">Start ({tz})</label><input id="st" type="time" required value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></div>
          <div className="field"><label htmlFor="sm">Minutes</label><input id="sm" type="number" min={15} max={240} value={f.minutes} onChange={(e) => setF({ ...f, minutes: Number(e.target.value) })} style={{ width: 90 }} /></div>
          <div className="field"><label htmlFor="sc">Consecutive slots</label><input id="sc" type="number" min={1} max={12} value={f.count} onChange={(e) => setF({ ...f, count: Number(e.target.value) })} style={{ width: 90 }} /></div>
          <div className="field"><label htmlFor="sl">Location / method</label><input id="sl" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></div>
          {user?.role === "supervisor" && (
            <div className="field"><label htmlFor="si">Interviewer</label>
              <select id="si" value={f.interviewer} onChange={(e) => setF({ ...f, interviewer: e.target.value })}>
                <option value="">Me</option>
                {interviewers.filter((i) => i.id !== user.id).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
              </select>
            </div>
          )}
          <button className="btn btn-primary" disabled={!jobId} style={{ marginBottom: 12 }}>Publish slots</button>
        </form>
        <p className="small muted">Past, zero-length and overlapping slots for the same interviewer are rejected by the server. 15 minutes are left between consecutive slots.</p>
      </div>
      {!items && <Loading />}
      {items && (
        <div className="week" role="grid" aria-label="Week view">
          {days.map((d) => {
            const k = dayKey(d);
            const list = items.filter((s) => dayKey(s.starts_at) === k);
            return (
              <div key={k} className="day" role="gridcell">
                <h3>{fmt.day(d.toISOString(), tz)}</h3>
                {list.length === 0 && <div className="small muted">No slots</div>}
                {list.map((s) => (
                  <div key={s.id} className={`slot slot-${s.status}`}>
                    <div className="spread" style={{ gap: 4 }}>
                      <strong className="mono">{fmt.time(s.starts_at, tz)}–{fmt.time(s.ends_at, tz)}</strong>
                      {s.status === "available" && <button className="slot-x" aria-label={`Remove ${fmt.time(s.starts_at, tz)} slot`} title="Remove slot" onClick={() => act(`/api/hr/slots/${s.id}`, "DELETE")}>×</button>}
                    </div>
                    <div>{s.booking ? <>{s.booking.candidate_name} <span className="muted">· {s.status === "held" ? "requested" : "confirmed"}</span></> : <span className="muted">free</span>}</div>
                    {multipleInterviewers && <div className="muted">{s.interviewer.name}</div>}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---- Approvals -----------------------------------------------------------------------

const KIND_LABEL: Record<string, string> = { invitation: "Invitation", confirmation: "Confirmation", reminder: "Reminder", reply: "Reply", decline: "Decline letter" };

export function DraftCard({ d, tz, onChange, sources }: { d: any; tz: string; onChange: () => void; sources?: string[] }) {
  const [edit, setEdit] = useState(false);
  const [subject, setSubject] = useState(d.preview.subject);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function call(path: string, b?: any, method = "POST") {
    setBusy(true);
    setError(null);
    try {
      await api(path, { method, body: b });
      setEdit(false);
      onChange();
    } catch (e) {
      setError((e as ApiError).message);
      onChange();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card">
      <div className="spread">
        <h2>
          {KIND_LABEL[d.kind] ?? d.kind} · {d.candidate.name} <StateBadge state={d.status} />
        </h2>
        <span className="small muted">
          {d.job.title} · revision {d.revision} · <Badge tone={d.generator.startsWith("ai_live") ? "ai" : "neutral"}>{d.generator === "ai_live" ? "AI draft (live LLM)" : d.generator === "ai_replay" ? "replay draft (synthetic)" : d.generator === "edited" ? "edited by human" : "template"}</Badge>
        </span>
      </div>
      {d.blocking_problem && <Notice tone="warn">Cannot be approved: {d.blocking_problem}</Notice>}
      {sources && sources.length > 0 && (
        <div className="chips" aria-label="Facts the draft was allowed to use">
          <span className="small muted">Grounded only in:</span>
          {sources.map((x) => <span key={x} className="chip">{x}</span>)}
        </div>
      )}
      <div className="email-preview">
        <dl>
          <dt>From</dt><dd>{d.preview.from}</dd>
          <dt>To</dt><dd><strong>{d.preview.to}</strong> <span className="small muted">(from the candidate's CV, verified against the account)</span></dd>
          <dt>Subject</dt><dd>{d.preview.subject}</dd>
          {d.preview.link_url && (<><dt>Booking link</dt><dd className="mono">{d.preview.link_url}</dd></>)}
        </dl>
        {!edit && <pre>{d.preview.body}</pre>}
        {edit && (
          <div style={{ padding: 12 }}>
            <div className="field"><label htmlFor={`sub${d.id}`}>Subject</label><input id={`sub${d.id}`} value={subject} onChange={(e) => setSubject(e.target.value)} /></div>
            <div className="field"><label htmlFor={`body${d.id}`}>Message ({d.preview.link_url ? "the booking link, expiry and footer are" : "the footer is"} appended automatically)</label><textarea id={`body${d.id}`} value={body} onChange={(e) => setBody(e.target.value)} /></div>
          </div>
        )}
      </div>
      <ErrorBox error={error} />
      {d.outbox && <p className="small muted">Outbox: {d.outbox.status} · {d.outbox.transport_result} {d.outbox.sent_at && `· ${fmt.dateTime(d.outbox.sent_at, tz)}`}</p>}
      {d.approved_by && <p className="small muted">Approved by {d.approved_by} at {fmt.dateTime(d.approved_at, tz)}</p>}
      <div className="row" style={{ marginTop: 8 }}>
        {d.status === "draft" && !edit && (
          <>
            <button className="btn btn-good" disabled={busy || !!d.blocking_problem} onClick={() => call(`/api/hr/email-drafts/${d.id}/approve-send`, { revision: d.revision, digest: d.digest })}>
              Approve & send this exact message
            </button>
            <button className="btn" onClick={() => { setSubject(d.preview.subject); setBody(d.editable_body); setEdit(true); }}>Edit</button>
            <button className="btn btn-danger" disabled={busy} onClick={() => call(`/api/hr/email-drafts/${d.id}/reject`)}>Reject (do not send)</button>
          </>
        )}
        {edit && (
          <>
            <button className="btn btn-primary" disabled={busy} onClick={() => call(`/api/hr/email-drafts/${d.id}`, { subject, body, revision: d.revision }, "PUT")}>Save edit (new revision, needs approval)</button>
            <button className="btn" onClick={() => setEdit(false)}>Cancel</button>
          </>
        )}
        {d.status === "failed" && d.approved_by && <button className="btn" onClick={() => call(`/api/hr/email-drafts/${d.id}/retry`)}>Retry same approved message</button>}
        {d.status === "delivery_unknown" && <span className="small">Delivery unknown - check Mailpit before deciding to resend.</span>}
      </div>
    </div>
  );
}

export function ApprovalsPage() {
  const { status } = useAuth();
  const tz = status?.timezone ?? "UTC";
  const [data, setData] = useState<any>(null);
  const [sent, setSent] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"pending" | "history">("pending");
  const load = useCallback(() => {
    Promise.all([api("/api/hr/approvals"), api("/api/hr/email-drafts")])
      .then(([a, all]) => {
        setData(a);
        setSent(all.items.filter((d: any) => !["draft"].includes(d.status)));
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    const t = window.setInterval(load, 4000); // reflect worker dispatch status
    return () => window.clearInterval(t);
  }, [load]);
  async function prepareConfirmation(interviewId: string) {
    try {
      await api(`/api/hr/interviews/${interviewId}/confirmation-draft`, { method: "POST" });
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  if (!data) return <div className="page">{error ? <ErrorBox error={error} onRetry={load} /> : <Loading />}</div>;
  const drafts = data.email_drafts.filter((d: any) => d.status === "draft" || d.status === "failed" || d.status === "delivery_unknown");
  return (
    <div className="page medium">
      <div className="page-head">
        <div>
          <h1>Approvals</h1>
          <p className="muted">Nothing is sent until you approve the exact recipient and message shown. Editing creates a new revision that needs approval again.</p>
        </div>
        {data.mailpit_url && <a className="btn" href={data.mailpit_url} target="_blank" rel="noreferrer">Open local inbox (Mailpit)</a>}
      </div>
      <ErrorBox error={error} />
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "pending"} onClick={() => setTab("pending")}>Pending ({drafts.length + data.booking_requests.length + data.shortlist_drafts.length})</button>
        <button role="tab" aria-selected={tab === "history"} onClick={() => setTab("history")}>Sent & queued ({sent.length})</button>
      </div>
      {tab === "pending" && (
        <>
          {data.shortlist_drafts.map((s: any) => (
            <Notice key={s.id} tone="info">
              <span>Shortlist draft r{s.revision} for {s.job_title} ({s.members}) awaits approval.</span>
              <Link className="btn btn-small" to={`/hr/jobs/${s.job_id}/shortlist`}>Review</Link>
            </Notice>
          ))}
          {data.booking_requests.map((b: any) => (
            <Notice key={b.id} tone="info">
              <span>{b.candidate_name} requested {fmt.dateTime(b.slot.starts_at, tz)} ({b.job.title}).</span>
              <Link className="btn btn-small" to="/hr/calendar">Decide in calendar</Link>
            </Notice>
          ))}
          {drafts.length === 0 && data.booking_requests.length === 0 && data.shortlist_drafts.length === 0 && <Empty title="Nothing waiting for you" />}
          {drafts.map((d: any) => <DraftCard key={`${d.id}-${d.revision}-${d.status}`} d={d} tz={tz} onChange={load} />)}
          <ConfirmedNeedingEmail onPrepare={prepareConfirmation} tz={tz} />
        </>
      )}
      {tab === "history" && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Kind</th><th>Candidate</th><th>Recipient</th><th>Status</th><th>Approved by</th></tr></thead>
            <tbody>
              {sent.map((d) => (
                <tr key={d.id}>
                  <td>{d.kind}</td><td>{d.candidate.name}</td><td className="mono">{d.preview.to}</td>
                  <td><StateBadge state={d.status} /> {d.outbox && <span className="small muted">{d.outbox.transport_result}</span>}</td>
                  <td className="small">{d.approved_by ?? "-"} {d.approved_at && fmt.dateTime(d.approved_at, tz)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ConfirmedNeedingEmail({ onPrepare, tz }: { onPrepare: (id: string) => void; tz: string }) {
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => {
    api("/api/hr/booking-requests?status=confirmed").then((r) => setItems(r.items.filter((b: any) => !b.confirmation_draft)));
  }, []);
  if (!items.length) return null;
  return (
    <div className="card">
      <h2>Confirmed interviews without a confirmation email</h2>
      {items.map((b) => (
        <div key={b.id} className="spread criterion">
          <span>{b.candidate_name} · {fmt.dateTime(b.slot.starts_at, tz)}</span>
          <button className="btn btn-small" onClick={() => onPrepare(b.interview_id)}>Prepare confirmation draft</button>
        </div>
      ))}
    </div>
  );
}
