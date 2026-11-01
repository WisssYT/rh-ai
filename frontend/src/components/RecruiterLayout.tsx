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
  const [counts, setCounts] = useState<{ approvals: number; review: number; inbox: number; followups: number } | null>(null);

  // Refresh sidebar context on navigation (cheap; keeps counts honest after actions).
  useEffect(() => {
    if (!user || user.role === "candidate") return;
    api("/api/hr/jobs").then((r) => setJobs(r.items)).catch(() => setJobs([]));
    api("/api/hr/nav-counts").then(setCounts).catch(() => setCounts(null));
  }, [user, loc.pathname]);

  const count = (n: number | undefined, label: string, quiet = true) =>
    n ? <span className={`rx-count${quiet ? " rx-count-quiet" : ""}`} aria-label={`${n} ${label}`}>{n}</span> : null;

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
            <NavLink to="/hr/dashboard"><Icon name="chart" />Dashboard</NavLink>
            <NavLink to="/hr" end><Icon name="grid" />Overview</NavLink>
            <NavLink to="/hr/candidates"><Icon name="people" />Candidates</NavLink>
          </div>
          <div className="rx-nav-group">
            <div className="rx-nav-label">Act</div>
            <NavLink to="/hr/approvals"><Icon name="inbox" />Approvals{count(counts?.approvals, "waiting", false)}</NavLink>
            <NavLink to="/hr/review"><Icon name="flag" />Review queue{count(counts?.review, "open")}</NavLink>
            <NavLink to="/hr/inbox"><Icon name="mail" />Inbox brief{count(counts?.inbox, "open")}</NavLink>
            <NavLink to="/hr/followups"><Icon name="repeat" />Follow-ups{count(counts?.followups, "due")}</NavLink>
          </div>
          <div className="rx-nav-group">
            <div className="rx-nav-label">Interviews</div>
            <NavLink to="/hr/calendar"><Icon name="calendar" />Calendar</NavLink>
            <NavLink to="/hr/interviews"><Icon name="chat" />Interviews</NavLink>
          </div>
          <div className="rx-nav-group">
            <div className="rx-nav-label">Library</div>
            <NavLink to="/hr/templates"><Icon name="template" />Templates</NavLink>
            <NavLink to="/hr/reports"><Icon name="report" />Reports</NavLink>
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
