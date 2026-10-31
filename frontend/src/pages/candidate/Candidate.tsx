import { useCallback, useEffect, useMemo, useState, type DragEvent, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, fmt, newIdempotencyKey } from "../../api";
import { useAuth } from "../../auth";
import { Icon } from "../../components/Icon";
import { Empty, ErrorBox, Loading, Notice } from "../../components/ui";

const STAGES = ["Submitted", "Invited", "Interview confirmed"];
const STAGE_INDEX: Record<string, number> = { received: 0, invited_to_interview: 1, interview_confirmed: 2 };
const STAGE_TEXT: Record<string, string> = {
  received: "With the recruiting team",
  invited_to_interview: "Invited to interview - choose a time",
  interview_confirmed: "Interview confirmed",
  withdrawn: "Withdrawn",
};

function StageTrack({ stage }: { stage: string }) {
  if (stage === "withdrawn") return <p className="muted small">Withdrawn - no further steps.</p>;
  const at = STAGE_INDEX[stage] ?? 0;
  return (
    <div className="stage" aria-label={`Progress: ${STAGES[at]}`}>
      <span className="stage-fill" style={{ transform: `scaleX(${at / 2})` }} aria-hidden />
      <ol>
        {STAGES.map((s, i) => (
          <li key={s} className={i <= at ? "reached" : ""} aria-current={i === at ? "step" : undefined}>
            <span className="pip" />
            {s}
          </li>
        ))}
      </ol>
    </div>
  );
}

