/**
 * API client. All requests go to the same origin (`/api/v1/*`), which Next.js forwards to the
 * backend (next.config.ts rewrite, ADR-17). The session lives in an httpOnly cookie the browser
 * sends automatically; no token is ever readable by JavaScript and no secret is in this bundle.
 */

import type { ErrorDetail } from "./types";

export const API_BASE = "/api/v1";

/** Normalised error for every failed request (backend envelope, network or unexpected). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ErrorDetail[] | Record<string, unknown> | null;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: ApiError["details"] = null,
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /** Field-level messages keyed by the last path element of `loc` (e.g. "phone"). */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    if (Array.isArray(this.details)) {
      for (const d of this.details) {
        const field = d.loc?.[d.loc.length - 1];
        if (typeof field === "string" && !out[field]) out[field] = d.msg || d.type || "Invalid value";
      }
    }
    return out;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Send an Idempotency-Key. Pass a string to reuse the same key across retries. */
  idempotencyKey?: string | true;
  signal?: AbortSignal;
}

export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

export async function parseError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("x-request-id");
  try {
    const data = await response.json();
    const err = data?.error;
    if (err && typeof err.code === "string") {
      return new ApiError(response.status, err.code, err.message || "Request failed.", err.details ?? null, err.request_id ?? requestId);
    }
  } catch {
    // not JSON
  }
  return new ApiError(response.status, `HTTP_${response.status}`, "Something went wrong. Please try again.", null, requestId);
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.idempotencyKey) {
    headers["Idempotency-Key"] = options.idempotencyKey === true ? newIdempotencyKey() : options.idempotencyKey;
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") throw error;
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the server. Check your internet connection.");
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
