import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, fmt } from "../../api";
import { useAuth } from "../../auth";
import { Badge, Empty, ErrorBox, Loading, Notice, Stat, StateBadge } from "../../components/ui";
import { Icon } from "../../components/Icon";

type Tab = "overview" | "users" | "audit" | "approvals";

export function SupervisorPage() {
  const [tab, setTab] = useState<Tab>("overview");
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Supervisor administration</h1>
          <p className="muted">Accounts, job assignments, AI mode, workflow status and the audit trail. Supervisor role is not a standing approval for AI actions.</p>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {(["overview", "users", "approvals", "audit"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      {tab === "overview" && <Overview />}
      {tab === "users" && <Users />}
      {tab === "approvals" && <ApprovalLog />}
      {tab === "audit" && <Audit />}
    </div>
  );
}

function Overview() {
  const { refresh } = useAuth();
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api("/api/supervisor/overview").then(setD).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  async function setMode(mode: string) {
    if (!confirm(`Switch AI mode to ${mode.toUpperCase()}? New analysis runs will use it; running runs keep their authorized mode.`)) return;
    try {
      await api("/api/supervisor/ai-mode", { body: { mode } });
      load();
      await refresh();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  if (!d) return error ? <ErrorBox error={error} onRetry={load} /> : <Loading />;
  return (
    <>
      <ErrorBox error={error} />
      <div className="card">
        <h2>AI mode <StateBadge state={d.ai_mode} label={d.ai_mode} /></h2>
        <p className="small">
          <strong>Live</strong>: real free-tier Gemini calls, real usage metadata, bounded by RPM and a daily call budget ({d.live_calls_today}/{d.daily_budget} today).{" "}
          <strong>Replay</strong>: synthetic deterministic adapter for offline demos - clearly labelled, never presented as an LLM result. A live failure never switches to replay by itself.
        </p>
        {!d.live_configured && <Notice tone="warn">GEMINI_API_KEY is not configured on the server - live mode is unavailable.</Notice>}
        <div className="row">
          <button className="btn" disabled={d.ai_mode === "replay"} onClick={() => setMode("replay")}>Switch to replay</button>
          <button className="btn btn-primary" disabled={d.ai_mode === "live" || !d.live_configured} title={!d.live_configured ? "No API key configured" : undefined} onClick={() => setMode("live")}>Switch to live</button>
        </div>
      </div>
      <div className="card">
        <h2>Workflow status</h2>
        <div className="stats" style={{ marginBottom: 12 }}>
          {Object.entries(d.users).map(([role, n]) => <Stat key={role} label={`${role} accounts`} value={n as number} />)}
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Job</th><th>Applications</th><th>Rubric / weights</th><th>Last run</th><th>Shortlist</th><th>Emails</th><th>Bookings</th><th>Interviews</th></tr></thead>
            <tbody>
              {d.jobs.map((j: any) => (
                <tr key={j.id}>
                  <td><strong>{j.title}</strong> <StateBadge state={j.status} /></td>
                  <td>{j.applications}</td>
                  <td>r{j.rubric_revision ?? "-"} / r{j.weights_revision ?? "-"}</td>
                  <td>{j.last_run ? <><StateBadge state={j.last_run.status} /> <Badge tone={j.last_run.mode === "live" ? "ai" : "neutral"}>{j.last_run.mode}</Badge></> : "-"}</td>
                  <td>{j.shortlist.approved_revision ? `r${j.shortlist.approved_revision} · ${j.shortlist.members}` : "none"} {j.shortlist.latest_status === "draft" && <Badge tone="warn">draft pending</Badge>}</td>
                  <td className="small">{Object.entries(j.emails).map(([k, v]) => `${k.replace("_", " ")}: ${v}`).join(", ") || "-"}</td>
                  <td className="small">{Object.entries(j.bookings).map(([k, v]) => `${k}: ${v}`).join(", ") || "-"}</td>
                  <td>{j.interviews}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function Users() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<any[] | null>(null);
  const [jobs, setJobs] = useState<any[]>([]);
  const [roleFilter, setRoleFilter] = useState("staff");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [form, setForm] = useState({ full_name: "", email: "", password: "", role: "recruiter" });
  const load = useCallback(() => {
    Promise.all([api("/api/supervisor/users"), api("/api/hr/jobs")])
      .then(([u, j]) => {
        setUsers(u.items);
        setJobs(j.items);
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  async function call(fn: () => Promise<any>, ok: string) {
    setError(null);
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  async function create(e: FormEvent) {
    e.preventDefault();
    await call(() => api("/api/supervisor/users", { body: form }), `Account created for ${form.email}.`);
    setForm({ full_name: "", email: "", password: "", role: "recruiter" });
  }
  const shown = users?.filter((u) => (roleFilter === "staff" ? u.role !== "candidate" : u.role === roleFilter)) ?? [];
  return (
    <>
      {msg && <Notice tone="good">{msg}</Notice>}
      <ErrorBox error={error} />
      <div className="card">
        <h2>Create staff account</h2>
        <form className="row" onSubmit={create} style={{ alignItems: "flex-end" }}>
          <div className="field"><label htmlFor="un">Full name</label><input id="un" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
          <div className="field"><label htmlFor="ue">Email</label><input id="ue" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
          <div className="field"><label htmlFor="up">Initial password (min 12)</label><input id="up" type="password" minLength={12} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" /></div>
          <div className="field"><label htmlFor="ur">Role</label>
            <select id="ur" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option value="recruiter">Recruiter</option><option value="supervisor">Supervisor</option></select>
          </div>
          <button className="btn btn-primary" style={{ marginBottom: 12 }}>Create</button>
        </form>
      </div>
      <div className="card">
        <div className="spread">
          <h2>Accounts</h2>
          <select aria-label="Filter accounts" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} style={{ width: 180 }}>
            <option value="staff">Staff</option>
            <option value="candidate">Candidates</option>
          </select>
        </div>
        {!users && <Loading />}
        {users && shown.length === 0 && <Empty title="No accounts" />}
        {shown.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Role</th><th>Status</th><th>Assigned jobs</th><th>Actions</th></tr></thead>
              <tbody>
                {shown.map((u) => (
                  <tr key={u.id}>
                    <td><strong>{u.full_name}</strong><div className="small muted">{u.email}</div></td>
                    <td>{u.role}</td>
                    <td>{u.is_active ? <Badge tone="good">active</Badge> : <Badge>deactivated</Badge>}</td>
                    <td className="small">
                      {u.role === "candidate" ? "-" : (
                        <>
                          {u.jobs.map((j: any) => (
                            <span key={j.id} className="row">
                              {j.title}
                              <button className="btn btn-ghost btn-small" aria-label={`Unassign ${j.title}`} onClick={() => call(() => api(`/api/supervisor/assignments?user_id=${u.id}&job_id=${j.id}`, { method: "DELETE" }), "Assignment removed.")}><Icon name="close" /></button>
                            </span>
                          ))}
                          <select aria-label={`Assign job to ${u.full_name}`} value="" onChange={(e) => e.target.value && call(() => api("/api/supervisor/assignments", { body: { user_id: u.id, job_id: e.target.value } }), "Assignment added.")}>
                            <option value="">+ assign job…</option>
                            {jobs.filter((j) => !u.jobs.some((x: any) => x.id === j.id)).map((j) => <option key={j.id} value={j.id}>{j.title}</option>)}
                          </select>
                        </>
                      )}
                    </td>
                    <td>
                      {u.id !== me?.id && (
                        <div className="row">
                          {u.role !== "candidate" && (
                            <button className="btn btn-small" onClick={() => confirm(`Change ${u.full_name} to ${u.role === "recruiter" ? "supervisor" : "recruiter"}?`) && call(() => api(`/api/supervisor/users/${u.id}`, { method: "PATCH", body: { role: u.role === "recruiter" ? "supervisor" : "recruiter" } }), "Role changed.")}>
                              Make {u.role === "recruiter" ? "supervisor" : "recruiter"}
                            </button>
                          )}
                          <button className="btn btn-small" onClick={() => call(() => api(`/api/supervisor/users/${u.id}`, { method: "PATCH", body: { is_active: !u.is_active } }), u.is_active ? "Deactivated; sessions revoked." : "Reactivated.")}>
                            {u.is_active ? "Deactivate" : "Reactivate"}
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

function ApprovalLog() {
  const [items, setItems] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api("/api/supervisor/approvals").then((r) => setItems(r.items)).catch((e) => setError(e.message));
  }, []);
  if (!items) return error ? <ErrorBox error={error} /> : <Loading />;
  return (
    <div className="card">
      <h2>Recorded human approvals</h2>
      <p className="small muted">Generated server-side at the moment of approval: approver, role, target, revision and content digest.</p>
      {items.length === 0 && <Empty title="No approvals yet" />}
      <div className="table-wrap">
        <table>
          <thead><tr><th>When</th><th>Action</th><th>Approver</th><th>Target</th><th>Digest</th></tr></thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td className="small">{fmt.dateTime(a.created_at)}</td>
                <td>{a.action.replace(/_/g, " ")}</td>
                <td className="small">{a.approver} ({a.approver_role})</td>
                <td className="small mono">{a.target_type}:{a.target_id.slice(0, 8)} r{a.target_revision ?? "-"}</td>
                <td className="mono">{a.digest.slice(0, 12)}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Audit() {
  const [data, setData] = useState<any>(null);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api(`/api/supervisor/audit?page=${page}&page_size=50${action ? `&action=${encodeURIComponent(action)}` : ""}`).then(setData).catch((e) => setError(e.message));
  }, [page, action]);
  return (
    <div className="card">
      <div className="spread">
        <h2>Audit timeline</h2>
        <select aria-label="Filter by action" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} style={{ width: 220 }}>
          <option value="">All events</option>
          {["analysis", "shortlist", "email", "booking", "account", "auth", "rubric", "weights", "calendar", "application", "system", "job"].map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>
      <p className="small muted">Application audit trail (append-only by convention). It is not a cryptographically tamper-proof log. CV text, email bodies, passwords and tokens are never written here.</p>
      <ErrorBox error={error} />
      {!data && <Loading />}
      {data && (
        <>
          <ul className="timeline">
            {data.items.map((e: any) => (
              <li key={e.id}>
                <div className="spread">
                  <span>
                    <strong>{e.action}</strong> <span className="muted">by {e.actor} ({e.actor_role})</span> {e.outcome !== "ok" && <Badge tone="warn">{e.outcome}</Badge>}
                  </span>
                  <span className="small muted">{fmt.dateTime(e.at)}</span>
                </div>
                <div className="small mono muted">
                  {e.target_type}:{(e.target_id ?? "-").slice(0, 10)} {e.revision !== null && `r${e.revision}`} {e.digest && `#${e.digest.slice(0, 10)}`} {Object.keys(e.details ?? {}).length > 0 && JSON.stringify(e.details)}
                </div>
              </li>
            ))}
          </ul>
          <div className="row">
            <button className="btn btn-small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer</button>
            <span className="small">Page {page} · {data.total} events</span>
            <button className="btn btn-small" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>Older</button>
          </div>
        </>
      )}
    </div>
  );
}
