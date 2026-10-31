import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../api";
import { useAuth } from "../../auth";
import { Empty, ErrorBox, Loading, Notice } from "../../components/ui";

interface Job {
  id: string;
  slug: string;
  title: string;
  location: string;
  employment_type: string;
  summary: string;
  description: string;
}

export function JobsPage() {
  const { status } = useAuth();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => {
    setError(null);
    api("/api/jobs").then((r) => setJobs(r.items)).catch((e) => setError(e.message));
  };
  useEffect(load, []);
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Careers at {status?.company_name ?? "our company"}</h1>
          <p className="muted">Open positions. Apply with a PDF CV after creating a candidate account.</p>
        </div>
      </div>
      <ErrorBox error={error} onRetry={load} />
      {!jobs && !error && <Loading />}
      {jobs && jobs.length === 0 && <Empty title="No open positions right now" />}
      <div className="grid grid-3">
        {jobs?.map((j) => (
          <Link key={j.id} to={`/jobs/${j.slug}`} className="card job-card">
            <h2>{j.title}</h2>
            <div className="muted small">
              {j.location} · {j.employment_type}
            </div>
            <p>{j.summary}</p>
            <span className="small">View details →</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function JobDetailPage() {
  const { slug } = useParams();
  const { user, status } = useAuth();
  const nav = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    api(`/api/jobs/${slug}`).then(setJob).catch((e) => setError(e.message));
  }, [slug]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!job || !file) return;
    setSubmitError(null);
    if (!file.name.toLowerCase().endsWith(".pdf")) return setSubmitError("Please choose a .pdf file");
    if (status && file.size > status.max_upload_mb * 1024 * 1024) return setSubmitError(`The file is larger than ${status.max_upload_mb} MB`);
    const form = new FormData();
    form.append("file", file);
    form.append("storage_notice_ack", String(ack));
    setBusy(true);
    try {
      const r = await api(`/api/jobs/${job.id}/applications`, { form });
      nav(`/candidate/applications/${r.id}?submitted=1`);
    } catch (err) {
      setSubmitError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="page"><ErrorBox error={error} /></div>;
  if (!job) return <div className="page"><Loading /></div>;
  return (
    <div className="page medium">
      <p><Link to="/jobs">← All positions</Link></p>
      <div className="card">
        <h1>{job.title}</h1>
        <p className="muted">{job.location} · {job.employment_type}</p>
        <p><strong>{job.summary}</strong></p>
        {job.description.split("\n").map((p, i) => (p.trim() ? <p key={i}>{p}</p> : null))}
      </div>
      <div className="card" id="apply">
        <h2>Apply</h2>
        {!user && (
          <>
            <p>Applying requires a candidate account so you can follow your application and book interviews securely.</p>
            <div className="row">
              <Link className="btn btn-primary" to={`/register?next=/jobs/${job.slug}`}>Create account</Link>
              <Link className="btn" to={`/login?next=/jobs/${job.slug}`}>Log in</Link>
            </div>
          </>
        )}
        {user && user.role !== "candidate" && <Notice tone="warn">Staff accounts cannot apply. Log in with a candidate account.</Notice>}
        {user?.role === "candidate" && (
          <form onSubmit={submit}>
            <div className="field">
              <label htmlFor="cv">CV (PDF, max {status?.max_upload_mb ?? 5} MB, {status?.max_pdf_pages ?? 10} pages)</label>
              <input id="cv" type="file" accept="application/pdf,.pdf" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              <span className="hint">
                Invitations are sent to the email address written in your CV. It should match your account email ({user.email}).
              </span>
            </div>
            <label className="check">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              <span>
                I confirm this CV contains <strong>fictional demo data only</strong>. I understand the file is stored privately for this
                application, reviewed by recruiters, and may be analysed by an AI assistant whose output is provisional and reviewed by a
                human. No decision about me is made automatically.
              </span>
            </label>
            <ErrorBox error={submitError} />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn btn-primary" disabled={!file || !ack || busy} title={!ack ? "Confirm the notice first" : undefined}>
                {busy ? "Submitting…" : "Submit application"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function nextPath(sp: URLSearchParams, fallback: string) {
  const n = sp.get("next");
  return n && n.startsWith("/") && !n.startsWith("//") ? n : fallback;
}

export function LoginPage({ portal }: { portal: "candidate" | "staff" }) {
  const { login } = useAuth();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const u = await login(email, password, portal);
      nav(nextPath(sp, u.role === "candidate" ? "/candidate" : u.role === "supervisor" ? "/supervisor" : "/hr"), { replace: true });
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page narrow">
      <div className="card">
        <h1>{portal === "staff" ? "HR & supervisor sign in" : "Candidate sign in"}</h1>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <ErrorBox error={error} />
          <button className="btn btn-primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        {portal === "candidate" ? (
          <p className="small">No account yet? <Link to={`/register${sp.get("next") ? `?next=${encodeURIComponent(sp.get("next")!)}` : ""}`}>Create one</Link>. Staff: <Link to="/hr/login">HR sign in</Link>.</p>
        ) : (
          <p className="small muted">Staff accounts are created by a supervisor. Candidates: <Link to="/login">candidate sign in</Link>.</p>
        )}
      </div>
    </div>
  );
}

export function RegisterPage() {
  const { refresh } = useAuth();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [ack, setAck] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/register", { body: { ...form, fictional_data_ack: ack } });
      await refresh();
      nav(nextPath(sp, "/candidate"), { replace: true });
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page narrow">
      <div className="card">
        <h1>Create a candidate account</h1>
        <Notice tone="warn">Demo: use a fictional name and an address on a reserved domain, e.g. <span className="mono">jane.doe@example.test</span>. Email ownership is <strong>not</strong> verified in this prototype.</Notice>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="name">Full name</label>
            <input id="name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required minLength={2} />
          </div>
          <div className="field">
            <label htmlFor="remail">Email</label>
            <input id="remail" type="email" autoComplete="username" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
          </div>
          <div className="field">
            <label htmlFor="rpw">Password</label>
            <input id="rpw" type="password" autoComplete="new-password" minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            <span className="hint">At least 10 characters.</span>
          </div>
          <label className="check">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            <span>I will only use fictional data in this hackathon demo.</span>
          </label>
          <ErrorBox error={error} />
          <button className="btn btn-primary" disabled={busy || !ack} style={{ marginTop: 12 }}>{busy ? "Creating…" : "Create account"}</button>
        </form>
      </div>
    </div>
  );
}
