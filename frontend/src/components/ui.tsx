import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";

type Tone = "neutral" | "good" | "warn" | "bad" | "info" | "ai";

export function Badge({ tone = "neutral", children, title, plain }: { tone?: Tone; children: ReactNode; title?: string; plain?: boolean }) {
  return (
    <span className={`badge badge-${tone}${plain ? " badge-plain" : ""}`} title={title}>
      {children}
    </span>
  );
}

const STATE: Record<string, [Tone, string]> = {
  ok: ["good", "ok"], parsed: ["good", "parsed"], provisional: ["info", "provisional"], needs_review: ["warn", "needs review"],
  invalid: ["bad", "invalid output"], review_required: ["warn", "review"], draft: ["neutral", "draft"],
  approved_queued: ["info", "approved · queued"], sending: ["info", "sending"], sent: ["good", "sent"], failed: ["bad", "failed"],
  delivery_unknown: ["warn", "delivery unknown"], rejected: ["neutral", "rejected"], requested: ["warn", "requested"],
  confirmed: ["good", "confirmed"], declined: ["neutral", "declined"], expired: ["neutral", "expired"], cancelled: ["neutral", "cancelled"],
  available: ["good", "free"], held: ["warn", "requested"], booked: ["info", "booked"], queued: ["info", "queued"],
  running: ["info", "running"], completed: ["good", "completed"], completed_with_review: ["warn", "completed · review"],
  quota_paused: ["warn", "paused"], human_approved: ["good", "approved"], superseded: ["neutral", "superseded"],
  not_evaluated: ["neutral", "not evaluated"], published: ["good", "published"], closed: ["neutral", "closed"],
  submitted: ["info", "submitted"], withdrawn: ["neutral", "withdrawn"], live: ["ai", "live"], replay: ["neutral", "replay"],
};

export function StateBadge({ state, label }: { state: string; label?: string }) {
  const [tone, text] = STATE[state] ?? ["neutral", state.replace(/_/g, " ")];
  return <Badge tone={tone}>{label ?? text}</Badge>;
}

export function ErrorBox({ error, onRetry }: { error: string | null | undefined; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="alert alert-bad" role="alert">
      <span>{error}</span>
      {onRetry && (
        <button className="btn btn-small" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "good"; children: ReactNode }) {
  return (
    <div className={`alert alert-${tone}`} role={tone === "good" ? "status" : undefined}>
      {children}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="muted loading" aria-live="polite">
      <span className="spinner" aria-hidden /> {label}
    </p>
  );
}

/** Table-shaped placeholder so the layout does not jump when data arrives. */
export function SkeletonRows({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="skeleton-table" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="skeleton-row" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
          {Array.from({ length: cols }, (_, c) => (
            <span key={c} className="skeleton" style={{ width: `${55 + ((r * 7 + c * 13) % 40)}%` }} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: string }) {
  return (
    <div className="empty">
      {icon && <Icon name={icon} className="empty-icon" />}
      <strong>{title}</strong>
      {children && <div className="muted small">{children}</div>}
    </div>
  );
}

export function Drawer({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <h2>{title}</h2>
          <button className="btn btn-ghost btn-small" onClick={onClose} aria-label="Close panel">
            <Icon name="close" />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

/** Solid = evidence-backed lower bound; hatched = what unknown criteria could still add. */
export function ScoreBar({ lower, upper }: { lower: number | null; upper: number | null }) {
  if (lower === null || upper === null) return <span className="muted">-</span>;
  return (
    <div className="scorebar" role="img" aria-label={`Evidence score ${lower.toFixed(1)}, possible up to ${upper.toFixed(1)}`}>
      <div className="scorebar-range" style={{ left: `${lower}%`, width: `${Math.max(0, upper - lower)}%` }} />
      <div className="scorebar-fill" style={{ width: `${lower}%` }} />
    </div>
  );
}
