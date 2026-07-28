import type { Backtest, CorpusStats, Reading } from "./types";

/**
 * Base URL for the FastAPI backend.
 * - Dev: unset → "/api", which Vite proxies to localhost:8000 (see vite.config.ts).
 * - Prod: set VITE_API_BASE to the deployed API origin.
 */
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "/api";

/**
 * A non-2xx response from the API. `detail` carries FastAPI's message, which for the
 * two cases the UI cares about is written to be shown to the user verbatim:
 *   422 → subject has no tradeable proxy (not a market subject)
 *   404 → no reading cached yet for this subject
 * Status 0 is our own sentinel for "never reached the server".
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch (e) {
    // Let a caller-initiated abort propagate as itself — it isn't an API failure.
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Can't reach the API — is the backend running on :8000?");
  }
  if (!res.ok) {
    let detail = `${path} → ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/**
 * The one heavy endpoint: run (or return a cached) reading for any market subject.
 * Cold path is ~24s (fetch → score → embed → retrieve → synthesize → backtest);
 * a cached subject returns in milliseconds. Throws ApiError(422) for non-market input.
 */
export function querySubject(subject: string, forceRefresh = false, signal?: AbortSignal): Promise<Reading> {
  return request<Reading>("/subjects/query", {
    method: "POST",
    body: JSON.stringify({ subject, force_refresh: forceRefresh }),
    signal,
  });
}

/** Most recent cached reading. Throws ApiError(404) if the subject was never queried. */
export function fetchLatest(subject: string, signal?: AbortSignal): Promise<Reading> {
  return request<Reading>(`/subjects/${encodeURIComponent(subject)}/latest`, { signal });
}

/** Reading trend over time, oldest first. Sparse until a subject has been read repeatedly. */
export function fetchHistory(subject: string, limit = 90, signal?: AbortSignal): Promise<Reading[]> {
  return request<Reading[]>(`/subjects/${encodeURIComponent(subject)}/history?limit=${limit}`, { signal });
}

export function fetchBacktest(subject: string, signal?: AbortSignal): Promise<Backtest> {
  return request<Backtest>(`/subjects/${encodeURIComponent(subject)}/backtest`, { signal });
}

/** Corpus size — shown as a liveness/coverage stat on the landing page. */
export function fetchCorpusStats(signal?: AbortSignal): Promise<CorpusStats> {
  return request<CorpusStats>("/corpus/stats", { signal });
}
