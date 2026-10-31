import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { PRODUCT_NAME } from "../config";
import { BrandMark } from "./Icon";

export default function CandidateLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const candidate = user?.role === "candidate";
  return (
    <div className="cx">
      <a href="#main" className="skip">Skip to content</a>
      <header className="cx-header">
        <div className="cx-wrap">
          <NavLink to="/jobs" className="cx-brand" aria-label={`${PRODUCT_NAME} - open roles`}>
            <BrandMark />
            {PRODUCT_NAME}
          </NavLink>
          <nav className="cx-nav" aria-label="Main">
            <NavLink to="/jobs" end>Open roles</NavLink>
            {candidate && <NavLink to="/candidate" end>Applications</NavLink>}
            {candidate && <NavLink to="/candidate/profile">Profile</NavLink>}
          </nav>
          <div className="cx-user">
            {user ? (
              <>
                <span className="who" title={user.email}>{user.full_name}</span>
                <button
                  className="btn btn-small"
                  onClick={async () => {
                    await logout();
                    nav("/jobs");
                  }}
                >
                  Log out
                </button>
              </>
            ) : (
              <>
                <NavLink to="/login" className="btn btn-small btn-ghost">Log in</NavLink>
                <NavLink to="/register" className="btn btn-small btn-primary">Create account</NavLink>
              </>
            )}
          </div>
        </div>
      </header>
      <main id="main">
        {/* keyed wrapper -> a short, transform/opacity-only entrance on route change */}
        <div className="cx-route" key={loc.pathname}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
