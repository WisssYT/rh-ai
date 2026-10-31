import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, fmt, newIdempotencyKey } from "../../api";
import { useAuth } from "../../auth";
import { Empty, ErrorBox, Loading, Notice, StateBadge } from "../../components/ui";

const STAGE: Record<string, string> = {
  received: "Received - under review by the HR team",
  invited_to_interview: "Invited to interview",
  interview_confirmed: "Interview confirmed",
  withdrawn: "Withdrawn",
};

export function CandidateDashboard() {
  const { status } = useAuth();
  const [data, setData] = useState<{ apps: any[]; invs: any[]; bookings: any[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    Promise.all([api("/api/candidate/applications"), api("/api/candidate/invitations"), api("/api/candidate/bookings")])
      .then(([a, i, b]) => setData({ apps: a.items, invs: i.items, bookings: b.items }))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  const tz = status?.timezone;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>My applications</h1>
          <p className="muted">Only you can see this page. Recruiters decide; nothing about you is decided automatically.</p>
        </div>
        <Link to="/jobs" className="btn">Browse positions</Link>
      </div>
      <ErrorBox error={error} onRetry={load} />
      {!data && !error && <Loading />}
      {data && (
        <div className="grid grid-2">
          <section className="card">
            <h2>Applications</h2>
            {data.apps.length === 0 && <Empty title="No applications yet"><Link to="/jobs">Find a position</Link></Empty>}
            {data.apps.map((a) => (
              <div key={a.id} className="criterion">
                <div className="spread">
                  <Link to={`/candidate/applications/${a.id}`}><strong>{a.job.title}</strong></Link>
                  <span className="small muted">{fmt.dateTime(a.submitted_at, tz)}</span>
                </div>
                <div className="small">{STAGE[a.stage] ?? a.stage}</div>
                {a.contact_status !== "ok" && <Notice tone="warn">Action needed: {a.contact_reason}. Replace your CV with the corrected contact email.</Notice>}
              </div>
            ))}
          </section>
          <section className="card">
            <h2>Interview invitations</h2>
            {data.invs.length === 0 && <Empty title="No invitations yet" />}
            {data.invs.map((i) => (
              <div key={i.id} className="criterion spread">
                <div>
                  <strong>{i.job_title}</strong>
                  <div className="small muted">Expires {fmt.dateTime(i.expires_at, tz)} ({tz})</div>
                </div>
                {i.expired || i.revoked ? <StateBadge state="expired" label={i.revoked ? "withdrawn" : "expired"} /> : <Link className="btn btn-primary btn-small" to={`/candidate/interviews/${i.id}`}>Choose a time</Link>}
              </div>
            ))}
            <h3>My booking requests</h3>
            {data.bookings.length === 0 && <p className="muted small">None.</p>}
            {data.bookings.map((b) => (
              <div key={b.id} className="row small">
                <StateBadge state={b.status} label={b.status === "requested" ? "awaiting HR confirmation" : b.status} />
                {b.job_title}: {fmt.dateTime(b.slot.starts_at, tz)}
              </div>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}

export function CandidateApplication() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const { status } = useAuth();
  const [app, setApp] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => {
    api(`/api/candidate/applications/${id}`).then(setApp).catch((e) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);

  async function replace(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const f = new FormData();
    f.append("file", file);
    f.append("storage_notice_ack", String(ack));
    setBusy(true);
    setError(null);
    try {
      setApp(await api(`/api/candidate/applications/${id}/resume`, { form: f }));
      setMsg("CV replaced. Any earlier provisional assessment is now outdated and will be redone only if HR authorizes it.");
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  async function withdraw() {
    if (!confirm("Withdraw this application? This cannot be undone in the demo.")) return;
    try {
      await api(`/api/candidate/applications/${id}/withdraw`, { method: "POST" });
      load();
    } catch (err) {
      setError((err as ApiError).message);
    }
  }
  if (!app) return <div className="page">{error ? <ErrorBox error={error} /> : <Loading />}</div>;
  return (
    <div className="page medium">
      <p><Link to="/candidate">← My applications</Link></p>
      {sp.get("submitted") && <Notice tone="good">Application submitted. You can follow its status here.</Notice>}
      {msg && <Notice tone="good">{msg}</Notice>}
      <div className="card">
        <div className="spread">
          <h1>{app.job.title}</h1>
          <StateBadge state={app.status} />
        </div>
        <p>{STAGE[app.stage] ?? app.stage}</p>
        <dl className="small">
          <dt className="muted">Submitted</dt>
          <dd>{fmt.dateTime(app.submitted_at, status?.timezone)} · revision {app.revision}</dd>
          <dt className="muted">Document</dt>
          <dd>
            {app.document.filename} ({Math.round(app.document.size_bytes / 1024)} KB, {app.document.pages} page(s)) ·{" "}
            <a href={`/api/candidate/applications/${app.id}/resume`}>Download</a>
          </dd>
          <dt className="muted">Contact email found in CV</dt>
          <dd>{app.cv_email ?? "none"} <StateBadge state={app.contact_status} label={app.contact_status === "ok" ? "matches account" : "needs correction"} /></dd>
        </dl>
        {app.contact_status !== "ok" && <Notice tone="warn">{app.contact_reason}. Invitations are blocked until this is corrected - upload a CV whose only email is your account email.</Notice>}
        {app.document.parse_status !== "parsed" && <Notice tone="warn">Your document could not be read completely by our text extractor; a recruiter will review it manually.</Notice>}
      </div>
      <div className="card">
        <h2>Text we extracted</h2>
        <p className="small muted">Shown as plain text exactly as extracted. This is what reviewers and the screening assistant see (with contact details redacted for screening).</p>
        <div className="cvtext">
          {app.extracted_pages?.length ? app.extracted_pages.map((p: any) => `--- page ${p.page} ---\n` + p.segments.map((s: any) => s.text).join("\n")).join("\n\n") : "No text could be extracted."}
        </div>
      </div>
      {app.status === "submitted" && (
        <div className="card">
          <h2>Correct or replace your CV</h2>
          <form onSubmit={replace}>
            <div className="field">
              <label htmlFor="newcv">New CV (PDF)</label>
              <input id="newcv" type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </div>
            <label className="check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> <span>Fictional data only; I understand the previous assessment becomes outdated.</span></label>
            <ErrorBox error={error} />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={!file || !ack || busy}>{busy ? "Uploading…" : "Replace CV"}</button>
              <button type="button" className="btn btn-danger" onClick={withdraw}>Withdraw application</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

export function CandidateInterview() {
  const { invitationId } = useParams();
  const { status } = useAuth();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);
  // One idempotency key per selection attempt: a retried/double-clicked submit cannot create a second request.
  const idemKey = useMemo(() => newIdempotencyKey(), [selected]);
  const tz = data?.timezone ?? status?.timezone;

  const load = useCallback(() => {
    setError(null);
    api(`/api/candidate/invitations/${invitationId}/slots`).then(setData).catch((e) => setError(e.message));
  }, [invitationId]);
  useEffect(load, [load]);

  async function request() {
    if (!selected) return;
    setBusy(true);
    setConflict(null);
    try {
      await api(`/api/candidate/invitations/${invitationId}/booking-requests`, { body: { slot_id: selected, idempotency_key: idemKey } });
      setSelected(null);
      load();
    } catch (err) {
      const e = err as ApiError;
      if (e.status === 409) {
        setConflict(e.message);
        const alts = (e.detail as any)?.alternatives;
        if (alts) setData((d: any) => ({ ...d, slots: alts }));
        setSelected(null);
      } else setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function cancel(id: string) {
    try {
      await api(`/api/candidate/bookings/${id}/cancel`, { method: "POST" });
      load();
    } catch (err) {
      setError((err as ApiError).message);
    }
  }

  const byDay = useMemo(() => {
    const m = new Map<string, any[]>();
    for (const s of data?.slots ?? []) {
      const k = fmt.day(s.starts_at, tz);
      m.set(k, [...(m.get(k) ?? []), s]);
    }
    return [...m.entries()];
  }, [data, tz]);

  if (error) return <div className="page medium"><ErrorBox error={error} onRetry={load} /><p><Link to="/candidate">← My applications</Link></p></div>;
  if (!data) return <div className="page"><Loading /></div>;
  const active = data.active_booking;
  return (
    <div className="page medium">
      <p><Link to="/candidate">← My applications</Link></p>
      <div className="card">
        <h1>Interview for {data.invitation.job_title}</h1>
        <p className="muted">All times are shown in <strong>{tz}</strong>. Invitation valid until {fmt.dateTime(data.invitation.expires_at, tz)}.</p>
        {active ? (
          <Notice tone={active.status === "confirmed" ? "good" : "info"}>
            <span>
              {active.status === "confirmed" ? "Confirmed" : "Requested - awaiting HR confirmation"}: <strong>{fmt.dateTime(active.slot.starts_at, tz)}</strong> ({active.slot.location}).
              {active.status === "requested" && <> We hold this time until {fmt.dateTime(active.hold_expires_at, tz)}; if HR has not confirmed by then it is released.</>}
            </span>
            {active.status === "requested" && <button className="btn btn-small" onClick={() => cancel(active.id)}>Cancel request</button>}
          </Notice>
        ) : (
          <>
            <p>Pick one available time and submit a request. The recruiting team confirms it; you receive a confirmation email afterwards.</p>
            {conflict && <Notice tone="warn">{conflict} The list below has been refreshed.</Notice>}
            {byDay.length === 0 && <Empty title="No available times right now">Please check back later or reply to the invitation email.</Empty>}
            <div className="grid grid-3">
              {byDay.map(([day, slots]) => (
                <div key={day}>
                  <h3>{day}</h3>
                  {slots.map((s: any) => (
                    <button key={s.id} className="slot slot-available slot-pick" aria-pressed={selected === s.id} onClick={() => setSelected(s.id)}>
                      {fmt.time(s.starts_at, tz)} - {fmt.time(s.ends_at, tz)}
                      <div className="small muted">{s.location}</div>
                    </button>
                  ))}
                </div>
              ))}
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={!selected || busy} onClick={request} title={!selected ? "Select a time first" : undefined}>
                {busy ? "Sending…" : "Request this time"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
