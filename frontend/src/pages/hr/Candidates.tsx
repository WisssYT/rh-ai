import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, fmt } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Drawer, Empty, ErrorBox, Notice, SkeletonRows, StateBadge } from "../../components/ui";

export const STAGE_TONE: Record<string, "neutral" | "good" | "warn" | "bad" | "info"> = {
  applied: "neutral", evaluated: "info", shortlisted: "info", invited: "warn", booking_requested: "warn",
  interview_scheduled: "good", interviewed: "good", withdrawn: "neutral", declined: "neutral",
};
const STAGES = ["applied", "evaluated", "shortlisted", "invited", "booking_requested", "interview_scheduled", "interviewed", "declined", "withdrawn"];
const LABEL: Record<string, string> = {
  applied: "Applied", evaluated: "Evaluated", shortlisted: "Shortlisted", invited: "Invited", booking_requested: "Time requested",
  interview_scheduled: "Interview booked", interviewed: "Interviewed", withdrawn: "Withdrawn", declined: "Declined",
};

export function CandidatesPage() {
  const { status } = useAuth();
  const tz = status?.timezone;
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState("");
  const stage = sp.get("stage") ?? "";
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const openId = sp.get("open");
  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (stage) p.set("stage", stage);
    api(`/api/hr/candidates?${p}`).then(setData).catch((e) => setError(e.message));
  }, [q, stage]);
  useEffect(() => {
    const t = window.setTimeout(load, 200);
    return () => window.clearTimeout(t);
  }, [load]);
  const setParam = (k: string, v: string | null) => {
    const n = new URLSearchParams(sp);
    v ? n.set(k, v) : n.delete(k);
    setSp(n, { replace: true });
  };
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Candidates</h1>
          <p className="muted">Everyone who applied to your jobs, across roles. Stages come from recorded steps only (evaluation, approved shortlist, sent invitation, booking, interview).</p>
        </div>
      </div>
      <div className="filters">
        <input type="search" placeholder="Search name or email" aria-label="Search candidates" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={stage} onChange={(e) => setParam("stage", e.target.value || null)} aria-label="Filter by stage">
          <option value="">All stages</option>
          {STAGES.map((s) => <option key={s} value={s}>{LABEL[s]}</option>)}
        </select>
        {data && <span className="small muted">{data.total} candidate(s)</span>}
      </div>
      <ErrorBox error={error} onRetry={load} />
      {!data && <SkeletonRows rows={8} cols={5} />}
      {data && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Candidate</th><th>Applications</th><th className="num">Messages</th><th>Last activity</th><th><span className="sr-only">Open</span></th></tr></thead>
            <tbody>
              {data.items.length === 0 && <tr><td colSpan={5}><Empty title="No candidates match" icon="people" /></td></tr>}
              {data.items.map((c: any) => (
                <tr key={c.id}>
                  <td><strong>{c.name}</strong><div className="small muted mono">{c.email}</div></td>
                  <td>
                    {c.applications.map((a: any) => (
                      <div key={a.id} className="row" style={{ gap: 6 }}>
                        <span className="small">{a.job.title}</span>
                        <Badge tone={STAGE_TONE[a.stage]}>{a.stage_label}</Badge>
                        {a.evaluation?.flagged && <Badge tone="bad">flagged</Badge>}
                        {a.contact_status !== "ok" && <Badge tone="warn">contact</Badge>}
                        {a.parse_status !== "parsed" && <Badge tone="warn">manual doc</Badge>}
                      </div>
                    ))}
                  </td>
                  <td className="num mono">{c.messages || ""}</td>
                  <td className="small">{fmt.dateTime(c.last_activity, tz)}</td>
                  <td><button className="btn btn-small" onClick={() => setParam("open", c.id)}>Open</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <CandidateDrawer id={openId} tz={tz} onClose={() => setParam("open", null)} onChanged={load} />
    </div>
  );
}

function CandidateDrawer({ id, tz, onClose, onChanged }: { id: string | null; tz?: string; onClose: () => void; onChanged: () => void }) {
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmDecline, setConfirmDecline] = useState<string | null>(null);
  const load = useCallback(() => {
    if (!id) return;
    setD(null);
    setError(null);
    api(`/api/hr/candidates/${id}`).then(setD).catch((e) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);
  async function decline(appId: string) {
    try {
      await api(`/api/hr/applications/${appId}/decline-draft`, { method: "POST" });
      setMsg("Decline letter drafted. It is waiting in Approvals - nothing has been sent.");
      setConfirmDecline(null);
      load();
      onChanged();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  return (
    <Drawer open={!!id} title={d ? d.name : "Candidate"} onClose={onClose}>
      <ErrorBox error={error} />
      {msg && <Notice tone="good"><span>{msg}</span></Notice>}
      {!d && !error && <SkeletonRows rows={4} cols={2} />}
      {d && (
        <>
          <p className="small muted mono" style={{ marginTop: 0 }}>{d.email}</p>
          <h3>Applications</h3>
          {d.applications.map((a: any) => (
            <div key={a.id} className="criterion">
              <div className="spread">
                <span><strong>{a.job.title}</strong> <Badge tone={STAGE_TONE[a.stage]}>{a.stage_label}</Badge> {a.evaluation && <Badge tone={a.evaluation.source === "live" ? "ai" : "neutral"}>{a.evaluation.source}</Badge>}</span>
                <span className="row">
                  <Link className="btn btn-small" to={`/hr/jobs/${a.job.id}/applications?evidence=${a.id}`}>Evidence</Link>
                  {!["declined", "withdrawn"].includes(a.stage) && confirmDecline !== a.id && <button className="btn btn-small btn-danger" onClick={() => setConfirmDecline(a.id)}>Decline…</button>}
                </span>
              </div>
              <div className="small muted">Applied {fmt.dateTime(a.submitted_at, tz)}</div>
              {confirmDecline === a.id && (
                <div className="confirm">
                  <span className="small">You have decided not to continue with {d.name} for {a.job.title}. This only <strong>drafts</strong> a polite letter from the decline template - you approve the exact text before anything is sent.</span>
                  <span className="row"><button className="btn btn-small btn-primary" onClick={() => decline(a.id)}>Draft decline letter</button><button className="btn btn-small" onClick={() => setConfirmDecline(null)}>Cancel</button></span>
                </div>
              )}
            </div>
          ))}
          <h3>Interviews</h3>
          {d.interviews.length === 0 ? <p className="small muted">None.</p> : d.interviews.map((i: any) => (
            <div key={i.id} className="spread criterion"><span>{fmt.dateTime(i.starts_at, tz)} <StateBadge state={i.status} /></span><Link className="btn btn-small" to={`/hr/interviews/${i.id}`}>Kit & scorecard</Link></div>
          ))}
          <h3>Messages from the candidate</h3>
          {d.messages_list.length === 0 ? <p className="small muted">None.</p> : d.messages_list.map((m: any) => (
            <div key={m.id} className="spread criterion"><span><strong>{m.subject}</strong><div className="small muted">{fmt.dateTime(m.received_at, tz)}{m.summary && ` · ${m.summary}`}</div></span><Link className="btn btn-small" to={`/hr/inbox?message=${m.id}`}>Open</Link></div>
          ))}
          <h3>Emails</h3>
          {d.emails.length === 0 ? <p className="small muted">None.</p> : d.emails.map((e: any) => (
            <div key={e.id} className="spread criterion"><span>{e.subject}<div className="small muted">{e.kind} · prepared {fmt.dateTime(e.created_at, tz)}</div></span><StateBadge state={e.status} /></div>
          ))}
          <h3>Timeline</h3>
          <ul className="timeline">
            {d.timeline.map((t: any, i: number) => <li key={i}><span className="mono small">{t.action}</span> <span className="small muted">· {t.actor_role} · {fmt.dateTime(t.at, tz)}</span></li>)}
          </ul>
        </>
      )}
    </Drawer>
  );
}
