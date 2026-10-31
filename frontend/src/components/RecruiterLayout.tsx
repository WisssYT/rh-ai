import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { PRODUCT_NAME } from "../config";
import { BrandMark, Icon } from "./Icon";

interface JobLink {
  id: string;
  title: string;
  status: string;
  applications: number;
}

export default function RecruiterLayout() {
  const { user, status, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [jobs, setJobs] = useState<JobLink[]>([]);
  const [pending, setPending] = useState<number | null>(null);

  // Refresh sidebar context on navigation (cheap; keeps counts honest after actions).
  useEffect(() => {
    if (!user || user.role === "candidate") return;
    api("/api/hr/jobs").then((r) => setJobs(r.items)).catch(() => setJobs([]));
    api("/api/hr/approvals")
      .then((r) => setPending(r.email_drafts.filter((d: any) => d.status === "draft").length + r.booking_requests.length + r.shortlist_drafts.length))
      .catch(() => setPending(null));
  }, [user, loc.pathname]);

  return (
    <div className="rx">
      <a href="#main" className="skip">Skip to content</a>
      <aside className="rx-side" aria-label="Recruiting navigation">
        <NavLink to="/hr" className="rx-brand">
          <BrandMark size={20} />
          <span>{PRODUCT_NAME}</span>
        </NavLink>
        <nav>
          <div className="rx-nav-group">
            <NavLink to="/hr" end><Icon name="grid" />Overview</NavLink>
            <NavLink to="/hr/approvals">
              <Icon name="inbox" />Approvals
              {pending ? <span className="rx-count" aria-label={`${pending} waiting`}>{pending}</span> : null}
            </NavLink>
            <NavLink to="/hr/calendar"><Icon name="calendar" />Calendar</NavLink>
          </div>
          <div className="rx-nav-group">
            <div className="rx-nav-label">Jobs</div>
            {jobs.length === 0 && <span className="rx-nav-empty">No assigned jobs</span>}
            {jobs.map((j) => (
              <NavLink key={j.id} to={`/hr/jobs/${j.id}/applications`} className={() => (loc.pathname.startsWith(`/hr/jobs/${j.id}`) ? "active" : "")}>
                <span className={`rx-dot rx-dot-${j.status}`} aria-hidden />
                <span className="rx-job-title" title={j.title}>{j.title}</span>
                <span className="rx-job-n">{j.applications}</span>
              </NavLink>
            ))}
          </div>
          {user?.role === "supervisor" && (
            <div className="rx-nav-group">
              <div className="rx-nav-label">Administration</div>
              <NavLink to="/supervisor"><Icon name="shield" />Supervisor</NavLink>
            </div>
          )}
        </nav>
        <div className="rx-side-foot">
          <div className="rx-me">
            <strong>{user?.full_name}</strong>
            <span>{user?.role}</span>
          </div>
          <button
            className="btn btn-small"
            onClick={async () => {
              await logout();
              nav("/hr/login");
            }}
          >
            Log out
          </button>
        </div>
      </aside>
      <div className="rx-main">
        {status && (
          <div className="rx-topbar" role="note">
            <span className={`rx-mode rx-mode-${status.ai_mode}`} title="Changed only by an explicit supervisor action">
              AI {status.ai_mode === "live" ? <>live · <span className="mono">{status.model_id}</span></> : "replay · synthetic output, not an LLM"}
            </span>
            {status.ai_mode === "live" && status.daily_budget !== undefined && (
              <span className="mono muted">{status.live_calls_today}/{status.daily_budget} calls today</span>
            )}
            <span className="muted small">Times in {status.timezone}</span>
          </div>
        )}
        <main id="main" className="rx-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
