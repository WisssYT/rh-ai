import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api } from "./api";

export type Role = "candidate" | "recruiter" | "supervisor";
export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
}
export interface SystemStatus {
  product_name: string;
  company_name: string;
  ai_mode: "live" | "replay";
  timezone: string;
  max_upload_mb: number;
  max_pdf_pages: number;
  email_verification: boolean;
  live_configured?: boolean;
  model_id?: string;
  mailpit_url?: string;
  preflight?: string[];
  live_calls_today?: number;
  daily_budget?: number;
}

interface Ctx {
  user: User | null;
  status: SystemStatus | null;
  loading: boolean;
  refresh: () => Promise<void>;
  login: (email: string, password: string, portal: "candidate" | "staff") => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [me, st] = await Promise.all([api("/api/auth/me"), api("/api/system/status")]);
      setUser(me.user);
      setStatus(st);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string, portal: "candidate" | "staff") => {
      const r = await api("/api/auth/login", { body: { email, password, portal } });
      await refresh();
      return r.user as User;
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
      await refresh();
    }
  }, [refresh]);

  return <AuthContext.Provider value={{ user, status, loading, refresh, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): Ctx {
  const c = useContext(AuthContext);
  if (!c) throw new Error("AuthProvider missing");
  return c;
}

/** UX guard only - every endpoint enforces role and ownership on the server. */
export function RequireRole({ roles, children, loginPath }: { roles: Role[]; children: ReactNode; loginPath: string }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="page"><p className="muted">Loading…</p></div>;
  if (!user) return <Navigate to={`${loginPath}?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (!roles.includes(user.role))
    return (
      <div className="page narrow">
        <div className="card">
          <h1>Not available for this account</h1>
          <p>You are signed in as {user.email} ({user.role}). This area needs a {roles.join(" or ")} account.</p>
        </div>
      </div>
    );
  return <>{children}</>;
}