export function CandidateDashboard() {
  const { status, user } = useAuth();
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
  const openInvites = data?.invs.filter((i) => !i.expired && !i.revoked) ?? [];
  const bookingFor = (title: string) => data?.bookings.find((b) => b.job_title === title && ["requested", "confirmed"].includes(b.status));

  return (
    <div className="cx-wrap">
      <header className="acct-head">
        <div>
          <p className="overline">Signed in as {user?.email}</p>
          <h1>Your applications</h1>
        </div>
        <Link to="/jobs" className="btn">Browse roles</Link>
      </header>
      <ErrorBox error={error} onRetry={load} />
      {!data && !error && <Loading />}
      {data && openInvites.map((i) => {
        const b = bookingFor(i.job_title);
        return (
          <section key={i.id} className="invite-callout" aria-label={`Invitation for ${i.job_title}`}>
            <div>
              <h2>{b ? (b.status === "confirmed" ? "Your interview is confirmed" : "Time requested - waiting for the recruiter") : `You're invited to interview for ${i.job_title}`}</h2>
              <p>
                {b ? `${fmt.dateTime(b.slot.starts_at, tz)} (${tz})` : `Choose a time before ${fmt.dateTime(i.expires_at, tz)} (${tz}).`}
              </p>
            </div>
            <Link className="btn" to={`/candidate/interviews/${i.id}`}>{b ? "View details" : "Choose a time"}<Icon name="arrow" /></Link>
          </section>
        );
      })}
      {data && data.apps.length === 0 && (
        <div style={{ marginTop: 24 }}>
          <Empty title="You haven't applied yet" icon="doc"><Link to="/jobs">See open roles</Link></Empty>
        </div>
      )}
      {data && data.apps.length > 0 && (
        <ul className="app-list">
          {data.apps.map((a) => (
            <li key={a.id} className="app-item">
              <div>
                <h3><Link to={`/candidate/applications/${a.id}`}>{a.job.title}</Link></h3>
                <div className="when">Submitted {fmt.dateTime(a.submitted_at, tz)}{a.revision > 1 && ` · CV replaced (version ${a.revision})`}</div>
                <p className="small" style={{ margin: "8px 0 0" }}>{STAGE_TEXT[a.stage] ?? a.stage}</p>
                {a.contact_status !== "ok" && (
                  <p className="small" style={{ color: "var(--warn)", margin: "6px 0 0" }}>
                    Action needed: {a.contact_reason}. <Link to={`/candidate/applications/${a.id}`}>Replace your CV</Link>
                  </p>
                )}
              </div>
              <StageTrack stage={a.stage} />
            </li>
          ))}
        </ul>
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
  const [drag, setDrag] = useState(false);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(sp.get("submitted") ? "Application submitted. You can follow it here." : null);
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
      setFile(null);
      setAck(false);
      setMsg("CV replaced. The recruiting team will review the new version.");
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  async function withdraw() {
    if (!confirm("Withdraw this application? This can't be undone.")) return;
    try {
      await api(`/api/candidate/applications/${id}/withdraw`, { method: "POST" });
      load();
    } catch (err) {
      setError((err as ApiError).message);
    }
  }
  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setFile(f);
  }

  if (!app) return <div className="cx-wrap" style={{ paddingTop: 40 }}>{error ? <ErrorBox error={error} /> : <Loading />}</div>;
  const d = app.document;
  return (
    <div className="cx-wrap">
      <header className="acct-head">
        <div>
          <Link className="back" to="/candidate"><Icon name="back" />Your applications</Link>
          <h1 style={{ marginTop: 16 }}>{app.job.title}</h1>
          <p className="muted" style={{ margin: "8px 0 0" }}>{STAGE_TEXT[app.stage] ?? app.stage}</p>
        </div>
        <div style={{ minWidth: 280, flex: "0 1 380px" }}><StageTrack stage={app.stage} /></div>
      </header>
      {msg && <Notice tone="good"><span>{msg}</span></Notice>}
      {app.contact_status !== "ok" && (
        <Notice tone="warn">
          <span><strong>Contact email needs correcting.</strong> {app.contact_reason}. Invitations can't be sent until your CV lists exactly one address: {app.cv_email ? <span className="mono">{app.cv_email}</span> : "your account email"}.</span>
        </Notice>
      )}
      {d.parse_status !== "parsed" && <Notice tone="warn"><span>Our text extractor couldn't read your document completely. A recruiter will look at the original file instead.</span></Notice>}
      <div className="split">
        <section aria-labelledby="text-title">
          <div className="spread" style={{ marginBottom: 12 }}>
            <h2 id="text-title" style={{ fontSize: "1.3rem" }}>What we read from your CV</h2>
            <a className="btn btn-small" href={`/api/candidate/applications/${app.id}/resume`}><Icon name="doc" />Original PDF</a>
          </div>
          <div className="sheet" tabIndex={0} aria-label="Extracted CV text">
            {app.extracted_pages?.length ? (
              app.extracted_pages.map((p: any) => (
                <div key={p.page}>
                  <div className="page-mark">PAGE {p.page}</div>
                  {p.segments.map((s: any) => <p key={s.id}>{s.text}</p>)}
                </div>
              ))
            ) : (
              <p className="muted">No text could be extracted - possibly a scanned document.</p>
            )}
          </div>
          <p className="hint" style={{ marginTop: 8 }}>For screening, contact details and personal attributes are hidden from the assistant.</p>
        </section>
        <aside>
          <div className="side-block">
            <h3>Details</h3>
            <dl className="kv">
              <dt>Submitted</dt><dd>{fmt.dateTime(app.submitted_at, status?.timezone)}</dd>
              <dt>Version</dt><dd>{app.revision}</dd>
              <dt>File</dt><dd style={{ wordBreak: "break-all" }}>{d.filename} <span className="mono muted">{Math.round(d.size_bytes / 1024)} KB · {d.pages}p</span></dd>
              <dt>CV email</dt><dd className="row" style={{ gap: 6 }}>{app.cv_email ?? <span className="muted">none found</span>}{app.contact_status === "ok" && <span className="row" style={{ gap: 4, color: "var(--green)" }}><Icon name="check" className="icon" label="matches your account" /><span className="small">matches account</span></span>}</dd>
            </dl>
          </div>
          {app.status === "submitted" && (
            <div className="side-block">
              <h3>Replace your CV</h3>
              <form onSubmit={replace}>
                <div className={`dropzone${drag ? " drag" : ""}`} onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}>
                  <Icon name="upload" />
                  <strong>{file ? file.name : "Drop a new PDF, or choose a file"}</strong>
                  <input type="file" accept="application/pdf,.pdf" aria-label="New CV (PDF)" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                </div>
                <label className="check" style={{ marginTop: 12 }}>
                  <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  <span>Fictional data only. Any earlier review notes no longer apply to the new version.</span>
                </label>
                <ErrorBox error={error} />
                <button className="btn btn-primary" style={{ marginTop: 12 }} disabled={!file || !ack || busy}>{busy ? "Uploading…" : "Upload new version"}</button>
              </form>
            </div>
          )}
          {app.status === "submitted" && (
            <div className="side-block">
              <h3>Withdraw</h3>
              <p className="small muted">Stops the process for this role. Your other applications are not affected.</p>
              <button type="button" className="btn btn-danger btn-small" onClick={withdraw}>Withdraw application</button>
            </div>
          )}
        </aside>
      </div>
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
  // One idempotency key per selection: a retried or double-clicked request cannot create a second booking.
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
  const chosen = data?.slots?.find((s: any) => s.id === selected);

  if (error)
    return (
      <div className="cx-wrap" style={{ paddingTop: 40 }}>
        <ErrorBox error={error} onRetry={load} />
        <Link className="back" to="/candidate"><Icon name="back" />Your applications</Link>
      </div>
    );
  if (!data) return <div className="cx-wrap" style={{ paddingTop: 40 }}><Loading /></div>;
  const active = data.active_booking;
  return (
    <div className="cx-wrap">
      <header className="acct-head">
        <div>
          <Link className="back" to="/candidate"><Icon name="back" />Your applications</Link>
          <p className="overline" style={{ marginTop: 18 }}>Interview · {data.invitation.job_title}</p>
          <h1>{active ? (active.status === "confirmed" ? "You're booked." : "Request sent.") : "Choose a time that suits you."}</h1>
        </div>
        <p className="mono muted small" style={{ margin: 0 }}>
          Times in {tz}
          <br />
          Invitation open until {fmt.dateTime(data.invitation.expires_at, tz)}
        </p>
      </header>

      {active ? (
        <section className={`status-card${active.status === "requested" ? " pending" : ""}`} aria-live="polite">
          <p className="overline" style={{ margin: 0 }}>{active.status === "confirmed" ? "Confirmed by the recruiter" : "Requested - awaiting HR confirmation"}</p>
          <div className="when">{fmt.dateTime(active.slot.starts_at, tz)} - {fmt.time(active.slot.ends_at, tz)}</div>
          <p className="small" style={{ margin: 0 }}>{active.slot.location}</p>
          {active.status === "requested" && (
            <>
              <p className="small muted">We hold this time for you until {fmt.dateTime(active.hold_expires_at, tz)}. If the recruiter hasn't confirmed by then, it's released and you can choose again.</p>
              <button className="btn btn-small" onClick={() => cancel(active.id)}>Cancel request</button>
            </>
          )}
          {active.status === "confirmed" && <p className="small muted">A confirmation email will follow once the recruiter sends it.</p>}
        </section>
      ) : (
        <>
          {conflict && <Notice tone="warn"><span>{conflict} The times below are up to date.</span></Notice>}
          {byDay.length === 0 && <div style={{ marginTop: 24 }}><Empty title="No free times at the moment" icon="calendar">New times may be published soon - check back, or reply to your invitation email.</Empty></div>}
          <div className="days" role="group" aria-label="Available interview times">
            {byDay.map(([day, slots]) => (
              <div key={day} className="day-col">
                <h3>{day}</h3>
                {slots.map((s: any) => (
                  <button key={s.id} className="slot-btn" aria-pressed={selected === s.id} onClick={() => setSelected(selected === s.id ? null : s.id)}>
                    <span>{fmt.time(s.starts_at, tz)}</span>
                    <small>{Math.round((new Date(s.ends_at).getTime() - new Date(s.starts_at).getTime()) / 60000)} min</small>
                  </button>
                ))}
              </div>
            ))}
          </div>
          {chosen && (
            <div className="selection-bar" role="region" aria-label="Selected time">
              <div>
                <strong>{fmt.day(chosen.starts_at, tz)}, {fmt.time(chosen.starts_at, tz)} - {fmt.time(chosen.ends_at, tz)}</strong>
                <div className="small muted">{chosen.location}</div>
              </div>
              <button className="btn btn-primary" disabled={busy} onClick={request}>{busy ? "Sending…" : "Request this time"}</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function CandidateProfile() {
  const { user, refresh } = useAuth();
  const [name, setName] = useState(user?.full_name ?? "");
  const [nameMsg, setNameMsg] = useState<string | null>(null);
  const [nameErr, setNameErr] = useState<string | null>(null);
  const [pw, setPw] = useState({ current_password: "", new_password: "", confirm: "" });
  const [pwMsg, setPwMsg] = useState<string | null>(null);
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function saveName(e: FormEvent) {
    e.preventDefault();
    setNameErr(null);
    setNameMsg(null);
    try {
      await api("/api/candidate/profile", { method: "PATCH", body: { full_name: name } });
      await refresh();
      setNameMsg("Name updated.");
    } catch (err) {
      setNameErr((err as ApiError).message);
    }
  }
  async function savePw(e: FormEvent) {
    e.preventDefault();
    setPwErr(null);
    setPwMsg(null);
    if (pw.new_password !== pw.confirm) return setPwErr("The new passwords don't match.");
    setBusy(true);
    try {
      await api("/api/candidate/profile/password", { body: { current_password: pw.current_password, new_password: pw.new_password } });
      setPw({ current_password: "", new_password: "", confirm: "" });
      setPwMsg("Password changed. Other devices have been signed out.");
    } catch (err) {
      setPwErr((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="cx-wrap" style={{ maxWidth: 760 }}>
      <header className="acct-head">
        <div>
          <p className="overline">Account</p>
          <h1>Profile</h1>
        </div>
      </header>
      <section className="side-block" aria-labelledby="p-name" style={{ marginTop: 24 }}>
        <h2 id="p-name" style={{ fontSize: "1.25rem" }}>Your details</h2>
        <form onSubmit={saveName} style={{ marginTop: 14 }}>
          <div className="field">
            <label htmlFor="pname">Full name</label>
            <input id="pname" value={name} onChange={(e) => setName(e.target.value)} minLength={2} required autoComplete="name" />
          </div>
          <div className="field">
            <label htmlFor="pemail">Email</label>
            <input id="pemail" value={user?.email ?? ""} readOnly aria-describedby="pemail-hint" />
            <span className="hint" id="pemail-hint">Your email identifies you for invitations and can't be changed here. It should match the address in your CV.</span>
          </div>
          {nameMsg && <Notice tone="good"><span>{nameMsg}</span></Notice>}
          <ErrorBox error={nameErr} />
          <button className="btn btn-primary" disabled={!name.trim() || name.trim() === user?.full_name}>Save name</button>
        </form>
      </section>
      <section className="side-block" aria-labelledby="p-pw">
        <h2 id="p-pw" style={{ fontSize: "1.25rem" }}>Password</h2>
        <form onSubmit={savePw} style={{ marginTop: 14 }}>
          <div className="field">
            <label htmlFor="cur">Current password</label>
            <input id="cur" type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required />
          </div>
          <div className="field">
            <label htmlFor="np">New password</label>
            <input id="np" type="password" autoComplete="new-password" minLength={10} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required />
            <span className="hint">At least 10 characters.</span>
          </div>
          <div className="field">
            <label htmlFor="np2">Repeat new password</label>
            <input id="np2" type="password" autoComplete="new-password" minLength={10} value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} required />
          </div>
          {pwMsg && <Notice tone="good"><span>{pwMsg}</span></Notice>}
          <ErrorBox error={pwErr} />
          <button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Change password"}</button>
        </form>
      </section>
    </div>
  );
}
