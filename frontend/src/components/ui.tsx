import { useEffect, useRef, type ReactNode } from "react";

export function Badge({ tone = "neutral", children, title }: { tone?: "neutral" | "good" | "warn" | "bad" | "info" | "ai"; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

const STATE_TONES: Record<string, "neutral" | "good" | "warn" | "bad" | "info" | "ai"> = {
  ok: "good", parsed: "good", provisional: "info", needs_review: "warn", invalid: "bad", review_required: "warn",
  draft: "neutral", approved_queued: "info", sending: "info", sent: "good", failed: "bad", delivery_unknown: "warn",
  rejected: "neutral", requested: "warn", confirmed: "good", declined: "neutral", expired: "neutral", cancelled: "neutral",
  available: "good", held: "warn", booked: "info", queued: "info", running: "info", completed: "good",
  completed_with_review: "warn", quota_paused: "warn", human_approved: "good", superseded: "neutral",
  not_evaluated: "neutral", published: "good", closed: "neutral", live: "ai", replay: "neutral",
};

export function StateBadge({ state, label }: { state: string; label?: string }) {
  return <Badge tone={STATE_TONES[state] ?? "neutral"}>{label ?? state.replace(/_/g, " ")}</Badge>;
}

export function ErrorBox({ error, onRetry }: { error: string | null | undefined; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="alert alert-bad" role="alert">
      <span>{error}</span>
      {onRetry && (
        <button className="btn btn-small" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "good"; children: ReactNode }) {
  return <div className={`alert alert-${tone}`}>{children}</div>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="muted loading" aria-live="polite">
      <span className="spinner" aria-hidden /> {label}
    </p>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children && <div className="muted">{children}</div>}
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
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close panel">
            ✕
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

export function ScoreBar({ lower, upper }: { lower: number | null; upper: number | null }) {
  if (lower === null || upper === null) return <span className="muted">-</span>;
  return (
    <div className="scorebar" role="img" aria-label={`Evidence score ${lower.toFixed(1)}, possible up to ${upper.toFixed(1)}`}>
      <div className="scorebar-range" style={{ left: `${lower}%`, width: `${Math.max(0, upper - lower)}%` }} />
      <div className="scorebar-fill" style={{ width: `${lower}%` }} />
    </div>
  );
}
