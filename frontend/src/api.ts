// Thin fetch wrapper. Session lives in an HttpOnly cookie set by the backend; the client never stores
// credentials or roles. Mutations send the CSRF token (double-submit cookie, bound to the session server-side).

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name.replace(/[.$?*|{}()[\]\\/+^]/g, "\\$&") + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : null;
}

let csrfPromise: Promise<void> | null = null;
async function ensureCsrf(): Promise<string> {
  let token = readCookie("td_csrf");
  if (!token) {
    csrfPromise ??= fetch("/api/auth/csrf", { credentials: "same-origin" }).then(() => undefined);
    await csrfPromise;
    csrfPromise = null;
    token = readCookie("td_csrf");
  }
  return token ?? "";
}

function messageFrom(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return fallback;
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["x-csrf-token"] = await ensureCsrf();
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "Network error - is the backend running?", null);
  }
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data?.detail ?? data;
    let msg = messageFrom(detail, `Request failed (${res.status})`);
    if (data?.errors?.length) msg += ": " + data.errors.map((e: any) => `${e.loc.slice(1).join(".")} ${e.msg}`).join("; ");
    throw new ApiError(res.status, msg, detail);
  }
  return data as T;
}

export const fmt = {
  dateTime(iso: string | null | undefined, tz?: string) {
    if (!iso) return "-";
    return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: tz }).format(new Date(iso));
  },
  time(iso: string, tz?: string) {
    return new Intl.DateTimeFormat("en-GB", { timeStyle: "short", timeZone: tz }).format(new Date(iso));
  },
  day(iso: string, tz?: string) {
    return new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "2-digit", month: "short", timeZone: tz }).format(new Date(iso));
  },
  num(n: number | null | undefined, digits = 1) {
    return n === null || n === undefined ? "-" : n.toFixed(digits);
  },
};

export function newIdempotencyKey(): string {
  const a = new Uint8Array(16);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}
