import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fmt } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Empty, ErrorBox, Loading, ScoreBar, SkeletonRows, StateBadge } from "../../components/ui";

export function ReportsPage() {
  const [jobs, setJobs] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api("/api/hr/jobs").then((r) => setJobs(r.items)).catch((e) => setError(e.message));
  }, []);
  return (
    <div className="page medium">
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <p className="muted">A printable shortlist report per job for hiring managers or clients: the approved shortlist, the criteria and weights it was ranked on, cited evidence and open questions per person, and the approval record.</p>
        </div>
      </div>
      <ErrorBox error={error} />
      {!jobs && !error && <SkeletonRows rows={3} cols={3} />}
      {jobs && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Job</th><th>Status</th><th>Approved shortlist</th><th /></tr></thead>
            <tbody>
              {jobs.length === 0 && <tr><td colSpan={4}><Empty title="No jobs" /></td></tr>}
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td><strong>{j.title}</strong></td>
                  <td><StateBadge state={j.status} /></td>
                  <td>{j.approved_shortlist ? `r${j.approved_shortlist.revision} · ${j.approved_shortlist.members} people` : <span className="muted">none yet</span>}</td>
                  <td>{j.approved_shortlist ? <Link className="btn btn-small" to={`/hr/jobs/${j.id}/report`}>Open report</Link> : <Link className="btn btn-small btn-ghost" to={`/hr/jobs/${j.id}/shortlist`}>Go to ranking</Link>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Dots({ v }: { v: number | null }) {
  if (v === null || v === undefined) return <span className="muted mono small">unknown</span>;
  return <span className="rating" aria-label={`${v} of 4`}>{[1, 2, 3, 4].map((i) => <i key={i} className={i <= v ? "on" : ""} />)}</span>;
}

export function ReportPage() {
  const { id } = useParams();
  const { status } = useAuth();
  const tz = status?.timezone;
  const [r, setR] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api(`/api/hr/jobs/${id}/report`).then(setR).catch((e) => setError(e.message));
  }, [id]);
  if (!r) return <div className="page">{error ? <ErrorBox error={error} /> : <Loading />}</div>;
  const sl = r.shortlist;
  const synthetic = r.members.some((m: any) => m.source === "replay");
  return (
    <div className="page">
      <div className="spread no-print" style={{ marginBottom: 14 }}>
        <p className="crumb" style={{ margin: 0 }}><Link to="/hr/reports">Reports</Link> / {r.job.title}</p>
        <button className="btn btn-primary" onClick={() => window.print()} disabled={!sl}>Print / save as PDF</button>
      </div>
      <article className="report-sheet">
        <p className="report-kicker">{status?.company_name} · shortlist report · fictional data</p>
        <h1>{r.job.title}</h1>
        <p className="muted" style={{ margin: "6px 0 0" }}>{r.job.location}{r.job.summary && ` - ${r.job.summary}`}</p>
        {!sl ? <Empty title="No approved shortlist for this job yet" /> : (
          <>
            <div className="spread" style={{ marginTop: 20, alignItems: "flex-start" }}>
              <div className="small">
                <div>{r.members.length} people · rubric r{sl.rubric_revision} · weights r{sl.weights_revision}</div>
                <div className="muted">Generated {fmt.dateTime(r.generated_at, tz)}</div>
                {synthetic && <div style={{ marginTop: 4 }}><Badge tone="neutral">contains replay · synthetic evaluations (not an LLM)</Badge></div>}
              </div>
              <span className="stamp"><strong>Human approved</strong>{sl.approved_by} · {fmt.dateTime(sl.approved_at, tz)}<span>r{sl.revision} · {sl.digest.slice(0, 12)}…</span></span>
            </div>

            <h2>Criteria</h2>
            <table>
              <thead><tr><th>Criterion</th><th>Type</th><th className="num">Weight</th></tr></thead>
              <tbody>
                {r.rubric.map((c: any) => (
                  <tr key={c.id}><td>{c.label}<div className="small muted">{c.description}</div></td><td className="small">{c.required ? "required" : "preferred"}</td><td className="num mono">{(r.weights[c.id] ?? 0).toFixed(0)}%</td></tr>
                ))}
              </tbody>
            </table>

            <h2>Shortlist</h2>
            {r.members.map((m: any, i: number) => (
              <section key={m.application_id} className="report-member">
                <h3><span className="mono small muted">{String(i + 1).padStart(2, "0")}</span>{m.name}
                  {!m.in_proposal && <Badge tone="warn">added by recruiter</Badge>}
                  {m.flags?.includes("possible_prompt_injection") && <Badge tone="bad">CV contained instruction-like text</Badge>}
                </h3>
                <div className="row small" style={{ gap: 14, margin: "4px 0 10px" }}>
                  <span style={{ width: 160 }}><ScoreBar lower={m.lower} upper={m.upper} /></span>
                  <span className="mono">evidence {m.lower?.toFixed(1) ?? "-"} · up to {m.upper?.toFixed(1) ?? "-"} · coverage {m.coverage?.toFixed(0) ?? "-"}%</span>
                </div>
                {m.override_reason && <p className="small" style={{ margin: "0 0 8px" }}><strong>Reason for inclusion:</strong> {m.override_reason}</p>}
                {m.criteria.map((c: any) => (
                  <div key={c.id} className="report-crit">
                    <span>{c.label}{c.required && " *"}</span>
                    <span><Dots v={c.rating} /></span>
                    <span>
                      {c.evidence.map((e: any, k: number) => <div key={k} className="quote" style={{ margin: "0 0 2px" }}><q>{e.quote}</q><span className="ref">p{e.page} · {e.segment_id}</span></div>)}
                      {c.status !== "supported" && <span className="small muted">{c.unknowns[0] ?? "No evidence in the CV - ask in the interview."}</span>}
                      {c.status === "supported" && c.unknowns[0] && <div className="small muted">Open: {c.unknowns[0]}</div>}
                    </span>
                  </div>
                ))}
              </section>
            ))}
            <p className="report-foot">
              Ratings are provisional, evidence-backed assessments of what the CV states (candidate claims, not verified facts).
              Unknown means the CV gave no evidence - not a negative finding. The order is a lower-bound evidence score and is
              not a hiring decision; the shortlist above was approved by a person, recorded with revision and digest.
              Fictional hackathon data.
            </p>
          </>
        )}
      </article>
    </div>
  );
}
