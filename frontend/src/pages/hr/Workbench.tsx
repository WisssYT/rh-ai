import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, fmt } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Empty, ErrorBox, Notice, SkeletonRows, StateBadge } from "../../components/ui";

/* =============================== Review queue =============================== */

const KIND_LABEL: Record<string, string> = {
  injection: "injection", invalid_output: "AI output", needs_review: "evaluation", manual_document: "document",
  contact: "contact", suspicious_message: "inbox", email_problem: "email",
};

export function ReviewQueuePage() {
  const { status } = useAuth();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"open" | "done">("open");
  const [kind, setKind] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const load = useCallback(() => {
    api("/api/hr/review-queue").then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  async function ack(key: string) {
    try {
      await api("/api/hr/review-queue/ack", { body: { key, note: notes[key] ?? "" } });
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  const items: any[] = (data?.items ?? []).filter((i: any) => (tab === "open" ? !i.ack : !!i.ack) && (!kind || i.kind === kind));
  const kinds = [...new Set<string>((data?.items ?? []).map((i: any) => i.kind))];
  return (
    <div className="page medium">
      <div className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="muted">Everything the system routed to a person instead of deciding itself: suspicious content, unreadable documents, contact mismatches, rejected AI output and delivery problems. Marking an item reviewed records who looked at it - it never changes a rating or a decision.</p>
        </div>
      </div>
      <ErrorBox error={error} onRetry={load} />
      <div className="toolbar">
        <div className="tabs" role="tablist" style={{ marginBottom: 0, borderBottom: 0 }}>
          <button role="tab" aria-selected={tab === "open"} onClick={() => setTab("open")}>Open ({data?.open ?? "…"})</button>
          <button role="tab" aria-selected={tab === "done"} onClick={() => setTab("done")}>Reviewed ({data ? data.items.length - data.open : "…"})</button>
        </div>
        <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: "auto" }} aria-label="Filter by kind">
          <option value="">All kinds</option>
          {kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k] ?? k}</option>)}
        </select>
      </div>
      {!data && <SkeletonRows rows={5} cols={3} />}
      {data && (
        <div className="card" style={{ padding: 0 }}>
          {items.length === 0 && <Empty title={tab === "open" ? "Nothing waiting for review" : "Nothing reviewed yet"} icon="flag" />}
          {items.map((i) => (
            <div key={i.key} className={`rq-item${i.ack ? " acked" : ""}`}>
              <div>
                <div className={`rq-sev rq-sev-${i.severity}`}>{i.severity}</div>
                <div className="small muted mono">{KIND_LABEL[i.kind] ?? i.kind}</div>
              </div>
              <div>
                <strong>{i.title}</strong>
                <div className="small muted">{[i.candidate_name, i.job_title].filter(Boolean).join(" · ")}{i.at && ` · ${fmt.dateTime(i.at, status?.timezone)}`}</div>
                <div className="small" style={{ marginTop: 4 }}>{i.detail}</div>
                {i.ack && <div className="small muted" style={{ marginTop: 4 }}>Reviewed by {i.ack.by} · {fmt.dateTime(i.ack.at, status?.timezone)}{i.ack.note && ` - “${i.ack.note}”`}</div>}
              </div>
              <div className="rq-actions">
                <Link className="btn btn-small" to={i.link}>Open</Link>
                {!i.ack && (
                  <>
                    <input aria-label="Note (optional)" placeholder="Note (optional)" value={notes[i.key] ?? ""} onChange={(e) => setNotes({ ...notes, [i.key]: e.target.value })} maxLength={300} />
                    <button className="btn btn-small btn-good" onClick={() => ack(i.key)}>Mark reviewed</button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* =============================== Follow-ups =============================== */

export function FollowUpsPage() {
  const { status } = useAuth();
  const tz = status?.timezone;
  const [hours, setHours] = useState(48);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const load = useCallback(() => {
    api(`/api/hr/followups?older_than_hours=${hours}`).then((d) => {
      setData(d);
      setPicked(new Set(d.items.filter((f: any) => f.due && f.contact_status === "ok").map((f: any) => f.invitation_id)));
      setConfirmed(false);
    }).catch((e) => setError(e.message));
  }, [hours]);
  useEffect(load, [load]);

  async function prepare() {
    setBusy(true);
    setError(null);
    try {
      const r = await api("/api/hr/followups/reminders", { body: { invitation_ids: [...picked] } });
      setMsg(`${r.created.length} reminder draft(s) prepared${r.skipped.length ? `, ${r.skipped.length} skipped (${r.skipped.map((s: any) => s.reason).join("; ")})` : ""}. Nothing has been sent.`);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  const drafts: any[] = (data?.pending_drafts ?? []).filter((d: any) => d.status === "draft");
  const sendable = drafts.filter((d) => !d.blocking_problem);
  async function approveAll() {
    setBusy(true);
    setError(null);
    try {
      const r = await api("/api/hr/email-drafts/batch-approve", {
        body: { items: sendable.map((d) => ({ id: d.id, revision: d.revision, digest: d.digest })), confirm_recipients: confirmed },
      });
      const failed = r.results.filter((x: any) => !x.ok);
      setMsg(`${r.approved} reminder(s) approved and queued for sending.${failed.length ? ` ${failed.length} refused: ${failed.map((f: any) => `${f.to} (${f.reason})`).join("; ")}` : ""}`);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  const items: any[] = data?.items ?? [];
  return (
    <div className="page medium">
      <div className="page-head">
        <div>
          <h1>Follow-ups</h1>
          <p className="muted">Invited candidates who have not picked an interview time. Reminders are prepared only when you click, and go out only after you approve the listed recipients and messages. There are no automatic follow-ups.</p>
        </div>
        <label className="row small">Waiting at least
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))} style={{ width: "auto" }}>
            {[0, 24, 48, 72, 120].map((h) => <option key={h} value={h}>{h === 0 ? "any time" : `${h} h`}</option>)}
          </select>
        </label>
      </div>
      {msg && <Notice tone="good"><span>{msg}</span></Notice>}
      <ErrorBox error={error} onRetry={load} />
      {!data && <SkeletonRows rows={4} cols={5} />}
      {data && (
        <>
          <div className="table-wrap">
            <table>
              <thead><tr><th><span className="sr-only">Select</span></th><th>Candidate</th><th>Job</th><th>Invited</th><th className="num">Waiting</th><th className="num">Reminders</th><th>Status</th></tr></thead>
              <tbody>
                {items.length === 0 && <tr><td colSpan={7}><Empty title="Every invited candidate has requested a time" icon="repeat" /></td></tr>}
                {items.map((f) => (
                  <tr key={f.invitation_id} className={picked.has(f.invitation_id) ? "selected" : ""}>
                    <td><input type="checkbox" aria-label={`Select ${f.candidate_name}`} checked={picked.has(f.invitation_id)} disabled={!f.due || f.contact_status !== "ok"}
                      onChange={() => { const s = new Set(picked); s.has(f.invitation_id) ? s.delete(f.invitation_id) : s.add(f.invitation_id); setPicked(s); }} /></td>
                    <td><strong>{f.candidate_name}</strong><div className="small muted mono">{f.to}</div></td>
                    <td>{f.job.title}</td>
                    <td className="small">{fmt.dateTime(f.invited_at, tz)}<div className="muted">expires {fmt.dateTime(f.expires_at, tz)}</div></td>
                    <td className="num mono">{f.hours_waiting < 48 ? `${f.hours_waiting.toFixed(0)} h` : `${(f.hours_waiting / 24).toFixed(1)} d`}</td>
                    <td className="num mono">{f.reminders_sent}</td>
                    <td>{f.pending_draft ? <StateBadge state={f.pending_draft.status} label={`reminder ${f.pending_draft.status.replace(/_/g, " ")}`} /> : f.due ? <Badge tone="warn">due</Badge> : <Badge tone="neutral">recently contacted</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ margin: "12px 0 24px" }}>
            <button className="btn btn-primary" disabled={!picked.size || busy} onClick={prepare}>Prepare {picked.size} reminder draft(s)</button>
            <span className="small muted">Uses the default reminder template (Library → Templates) and the candidate's existing booking link.</span>
          </div>

          <h2>Waiting for your approval ({drafts.length})</h2>
          {drafts.length === 0 ? <p className="muted small">No reminder drafts waiting.</p> : (
            <div className="card">
              <p className="small" style={{ marginTop: 0 }}>You are approving <strong>exactly these {sendable.length} messages</strong> to these recipients. Each one is recorded as its own approval of that revision.</p>
              <div className="table-wrap" style={{ maxHeight: 360 }}>
                <table>
                  <thead><tr><th>To</th><th>Candidate</th><th>Subject</th><th>Revision</th><th /></tr></thead>
                  <tbody>
                    {drafts.map((d) => (
                      <tr key={d.id}>
                        <td className="mono">{d.preview.to}</td>
                        <td>{d.candidate.name}{d.blocking_problem && <div className="small" style={{ color: "var(--bad)" }}>{d.blocking_problem}</div>}</td>
                        <td>{d.preview.subject}</td>
                        <td className="mono">r{d.revision}</td>
                        <td><button className="btn btn-ghost btn-small" onClick={() => setPreview(preview === d.id ? null : d.id)}>{preview === d.id ? "Hide" : "Read"}</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {preview && (() => { const d = drafts.find((x) => x.id === preview); return d ? (
                <div className="email-preview" style={{ marginTop: 10 }}>
                  <dl><dt>To</dt><dd>{d.preview.to}</dd><dt>Subject</dt><dd>{d.preview.subject}</dd><dt>Booking link</dt><dd className="mono">{d.preview.link_url}</dd></dl>
                  <pre>{d.preview.body}</pre>
                </div>) : null; })()}
              <label className="check" style={{ marginTop: 12 }}>
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                <span>I reviewed the {sendable.length} recipient(s) and message(s) listed above.</span>
              </label>
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn btn-good" disabled={!confirmed || !sendable.length || busy} onClick={approveAll}>Approve & send {sendable.length} reminder(s)</button>
                <Link className="btn" to="/hr/approvals">Edit individually in Approvals</Link>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* =============================== Templates =============================== */

const KIND_TITLE: Record<string, string> = { invitation: "Interview invitation", reminder: "Booking reminder", reply: "Reply to a candidate", decline: "Decline letter" };

export function TemplatesPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [edit, setEdit] = useState<any | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const t = useRef<number>();
  const load = useCallback(() => {
    api("/api/hr/templates").then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    if (!edit) return;
    window.clearTimeout(t.current);
    t.current = window.setTimeout(() => {
      api("/api/hr/templates/preview", { body: { kind: edit.kind, subject: edit.subject, body: edit.body } })
        .then((p) => { setPreview(p); setPreviewErr(null); })
        .catch((e) => setPreviewErr((e as ApiError).message));
    }, 300);
  }, [edit?.kind, edit?.subject, edit?.body]); // eslint-disable-line react-hooks/exhaustive-deps

  const byKind = useMemo(() => {
    const m: Record<string, any[]> = {};
    (data?.kinds ?? []).forEach((k: string) => (m[k] = []));
    (data?.items ?? []).forEach((x: any) => (m[x.kind] ??= []).push(x));
    return m;
  }, [data]);

  function startNew(kind: string) {
    const b = data.builtin[kind];
    setEdit({ id: null, kind, name: "", subject: b.subject, body: b.body, is_default: true });
  }
  function insert(ph: string) {
    const el = bodyRef.current;
    const token = `{${ph}}`;
    if (!el) return setEdit({ ...edit, body: edit.body + token });
    const s = el.selectionStart ?? edit.body.length;
    const e = el.selectionEnd ?? s;
    setEdit({ ...edit, body: edit.body.slice(0, s) + token + edit.body.slice(e) });
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(s + token.length, s + token.length); });
  }
  async function save() {
    setError(null);
    try {
      const body = { kind: edit.kind, name: edit.name, subject: edit.subject, body: edit.body, is_default: edit.is_default };
      if (edit.id) await api(`/api/hr/templates/${edit.id}`, { method: "PUT", body });
      else await api("/api/hr/templates", { body });
      setMsg("Template saved. It applies to drafts prepared from now on - existing drafts are unchanged.");
      setEdit(null);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  async function remove(id: string) {
    if (!confirm("Delete this template? Drafts already prepared are not affected.")) return;
    try {
      await api(`/api/hr/templates/${id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  if (!data) return <div className="page">{error ? <ErrorBox error={error} onRetry={load} /> : <SkeletonRows rows={4} cols={3} />}</div>;
  const placeholders = Object.entries(data.placeholders as Record<string, string>).filter(([k]) => !edit || k !== "stage_sentence" || edit.kind === "reply");
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Templates</h1>
          <p className="muted">Company-wide wording for template drafts. Only the listed placeholders are filled in; booking links, expiry and the footer are always added by the system. Every message prepared from a template still needs approval of its exact text.</p>
        </div>
      </div>
      {msg && <Notice tone="good"><span>{msg}</span></Notice>}
      <ErrorBox error={error} />
      <div className="grid grid-dash">
        <div>
          {data.kinds.map((k: string) => {
            const list = byKind[k] ?? [];
            const def = list.find((x) => x.is_default);
            return (
              <div key={k} className="card">
                <div className="spread">
                  <h2>{KIND_TITLE[k] ?? k}</h2>
                  <button className="btn btn-small" onClick={() => startNew(k)}>New</button>
                </div>
                {!def && <p className="small muted" style={{ margin: "0 0 6px" }}>In use: <span className="mono">{data.builtin[k].name}</span></p>}
                {list.map((x) => (
                  <div key={x.id} className="spread criterion">
                    <span><strong>{x.name}</strong> {x.is_default && <Badge tone="good">in use</Badge>}<div className="small muted">{x.subject} · updated {fmt.dateTime(x.updated_at)} by {x.updated_by}</div></span>
                    <span className="row"><button className="btn btn-small" onClick={() => setEdit({ ...x })}>Edit</button><button className="btn btn-small btn-danger" onClick={() => remove(x.id)}>Delete</button></span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
        <div>
          {!edit ? (
            <div className="card"><Empty title="Pick a template to edit, or create one" icon="template">Templates are optional - built-in wording is used otherwise.</Empty></div>
          ) : (
            <div className="card">
              <h2>{edit.id ? "Edit template" : "New template"} · {KIND_TITLE[edit.kind]}</h2>
              <div className="field"><label htmlFor="tn">Name</label><input id="tn" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} maxLength={120} /></div>
              <div className="field"><label htmlFor="ts">Subject</label><input id="ts" value={edit.subject} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} maxLength={150} /></div>
              <div className="field">
                <label htmlFor="tb">Body</label>
                <div className="chips" aria-label="Insert placeholder">
                  {placeholders.map(([k, d]) => <button key={k} type="button" className="chip" title={d} onClick={() => insert(k)}>{`{${k}}`}</button>)}
                </div>
                <textarea id="tb" ref={bodyRef} value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} maxLength={3000} />
              </div>
              <label className="check"><input type="checkbox" checked={edit.is_default} onChange={(e) => setEdit({ ...edit, is_default: e.target.checked })} /><span>Use this template for new {KIND_TITLE[edit.kind]?.toLowerCase()} drafts</span></label>
              <h3>Preview with sample (fictional) values</h3>
              {previewErr ? <Notice tone="warn"><span>{previewErr}</span></Notice> : preview && (
                <div className="email-preview"><dl><dt>Subject</dt><dd>{preview.subject}</dd></dl><pre>{preview.body}</pre></div>
              )}
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn btn-primary" disabled={!!previewErr || edit.name.trim().length < 2} onClick={save}>Save template</button>
                <button className="btn" onClick={() => setEdit(null)}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
