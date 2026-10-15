import { useCallback, useEffect, useRef, useState } from "react";

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api";
const TOKEN_KEY = "relay.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: stay signed in for this tab only */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(`${BASE}${path}`, { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  if (res.status === 401) {
    setToken(null);
    if (!location.pathname.startsWith("/login")) location.href = "/login";
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.detail ?? `Request failed (${res.status})`);
  return data as T;
}

/** Fetch on mount, expose refresh, optionally poll. */
export function useApi<T = any>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e: any) {
      if (alive.current) setError(e.message);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    refresh();
    if (!pollMs) return () => void (alive.current = false);
    const id = setInterval(refresh, pollMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [refresh, pollMs]);

  return { data, error, loading, refresh, setData };
}
