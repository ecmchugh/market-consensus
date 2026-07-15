import type { ConsensusDay, HistoryPoint } from "./types";

/**
 * Base URL for the FastAPI backend.
 * - Dev: unset → "/api", which Vite proxies to localhost:8000 (see vite.config.ts).
 * - Prod: set VITE_API_BASE to the deployed API origin.
 */
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "/api";

/** When set, skip the network entirely and use bundled sample data. */
export const FORCE_SAMPLE = Boolean(import.meta.env.VITE_USE_SAMPLE);

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new ApiError(res.status, `${path} → ${res.status}`);
  return (await res.json()) as T;
}

export function fetchLatest(signal?: AbortSignal): Promise<ConsensusDay> {
  return getJSON<ConsensusDay>("/consensus/latest", signal);
}

export function fetchHistory(days = 30, signal?: AbortSignal): Promise<HistoryPoint[]> {
  return getJSON<HistoryPoint[]>(`/consensus/history?days=${days}`, signal);
}

export { ApiError };
