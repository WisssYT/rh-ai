import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, fmt } from "../../api";
import { Badge, Empty, ErrorBox, Loading, Notice, ScoreBar, StateBadge } from "../../components/ui";
import { EvidenceDrawer, JobNav, useJob } from "./HrJobs";

export function ShortlistPage() {
  const { id } = useParams();
  const { job, error: jobError, reload: reloadJob } = useJob(id);
  const [ranking, setRanking] = useState<any>(null);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [dirtyWeights, setDirtyWeights] = useState(false);
  const [lists, setLists] = useState<any>(null);
  const [picked, setPicked] = useState<Map<string, string>>(new Map()); // application_id -> override reason
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const debounce = useRef<number>();

  const loadRanking = useCallback(async () => {
    try {
      const [r, l] = await Promise.all([api(`/api/hr/jobs/${id}/ranking`), api(`/api/hr/jobs/${id}/shortlists`)]);
      setRanking(r);
      setLists(l);
      setWeights(r.weights);
      setDirtyWeights(false);
      const base = l.latest?.status === "draft" ? l.latest : l.approved;
      setPicked(new Map(base ? base.members.map((m: any) => [m.application_id, m.override_reason ?? ""]) : r.proposed.map((a: string) => [a, ""])));
    } catch (e) {
      setError((e as ApiError).message);
    }
  }, [id]);
  useEffect(() => {
    void loadRanking();
  }, [loadRanking]);

  function changeWeight(cid: string, v: number) {
    const w = { ...weights, [cid]: v };
    setWeights(w);
    setDirtyWeights(true);
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(async () => {
      try {
        const r = await api(`/api/hr/jobs/${id}/ranking/preview`, { body: { weights: w } });
        setRanking(r); // zero model calls - recomputed from saved criterion ratings
      } catch (e) {
        setError((e as ApiError).message);
      }
    }, 250);
  }
  async function saveWeights() {
    setBusy(true);
    try {
      await api(`/api/hr/jobs/${id}/weights`, { body: { weights, base_revision: ranking.weights_revision } });
      setMsg("Weights saved as a new revision (0 model calls). Any shortlist draft must be saved again against these weights.");
      reloadJob();
      await loadRanking();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  const rows: any[] = ranking?.rows ?? [];
  const proposed = useMemo(() => new Set<string>(ranking?.proposed ?? []), [ranking]);
  const review = useMemo(() => new Set<string>(ranking?.review ?? []), [ranking]);

  function toggle(aid: string) {
    const m = new Map(picked);
    m.has(aid) ? m.delete(aid) : m.set(aid, "");
    setPicked(m);
  }
  const missingReasons = [...picked.entries()].filter(([a, r]) => !proposed.has(a) && !r.trim());

  async function saveDraft() {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/hr/jobs/${id}/shortlists`, {
        body: { members: [...picked.entries()].map(([application_id, override_reason]) => ({ application_id, override_reason })) },
      });
      setMsg("Shortlist draft saved as a new revision. Review it below, then approve.");
      await loadRanking();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  async function approve() {
    const d = lists.latest;
    if (!confirm(`Approve shortlist revision ${d.revision} with ${d.members.length} candidate(s)? This is your decision, recorded with your name.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/hr/jobs/${id}/shortlists/${d.id}/approve`, { body: { digest: d.digest } });
      setMsg("Shortlist approved. You can now prepare invitation drafts for these candidates.");
      reloadJob();
      await loadRanking();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  async function prepare(generator: "ai" | "template") {
    setBusy(true);
    setError(null);
    try {
      const r = await api(`/api/hr/jobs/${id}/invitation-drafts`, { body: { application_ids: lists.approved.members.map((m: any) => m.application_id), generator } });
      const skipped = r.skipped.map((s: any) => `${rows.find((x) => x.application_id === s.application_id)?.candidate_name ?? s.application_id}: ${s.reason}`);
      setMsg(`${r.created.length} draft(s) prepared (${generator}). Nothing has been sent.${skipped.length ? " Skipped - " + skipped.join("; ") : ""}`);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  if (jobError) return <div className="page"><ErrorBox error={jobError} /></div>;
  if (!job || !ranking) return <div className="page">{error ? <ErrorBox error={error} /> : <Loading />}</div>;
  const latest = lists?.latest;
  const approved = lists?.approved;
  const draftPending = latest?.status === "draft";
  const selectionDiffers = (() => {
    if (!latest) return picked.size > 0;
    const a = new Set(latest.members.map((m: any) => m.application_id));
    return a.size !== picked.size || [...picked.keys()].some((k) => !a.has(k));
  })();
  const label = new Map<string, string>(ranking.criteria.map((c: any) => [c.id, c.label]));
  return (
    <div className="page">
      <JobNav job={job} />
      {msg && <Notice tone="good">{msg}</Notice>}
      <ErrorBox error={error} />
      <div className="grid grid-2">
        <div className="card">
          <h2>Weights {ranking.weights_preview && <Badge tone="warn">preview - not saved</Badge>}</h2>
          <p className="small muted">Changing weights recomputes totals from saved criterion ratings: <strong>{ranking.llm_calls} model calls</strong>. Criterion meaning changes go through the rubric editor.</p>
          <div className="weights">
            {ranking.criteria.map((c: any) => (
              <FragmentRow key={c.id} label={c.label} required={c.required} value={weights[c.id] ?? 0} onChange={(v) => changeWeight(c.id, v)} />
            ))}
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn btn-primary btn-small" disabled={!dirtyWeights || busy} onClick={saveWeights}>Save weights as new revision</button>
            <button className="btn btn-small" disabled={!dirtyWeights} onClick={loadRanking}>Discard preview</button>
          </div>
        </div>
        <div className="card">
          <h2>Shortlist decision</h2>
          <p className="small">
            Proposal: up to {ranking.shortlist_size} with evidence score ≥ {ranking.min_suggest_score}. {ranking.proposed.length} proposed. Selected by you: <strong>{picked.size}</strong>.
          </p>
          <p className="small muted">{ranking.order_label} Near-equal scores are marked ≈ - small differences do not show a better employee.</p>
          {approved && <Notice tone="good">Approved: revision {approved.revision} · {approved.members.length} candidate(s) · {fmt.dateTime(approved.approved_at)}</Notice>}
          {draftPending && <Notice tone="info">Draft revision {latest.revision} ({latest.members.length}) awaits your approval{selectionDiffers ? " - your current selection differs; save it first" : ""}.</Notice>}
          {missingReasons.length > 0 && <Notice tone="warn">{missingReasons.length} selected candidate(s) are outside the proposal - add an override reason in the table.</Notice>}
          <div className="row">
            <button className="btn" disabled={busy || picked.size === 0 || missingReasons.length > 0 || dirtyWeights} onClick={saveDraft} title={dirtyWeights ? "Save or discard weight preview first" : undefined}>
              Save selection as draft
            </button>
            <button className="btn btn-good" disabled={busy || !draftPending || selectionDiffers} onClick={approve}>
              Approve shortlist r{draftPending ? latest.revision : "-"}
            </button>
          </div>
          {approved && (
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn btn-small" disabled={busy} onClick={() => prepare("ai")}>Prepare invitation drafts (AI)</button>
              <button className="btn btn-small" disabled={busy} onClick={() => prepare("template")}>Prepare drafts (template)</button>
              <Link to="/hr/approvals" className="btn btn-small btn-primary">Review drafts →</Link>
            </div>
          )}
        </div>
      </div>
      <div className="card">
        <h2>Provisional ranking</h2>
        {rows.length === 0 && <Empty title="No applications yet" />}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Select</th>
                  <th scope="col">#</th>
                  <th scope="col">Candidate</th>
                  <th scope="col">Evidence score</th>
                  <th scope="col">Range / coverage</th>
                  <th scope="col">Status</th>
                  <th scope="col">Review</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const sel = picked.has(r.application_id);
                  const outside = sel && !proposed.has(r.application_id);
                  return (
                    <tr key={r.application_id} className={outside ? "outside" : sel ? "selected" : ""}>
                      <td>
                        <input type="checkbox" checked={sel} onChange={() => toggle(r.application_id)} aria-label={`Include ${r.candidate_name}`} />
                      </td>
                      <td>{r.position ?? "-"}{r.near_tie && <span title="Near-equal to a neighbour"> ≈</span>}</td>
                      <td>
                        <strong>{r.candidate_name}</strong>
                        <div className="small muted clamp" title={r.summary}>{r.summary}</div>
                        {outside && (
                          <input
                            aria-label={`Override reason for ${r.candidate_name}`}
                            placeholder="Override reason (required)"
                            value={picked.get(r.application_id) ?? ""}
                            onChange={(e) => setPicked(new Map(picked).set(r.application_id, e.target.value))}
                            style={{ marginTop: 4 }}
                          />
                        )}
                      </td>
                      <td style={{ minWidth: 140 }}>
                        <ScoreBar lower={r.lower} upper={r.upper} />
                        <span className="small">{fmt.num(r.lower)}</span>
                      </td>
                      <td className="small">
                        {r.lower !== null ? <>{fmt.num(r.lower)}–{fmt.num(r.upper)} · {fmt.num(r.coverage, 0)}%</> : "-"}
                        {r.unresolved_required?.length > 0 && <div><Badge tone="warn">unknown required: {r.unresolved_required.map((x: string) => label.get(x) ?? x).join(", ")}</Badge></div>}
                      </td>
                      <td>
                        {proposed.has(r.application_id) ? <Badge tone="info">proposed</Badge> : <Badge>not proposed</Badge>}{" "}
                        {approved?.members.some((m: any) => m.application_id === r.application_id) && <Badge tone="good">approved</Badge>}
                        <div><StateBadge state={r.evaluation_state} /> {r.evaluation_source && <Badge tone={r.evaluation_source === "live" ? "ai" : "neutral"}>{r.evaluation_source}</Badge>}</div>
                        {r.contact_status !== "ok" && <Badge tone="warn">contact review</Badge>}
                      </td>
                      <td className="small">{review.has(r.application_id) ? r.review_reasons.join("; ") : ""}</td>
                      <td><button className="btn btn-small" onClick={() => setDrawer(r.application_id)}>Evidence</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <EvidenceDrawer appId={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}

function FragmentRow({ label, required, value, onChange }: { label: string; required: boolean; value: number; onChange: (v: number) => void }) {
  const idv = `w-${label.replace(/\W+/g, "-")}`;
  return (
    <>
      <label htmlFor={idv} className="small">
        {label} {required && <Badge tone="info">required</Badge>}
      </label>
      <input id={idv} type="range" min={0} max={60} step={1} value={Math.round(value)} onChange={(e) => onChange(Number(e.target.value))} />
      <span className="mono">{Math.round(value)}</span>
    </>
  );
}
