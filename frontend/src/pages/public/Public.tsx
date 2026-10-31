import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../api";
import { useAuth } from "../../auth";
import { Icon } from "../../components/Icon";
import { PaperStack } from "../../components/PaperStack";
import { Empty, ErrorBox, Loading, Notice } from "../../components/ui";

interface Job {
  id: string;
  slug: string;
  title: string;
  location: string;
  employment_type: string;
  summary: string;
  description: string;
  criteria?: { label: string; description: string; required: boolean }[];
}

export function JobsPage() {
  const { status, user } = useAuth();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const heroRef = useRef<HTMLElement>(null);
  const load = () => {
    setError(null);
    api("/api/jobs").then((r) => setJobs(r.items)).catch((e) => setError(e.message));
  };
  useEffect(load, []);
  const company = status?.company_name ?? "our team";

  return (
    <>
      <section className="hero" ref={heroRef} aria-labelledby="hero-title">
        <div className="cx-wrap">
          <div>
            <p className="overline" style={{ visibility: status ? "visible" : "hidden" }}>{company} · Careers</p>
            <h1 id="hero-title">
              Your CV, read for evidence. <em>Decisions made by people.</em>
            </h1>
            <p className="lede">
              {status?.company_about ? `${status.company_about} ` : ""}
              Recruiters review every application against the criteria published with the role. An assistant points them to
              the relevant lines in your CV; nothing about you is decided automatically.
            </p>
            <div className="hero-actions">
              <a className="btn btn-primary" href="#roles">
                See open roles{jobs ? ` (${jobs.length})` : ""}
                <Icon name="arrow" />
              </a>
              {user?.role === "candidate" ? (
                <Link className="btn" to="/candidate">Your applications</Link>
              ) : (
                !user && <Link className="btn" to="/register">Create an account</Link>
              )}
            </div>
          </div>
          <PaperStack trackRef={heroRef} />
        </div>
      </section>

      <section className="cx-wrap section" id="roles" aria-labelledby="roles-title">
        <div className="section-head">
          <h2 id="roles-title">Open roles</h2>
          {jobs && <span className="count">{String(jobs.length).padStart(2, "0")} open</span>}
        </div>
        <ErrorBox error={error} onRetry={load} />
        {!jobs && !error && <div style={{ paddingTop: 20 }}><Loading label="Loading roles…" /></div>}
        {jobs?.length === 0 && <div style={{ paddingTop: 20 }}><Empty title="No open roles right now">New positions are published here first.</Empty></div>}
        <ul className="roles">
          {jobs?.map((j) => (
            <li key={j.id} className="role">
              <Link to={`/jobs/${j.slug}`}>
                <div>
                  <div className="role-title"><span>{j.title}</span></div>
                  <div className="role-summary">{j.summary}</div>
                </div>
                <div className="role-meta">
                  {j.location}
                  <br />
                  {j.employment_type}
                </div>
                <Icon name="arrow" />
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="cx-wrap section" aria-labelledby="process-title">
        <div className="process">
          <div className="process-intro">
            <p className="overline">After you apply</p>
            <h2 id="process-title">What happens to your application</h2>
            <p>Each step below is something a person at {company} does, or something you do from your account.</p>
          </div>
          <div>
            <ol className="steps">
              <li>
                <h3>You send a PDF</h3>
                <p>
                  Up to {status?.max_upload_mb ?? 5} MB and {status?.max_pdf_pages ?? 10} pages. Afterwards you can see exactly which text we
                  extracted, and replace the file if something is wrong.
                </p>
              </li>
              <li>
                <h3>A recruiter reviews it against the role's criteria</h3>
                <p>The criteria are listed on each role page. Assistant notes are provisional and cite the lines they rely on.</p>
              </li>
              <li>
                <h3>Shortlisted? You receive an invitation</h3>
                <p>A recruiter approves each email before it is sent to the address in your CV.</p>
              </li>
              <li>
                <h3>You pick an interview time</h3>
                <p>Sign in, choose a slot that suits you, and the recruiter confirms it.</p>
              </li>
            </ol>
            <p className="promise">No automated rejections. You can replace your CV or withdraw at any time from your account.</p>
          </div>
        </div>
      </section>
    </>
  );
}

const STEPS = ["Account", "CV", "Submit"];

function Tracker({ step }: { step: number }) {
  return (
    <div className="tracker" aria-label={`Step ${step + 1} of 3: ${STEPS[step]}`}>
      <span className="tracker-fill" style={{ transform: `scaleX(${step / 2})` }} aria-hidden />
      <ol>
        {STEPS.map((s, i) => (
          <li key={s} className={i < step ? "done" : i === step ? "current" : ""} aria-current={i === step ? "step" : undefined}>
            <span className="dot">{i < step && <Icon name="check" />}</span>
            {s}
          </li>
        ))}
      </ol>
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
  const [drag, setDrag] = useState(false);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    api(`/api/jobs/${slug}`).then(setJob).catch((e) => setError(e.message));
  }, [slug]);

  function pick(f: File | null | undefined) {
    setSubmitError(null);
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".pdf")) return setSubmitError("Please choose a PDF file.");
    if (status && f.size > status.max_upload_mb * 1024 * 1024) return setSubmitError(`That file is larger than ${status.max_upload_mb} MB.`);
    setFile(f);
  }
  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files?.[0]);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!job || !file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("storage_notice_ack", String(ack));
    setBusy(true);
    setSubmitError(null);
    try {
      const r = await api(`/api/jobs/${job.id}/applications`, { form });
      nav(`/candidate/applications/${r.id}?submitted=1`);
    } catch (err) {
      setSubmitError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  if (error) return <div className="cx-wrap" style={{ paddingTop: 40 }}><ErrorBox error={error} /><Link className="back" to="/jobs"><Icon name="back" />All roles</Link></div>;
  if (!job) return <div className="cx-wrap" style={{ paddingTop: 40 }}><Loading /></div>;
  const step = user?.role !== "candidate" ? 0 : !file || !ack ? 1 : 2;
  return (
    <div className="cx-wrap job-layout">
      <article>
        <Link className="back" to="/jobs"><Icon name="back" />All roles</Link>
        <header className="job-head">
          <p className="overline" style={{ marginTop: 22 }}>{job.employment_type}</p>
          <h1>{job.title}</h1>
          <p className="lede">{job.summary}</p>
          <div className="facts"><span>{job.location}</span><span>{status?.company_name}</span></div>
        </header>
        <div className="prose">
          {job.description.split("\n").map((p, i) => (p.trim() ? <p key={i}>{p}</p> : null))}
        </div>
        {job.criteria && job.criteria.length > 0 && (
          <section style={{ marginTop: 36 }} aria-labelledby="crit-title">
            <h2 id="crit-title" style={{ fontSize: "1.35rem" }}>What we assess</h2>
            <p className="muted small" style={{ marginTop: 6 }}>Recruiters review applications against these job-related criteria. Missing information is treated as unknown, never as a fail.</p>
            <ul className="criteria-list">
              {job.criteria.map((c) => (
                <li key={c.label}>
                  <div>
                    <strong style={{ fontWeight: 500 }}>{c.label}</strong>
                    {c.required && <span className="mono muted"> · essential</span>}
                    <div className="muted small">{c.description}</div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
      </article>

      <aside className="apply-panel" id="apply" aria-labelledby="apply-title">
        <h2 id="apply-title">Apply</h2>
        <Tracker step={step} />
        {!user && (
          <>
            <p className="small">You need a candidate account to apply. It's also where you follow your application and pick an interview time.</p>
            <div className="row">
              <Link className="btn btn-primary" to={`/register?next=/jobs/${job.slug}`}>Create account</Link>
              <Link className="btn" to={`/login?next=/jobs/${job.slug}`}>Log in</Link>
            </div>
          </>
        )}
        {user && user.role !== "candidate" && <Notice tone="warn"><span>Staff accounts can't apply. Log in with a candidate account.</span></Notice>}
        {user?.role === "candidate" && (
          <form onSubmit={submit}>
            <div className={`dropzone${drag ? " drag" : ""}`} onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}>
              <Icon name="upload" />
              <strong>Drop your CV here, or choose a file</strong>
              <span className="hint">PDF · max {status?.max_upload_mb ?? 5} MB · {status?.max_pdf_pages ?? 10} pages</span>
              <input id="cv" type="file" accept="application/pdf,.pdf" aria-label="CV (PDF)" onChange={(e) => pick(e.target.files?.[0])} />
            </div>
            {file && (
              <div className="file-chip">
                <Icon name="doc" />
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{file.name}</span>
                <span className="mono muted">{Math.max(1, Math.round(file.size / 1024))} KB</span>
              </div>
            )}
            <p className="hint" style={{ margin: "12px 0" }}>
              We send interview invitations to the email written in your CV, so it should match your account email ({user.email}).
            </p>
            <label className="check">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              <span>
                This CV contains only fictional demo data. I understand it is stored privately for this application and reviewed by
                recruiters, with help from an assistant whose notes are provisional.
              </span>
            </label>
            <ErrorBox error={submitError} />
            <button className="btn btn-primary" style={{ width: "100%", minHeight: 44, marginTop: 16 }} disabled={!file || !ack || busy}>
              {busy ? "Sending…" : "Submit application"}
            </button>
            {(!file || !ack) && <p className="hint" style={{ marginTop: 8, textAlign: "center" }}>{!file ? "Choose a PDF to continue." : "Confirm the notice to continue."}</p>}
          </form>
        )}
      </aside>
    </div>
  );
}

function nextPath(sp: URLSearchParams, fallback: string) {
  const n = sp.get("next");
  return n && n.startsWith("/") && !n.startsWith("//") ? n : fallback;
}

export function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fromInvite = sp.get("next")?.startsWith("/candidate/interviews/");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password, "candidate");
      nav(nextPath(sp, "/candidate"), { replace: true });
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="cx-wrap auth">
      <div className="auth-aside">
        <p className="overline">Candidate account</p>
        <h1>{fromInvite ? "Sign in to choose your interview time." : "Welcome back."}</h1>
        <p style={{ marginTop: 16 }}>
          {fromInvite
            ? "Invitation links only work for the account they were sent to - that keeps your booking private even if the email is forwarded."
            : "See where your applications stand, replace a CV, or pick an interview time."}
        </p>
      </div>
      <form onSubmit={submit} aria-label="Sign in">
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
        <p className="small" style={{ marginBottom: 0 }}>
          New here? <Link to={`/register${sp.get("next") ? `?next=${encodeURIComponent(sp.get("next")!)}` : ""}`}>Create an account</Link>
          <span className="muted"> · Staff: </span><Link to="/hr/login">HR sign in</Link>
        </p>
      </form>
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
    <div className="cx-wrap auth">
      <div className="auth-aside">
        <p className="overline">Candidate account</p>
        <h1>One account for every application.</h1>
        <p style={{ marginTop: 16 }}>
          Use the same email address that is written in your CV - interview invitations go there, and the booking link only opens for
          this account.
        </p>
        <p className="small muted">This demo accepts only fictional addresses on reserved domains, such as <span className="mono">jane.doe@example.test</span>. Email ownership is not verified.</p>
      </div>
      <form onSubmit={submit} aria-label="Create account">
        <div className="field">
          <label htmlFor="name">Full name</label>
          <input id="name" autoComplete="name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required minLength={2} />
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
          <span>I will only use fictional data in this demo.</span>
        </label>
        <ErrorBox error={error} />
        <button className="btn btn-primary" disabled={busy || !ack} style={{ marginTop: 14 }}>{busy ? "Creating…" : "Create account"}</button>
        <p className="small" style={{ marginBottom: 0 }}>Already registered? <Link to={`/login${sp.get("next") ? `?next=${encodeURIComponent(sp.get("next")!)}` : ""}`}>Sign in</Link></p>
      </form>
    </div>
  );
}

export function StaffLoginPage() {
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
      const u = await login(email, password, "staff");
      nav(nextPath(sp, u.role === "supervisor" ? "/supervisor" : "/hr"), { replace: true });
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="rx-auth">
      <div className="rx-auth-box">
        <form onSubmit={submit} aria-label="Staff sign in">
          <h1>Recruiting sign in</h1>
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
        <p className="small muted" style={{ marginTop: 14 }}>Staff accounts are created by a supervisor. Candidates sign in at <Link to="/login">the careers site</Link>.</p>
      </div>
    </div>
  );
}
