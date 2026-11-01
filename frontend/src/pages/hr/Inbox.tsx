import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, fmt } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Empty, ErrorBox, Notice, SkeletonRows } from "../../components/ui";
import { DraftCard } from "./HrOps";

const CATEGORY: Record<string, string> = {
  status_question: "status question", candidate_question: "candidate question", scheduling: "scheduling",
  withdrawal: "withdrawal", internal: "internal", vendor: "vendor", newsletter: "newsletter", suspicious: "suspicious", other: "other",
};

export function InboxPage() {
  const { status } = useAuth();
  const tz = status?.timezone;
  const [sp] = useSearchParams();
  const [tab, setTab] = useState<"open" | "replied" | "archived">("open");
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(sp.get("message"));
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, { draft: any; sources: string[] }>>({});

  const load = useCallback(() => {
    api(`/api/hr/inbox?status=${tab}`).then(setData).catch((e) => setError(e.message));
  }, [tab]);
  useEffect(load, [load]);

  async function brief() {
    setBusy(true);
    setError(null);
    try {
      const r = await api("/api/hr/inbox/brief", { body: {} });
      setMsg(`${r.triaged.length} message(s) sorted${r.failed.length ? `, ${r.failed.length} could not be sorted (${r.failed[0].reason})` : ""}. Labels are provisional; nothing was sent or answered.`);
      setConfirm(false);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  async function draft(id: string, generator: "ai" | "template") {
    setError(null);
    try {
      const r = await api(`/api/hr/inbox/${id}/reply-draft`, { body: { generator } });
      setDrafts((d) => ({ ...d, [id]: { draft: r, sources: r.sources } }));
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  async function refreshDraft(id: string, draftId: string) {
    try {
      const d = await api(`/api/hr/email-drafts/${draftId}`);
      setDrafts((x) => ({ ...x, [id]: { draft: d, sources: x[id]?.sources ?? [] } }));
    } catch {
      /* ignore */
    }
    load();
  }
  async function action(id: string, a: "archive" | "reopen") {
    try {
      await api(`/api/hr/inbox/${id}/${a}`, { method: "POST" });
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  const items: any[] = data?.items ?? [];
  const groups = useMemo(() => {
    const needs = items.filter((m) => m.triaged_at && m.needs_human).sort((a, b) => (a.urgency === "high" ? -1 : 0) - (b.urgency === "high" ? -1 : 0));
    const fyi = items.filter((m) => m.triaged_at && !m.needs_human);
    const unsorted = items.filter((m) => !m.triaged_at);
    return { needs, fyi, unsorted };
  }, [items]);

  const today = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: tz }).format(new Date());
  const sorted = items.filter((m) => m.triaged_at);
  const sources = new Set(sorted.map((m) => m.triage_source));

  // A render helper (not a nested component) so open drafts keep their editing state across reloads.
  function renderMessage(m: any) {
    const isOpen = open === m.id;
    const d = drafts[m.id];
    const suspicious = m.flags.includes("possible_prompt_injection");
    return (
      <article key={m.id} className={`msg${isOpen ? " open" : ""}`}>
        <button className="msg-head" onClick={() => setOpen(isOpen ? null : m.id)} aria-expanded={isOpen}>
          <span className={`msg-urg msg-urg-${m.urgency ?? "none"}`} aria-label={m.urgency ? `${m.urgency} urgency` : "not sorted"} />
          <span>
            <span className="msg-subject">{m.subject}</span>
            <span className="msg-from"> · {m.from_name || m.from_email}{m.channel === "candidate_portal" ? " (candidate portal)" : ""}</span>
            {m.summary && <div className="msg-summary">{m.summary}</div>}
          </span>
          <span className="msg-meta">
            <span>{fmt.dateTime(m.received_at, tz)}</span>
            <span className="row" style={{ gap: 4 }}>
              {m.category && <Badge tone={suspicious ? "bad" : m.category === "internal" ? "info" : "neutral"}>{CATEGORY[m.category] ?? m.category}</Badge>}
              {m.application && <Badge tone="good" plain>{m.application.job_title}</Badge>}
              {m.reply_draft && <Badge tone="info">reply {m.reply_draft.status.replace(/_/g, " ")}</Badge>}
            </span>
          </span>
        </button>
        {isOpen && (
          <div className="msg-body">
            {suspicious && <Notice tone="warn"><span><strong>Instruction-like content.</strong> This message tries to instruct the system. It was treated as data, nothing was executed, and AI reply drafting is blocked.</span></Notice>}
            <p className="untrusted-label">Original message · untrusted content · from {m.from_email}</p>
            <div className="untrusted">{m.body}</div>
            {m.triage_source && <p className="small muted" style={{ marginTop: 6 }}>Sorted by {m.triage_source === "live" ? "the live LLM" : "replay (synthetic keyword rules, not an LLM)"} · provisional labels.</p>}
            <div className="row" style={{ marginTop: 10 }}>
              {m.application ? (
                <>
                  <span className="small">Linked to <Link to={`/hr/candidates?open=${m.application.candidate_user_id}`}>{m.application.candidate_name}</Link>'s application for {m.application.job_title}.</span>
                  {m.status === "open" && !m.reply_draft && (
                    <>
                      <button className="btn btn-primary btn-small" disabled={suspicious} onClick={() => draft(m.id, "ai")} title={suspicious ? "Blocked for suspicious messages" : undefined}>Draft reply with AI</button>
                      <button className="btn btn-small" onClick={() => draft(m.id, "template")}>Draft from template</button>
                    </>
                  )}
                  {m.reply_draft && !d && <button className="btn btn-small" onClick={() => refreshDraft(m.id, m.reply_draft.id)}>Show reply draft</button>}
                </>
              ) : (
                <span className="small muted">Not linked to an application - no candidate file to ground a reply in. Answer personally if needed.</span>
              )}
              {m.status === "open" ? <button className="btn btn-ghost btn-small" onClick={() => action(m.id, "archive")}>Archive</button>
                : <button className="btn btn-ghost btn-small" onClick={() => action(m.id, "reopen")}>Reopen</button>}
            </div>
            {d && <div style={{ marginTop: 12 }}><DraftCard d={d.draft} tz={tz ?? "UTC"} sources={d.sources} onChange={() => refreshDraft(m.id, d.draft.id)} /></div>}
          </div>
        )}
      </article>
    );
  }

  return (
    <div className="page medium">
      <div className="page-head">
        <div>
          <h1>Inbox brief</h1>
          <p className="muted">The assistant sorts the HR mailbox by type and urgency and flags what needs a person. Replies are drafted from the candidate's own file only, sent to their verified address, and only after you approve the exact text.</p>
        </div>
        {tab === "open" && (data?.untriaged ?? 0) > 0 && !confirm && <button className="btn btn-primary" onClick={() => setConfirm(true)}>Prepare brief ({data.untriaged} unsorted)</button>}
      </div>
      {confirm && (
        <div className="confirm">
          <span>Sort <strong>{data.untriaged}</strong> unsorted message(s) with AI mode <strong>{status?.ai_mode === "live" ? `LIVE (${status?.model_id})` : "REPLAY (synthetic, not an LLM)"}</strong>. This stores provisional labels and summaries only - nothing is answered, forwarded or sent.</span>
          <span className="row"><button className="btn btn-primary" disabled={busy} onClick={brief}>{busy ? "Sorting…" : "Sort messages"}</button><button className="btn" onClick={() => setConfirm(false)}>Cancel</button></span>
        </div>
      )}
      {msg && <Notice tone="good"><span>{msg}</span></Notice>}
      <ErrorBox error={error} />
      <div className="tabs" role="tablist">
        {(["open", "replied", "archived"] as const).map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>)}
      </div>
      {!data && <SkeletonRows rows={5} cols={3} />}
      {data && (
        <>
          <div className="brief-edition">
            <span>{today}</span>
            <span>{items.length} message(s) · {groups.needs.length} need a person · {groups.fyi.length} FYI{groups.unsorted.length ? ` · ${groups.unsorted.length} unsorted` : ""}</span>
            {sources.size > 0 && <span>{[...sources].map((s) => (s === "live" ? "live LLM" : "replay · synthetic")).join(" + ")}</span>}
          </div>
          {items.length === 0 && <Empty title={tab === "open" ? "Inbox zero" : `Nothing ${tab}`} icon="mail" />}
          {groups.needs.length > 0 && <section className="brief-section"><h2>Needs a person</h2>{groups.needs.map(renderMessage)}</section>}
          {groups.unsorted.length > 0 && <section className="brief-section"><h2>Not sorted yet</h2>{groups.unsorted.map(renderMessage)}</section>}
          {groups.fyi.length > 0 && <section className="brief-section"><h2>For information · low priority</h2>{groups.fyi.map(renderMessage)}</section>}
        </>
      )}
    </div>
  );
}
