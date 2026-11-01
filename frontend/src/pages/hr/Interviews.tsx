import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, fmt } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Empty, ErrorBox, Loading, Notice, SkeletonRows, StateBadge } from "../../components/ui";

const REC: Record<string, string> = { advance: "Advance", hold: "Hold", do_not_advance: "Do not advance", undecided: "Undecided" };
const FOCUS: Record<string, string> = { unknown: "No evidence in CV", depth: "Limited evidence", verify: "Verify a claim" };

export function InterviewsPage() {
  const { status } = useAuth();
  const tz = status?.timezone;
  const [when, setWhen] = useState<"upcoming" | "past" | "all">("upcoming");
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api(`/api/hr/interviews?when=${when}`).then(setData).catch((e) => setError(e.message));
  }, [when]);
  useEffect(load, [load]);
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Interviews</h1>
          <p className="muted">Confirmed interviews with a question kit aimed at each candidate's unknowns and unverified claims, and a structured scorecard for every interviewer.</p>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {(["upcoming", "past", "all"] as const).map((w) => <button key={w} role="tab" aria-selected={when === w} onClick={() => setWhen(w)}>{w[0].toUpperCase() + w.slice(1)}</button>)}
      </div>
      <ErrorBox error={error} onRetry={load} />
      {!data && <SkeletonRows rows={4} cols={6} />}
      {data && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>When</th><th>Candidate</th><th>Job</th><th>Interviewer</th><th>Kit</th><th>Your scorecard</th><th>Confirmation</th><th /></tr></thead>
            <tbody>
              {data.items.length === 0 && <tr><td colSpan={8}><Empty title={`No ${when === "all" ? "" : when} interviews`} icon="chat">Interviews appear here once you confirm a booking request in the calendar.</Empty></td></tr>}
              {data.items.map((i: any) => (
                <tr key={i.id}>
                  <td className="small"><strong>{fmt.day(i.starts_at, tz)}</strong><div className="mono">{fmt.time(i.starts_at, tz)}-{fmt.time(i.ends_at, tz)}</div></td>
                  <td><strong>{i.candidate.name}</strong></td>
                  <td>{i.job.title}</td>
                  <td className="small">{i.interviewer.name}</td>
                  <td>{i.kit ? <Badge tone={i.kit.source === "live" ? "ai" : "neutral"}>r{i.kit.revision} · {i.kit.source}</Badge> : <span className="muted small">not prepared</span>}</td>
                  <td>{i.my_scorecard ? <StateBadge state={i.my_scorecard.status === "submitted" ? "completed" : "draft"} label={i.my_scorecard.status === "submitted" ? `submitted · ${REC[i.my_scorecard.recommendation]}` : "draft"} /> : <span className="muted small">-</span>}
                    {i.scorecards_submitted > 0 && <div className="small muted">{i.scorecards_submitted} submitted</div>}</td>
                  <td>{i.confirmation_email ? <StateBadge state={i.confirmation_email.status} /> : <span className="muted small">none</span>}</td>
                  <td><Link className="btn btn-small" to={`/hr/interviews/${i.id}`}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function InterviewDetailPage() {
  const { id } = useParams();
  const { status } = useAuth();
  const tz = status?.timezone;
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [card, setCard] = useState<{ ratings: Record<string, number | null>; notes: Record<string, string>; summary: string; recommendation: string; revision?: number }>({ ratings: {}, notes: {}, summary: "", recommendation: "undecided" });
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const load = useCallback(() => {
    api(`/api/hr/interviews/${id}`).then((x) => {
      setD(x);
      if (x.my_scorecard) setCard({ ratings: x.my_scorecard.ratings, notes: x.my_scorecard.notes, summary: x.my_scorecard.summary, recommendation: x.my_scorecard.recommendation, revision: x.my_scorecard.revision });
    }).catch((e) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);

  async function kit(generator: "ai" | "template") {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/hr/interviews/${id}/kit`, { body: { generator } });
      setMsg("Interview kit prepared. Questions are suggestions - use, edit or skip them.");
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  async function save(submit: boolean) {
    setBusy(true);
    setError(null);
    try {
      const body = { ratings: card.ratings, notes: card.notes, summary: card.summary, recommendation: card.recommendation, revision: card.revision ?? null };
      const r = await api(`/api/hr/interviews/${id}/scorecard${submit ? "/submit" : ""}`, { method: submit ? "POST" : "PUT", body });
      setCard({ ...card, revision: r.revision });
      setMsg(submit ? "Scorecard submitted and recorded with your name. It can no longer change." : "Draft saved.");
      setConfirmSubmit(false);
      load();
    } catch (e) {
      setError((e as ApiError).message);
      load();
    } finally {
      setBusy(false);
    }
  }
  if (!d) return <div className="page">{error ? <ErrorBox error={error} onRetry={load} /> : <Loading />}</div>;
  const submitted = d.my_scorecard?.status === "submitted";
  const k = d.kit;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="crumb"><Link to="/hr/interviews">Interviews</Link> / {d.candidate.name}</p>
          <h1>{d.candidate.name} · {d.job.title}</h1>
          <div className="ws-meta">
            <span>{fmt.dateTime(d.starts_at, tz)}-{fmt.time(d.ends_at, tz)}</span><span>{d.location}</span><span>with {d.interviewer.name}</span>
            {d.past && <span>held</span>}
          </div>
        </div>
        <Link className="btn" to={`/hr/jobs/${d.job.id}/applications?evidence=${d.candidate.application_id}`}>Evidence</Link>
      </div>
      {msg && <Notice tone="good"><span>{msg}</span></Notice>}
      <ErrorBox error={error} />
      <div className="grid grid-dash">
        <section className="card" aria-labelledby="kit-h">
          <div className="spread">
            <h2 id="kit-h">Interview kit {k && <Badge tone={k.source === "live" ? "ai" : "neutral"}>r{k.revision} · {k.source === "live" ? "live LLM" : k.source === "replay" ? "replay · synthetic" : "template"}</Badge>}</h2>
            <span className="row">
              <button className="btn btn-small btn-primary" disabled={busy || !d.evaluation} onClick={() => kit("ai")}>{k ? "Regenerate with AI" : "Prepare with AI"}</button>
              <button className="btn btn-small" disabled={busy || !d.evaluation} onClick={() => kit("template")}>Template questions</button>
            </span>
          </div>
          {!d.evaluation && <Notice tone="warn"><span>No evaluation for this application yet - authorize an analysis run first.</span></Notice>}
          {d.evaluation?.stale && <Notice tone="warn"><span>The evaluation is stale (rubric changed). Re-run the analysis before preparing a kit.</span></Notice>}
          <p className="small muted" style={{ marginTop: 0 }}>One question per criterion, aimed at what the CV does not prove. The context line is the verified quote or recorded unknown it came from; the model only writes the wording and never sees the candidate's name or contact details.</p>
          {!k && <Empty title="No kit yet" icon="chat" />}
          {k?.items.map((it: any, n: number) => (
            <div key={it.criterion_id} className="kit-item">
              <div className="spread">
                <span><span className="mono small muted">Q{n + 1} · </span><strong>{it.label}</strong>{it.required && <span className="small muted"> · required</span>}</span>
                <span className={`kit-focus kit-focus-${it.focus}`}>{FOCUS[it.focus]}{it.rating !== null && it.rating !== undefined && ` · rated ${it.rating}/4`}</span>
              </div>
              <p className="kit-q">{it.question}</p>
              {it.context && (it.focus === "unknown"
                ? <p className="small muted" style={{ margin: 0 }}>Recorded unknown: {it.context}</p>
                : <p className="quote small" style={{ margin: 0 }}><q>{it.context}</q>{it.ref && <span className="ref">{it.ref}</span>} <span className="small muted">candidate claim, not verified</span></p>)}
              {it.listen_for && <div className="kit-listen">Strong answer (anchor 4): {it.listen_for}</div>}
            </div>
          ))}
        </section>

        <section className="card" aria-labelledby="sc-h">
          <div className="spread">
            <h2 id="sc-h">Your scorecard {submitted ? <StateBadge state="completed" label="submitted" /> : d.my_scorecard ? <StateBadge state="draft" /> : null}</h2>
            {submitted && <span className="stamp"><strong>Submitted</strong>{fmt.dateTime(d.my_scorecard.submitted_at, tz)}</span>}
          </div>
          <p className="small muted" style={{ marginTop: 0 }}>Your own judgement from the interview, on the job's criteria. Leave a rating empty if it did not come up.</p>
          {d.criteria.map((c: any) => (
            <div key={c.id} className="score-crit">
              <div className="spread">
                <strong className="small">{c.label}{c.required && " *"}</strong>
                <span className="rate" role="group" aria-label={`Rating for ${c.label}`}>
                  {[0, 1, 2, 3, 4].map((v) => (
                    <button key={v} type="button" aria-pressed={card.ratings[c.id] === v} disabled={submitted} title={c.anchors[String(v)]}
                      onClick={() => setCard({ ...card, ratings: { ...card.ratings, [c.id]: card.ratings[c.id] === v ? null : v } })}>{v}</button>
                  ))}
                </span>
              </div>
              {card.ratings[c.id] !== undefined && card.ratings[c.id] !== null && <div className="small muted">{c.anchors[String(card.ratings[c.id])]}</div>}
              <textarea aria-label={`Notes for ${c.label}`} placeholder="Notes (what they said, examples)" value={card.notes[c.id] ?? ""} disabled={submitted}
                onChange={(e) => setCard({ ...card, notes: { ...card.notes, [c.id]: e.target.value } })} maxLength={1000} />
            </div>
          ))}
          <div className="field" style={{ marginTop: 12 }}>
            <label htmlFor="sc-sum">Summary</label>
            <textarea id="sc-sum" value={card.summary} disabled={submitted} onChange={(e) => setCard({ ...card, summary: e.target.value })} style={{ minHeight: 90 }} maxLength={3000} />
          </div>
          <div className="field">
            <span className="small" style={{ fontWeight: 500 }}>Your recommendation</span>
            <div className="seg" role="group" aria-label="Recommendation">
              {Object.entries(REC).map(([v, l]) => <button key={v} type="button" aria-pressed={card.recommendation === v} disabled={submitted} onClick={() => setCard({ ...card, recommendation: v })}>{l}</button>)}
            </div>
          </div>
          {!submitted && !confirmSubmit && (
            <div className="row">
              <button className="btn" disabled={busy} onClick={() => save(false)}>Save draft</button>
              <button className="btn btn-good" disabled={busy} onClick={() => setConfirmSubmit(true)}>Submit scorecard…</button>
            </div>
          )}
          {confirmSubmit && (
            <div className="confirm">
              <span className="small">Submit as your final record, with your name and time. It can't be edited afterwards.</span>
              <span className="row"><button className="btn btn-good btn-small" disabled={busy} onClick={() => save(true)}>Submit</button><button className="btn btn-small" onClick={() => setConfirmSubmit(false)}>Cancel</button></span>
            </div>
          )}
          {d.other_scorecards.length > 0 && (
            <>
              <h3>Other interviewers</h3>
              {d.other_scorecards.map((o: any) => (
                <div key={o.id} className="criterion small">
                  <strong>{o.interviewer}</strong> · {REC[o.recommendation]} · {fmt.dateTime(o.submitted_at, tz)}
                  <div className="muted">{o.summary}</div>
                </div>
              ))}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
