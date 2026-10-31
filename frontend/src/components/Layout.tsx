import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { PRODUCT_NAME } from "../config";

function ModeBanner() {
  const { status, user } = useAuth();
  if (!status) return null;
  const staff = user && user.role !== "candidate";
  return (
    <div className="banner" role="note">
      <span>
        <strong>Fictional hackathon data only.</strong> Do not upload real personal information.
      </span>
      {staff && (
        <span className={`mode mode-${status.ai_mode}`} title="Changed only by an explicit supervisor action">
          AI mode: <strong>{status.ai_mode === "live" ? `LIVE · ${status.model_id}` : "REPLAY · synthetic, not an LLM"}</strong>
          {status.ai_mode === "live" && status.daily_budget !== undefined && (
            <> · {status.live_calls_today}/{status.daily_budget} calls today</>
          )}
        </span>
      )}
    </div>
  );
}

export default function Layout({ area }: { area: "public" | "hr" | "supervisor" }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const staff = user && user.role !== "candidate";
  const links =
    area === "public"
      ? [
          { to: "/jobs", label: "Open positions" },
          ...(user?.role === "candidate" ? [{ to: "/candidate", label: "My applications" }] : []),
        ]
      : [
          { to: "/hr", label: "Dashboard", end: true },
          { to: "/hr/calendar", label: "Calendar" },
          { to: "/hr/approvals", label: "Approvals" },
          ...(user?.role === "supervisor" ? [{ to: "/supervisor", label: "Supervisor" }] : []),
        ];
  return (
    <div className={`app app-${area}`}>
      <a href="#main" className="skip">
        Skip to content
      </a>
      <ModeBanner />
      <header className="topbar">
        <NavLink to={area === "public" ? "/jobs" : "/hr"} className="brand">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
            <circle cx="13" cy="13" r="8" fill="none" stroke="currentColor" strokeWidth="3" />
            <path d="M19 19l8 8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          </svg>
          {PRODUCT_NAME}
          {area !== "public" && <span className="brand-tag">{area === "hr" ? "HR" : "Admin"}</span>}
        </NavLink>
        <nav aria-label="Main">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={"end" in l ? l.end : false}>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="userbox">
          {user ? (
            <>
              <span className="muted small" title={user.email}>
                {user.full_name} · {user.role}
              </span>
              <button
                className="btn btn-small"
                onClick={async () => {
                  await logout();
                  nav(staff ? "/hr/login" : "/jobs");
                }}
              >
                Log out
              </button>
            </>
          ) : area === "public" ? (
            <>
              <NavLink to="/login" className="btn btn-small">
                Log in
              </NavLink>
              <NavLink to="/register" className="btn btn-small btn-primary">
                Create account
              </NavLink>
            </>
          ) : null}
        </div>
      </header>
      <main id="main">
        <Outlet />
      </main>
      <footer className="footer muted small">
        {PRODUCT_NAME} prototype · The agent executes, the human decides about people. · All people, companies and CVs are fictional.
      </footer>
    </div>
  );
}
