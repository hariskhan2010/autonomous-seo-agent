import "server-only";

// Server-only: this must never be imported from a Client Component. The dev-mode identity
// headers below stand in for real auth (Supabase login is the planned upgrade — see README.md);
// they're only honored by the API when ENV=dev, but keeping the fetch itself server-side means
// no auth header of any kind, dev or real, ever reaches the browser bundle.

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: string,
  ) {
    super(`API request failed (${status}): ${body}`);
  }
}

function devHeaders(): Record<string, string> {
  return {
    "x-dev-tenant": process.env.DEV_TENANT_ID ?? "",
    "x-dev-user": process.env.DEV_USER_ID ?? "",
    "x-dev-role": process.env.DEV_ROLE ?? "owner",
  };
}

async function request<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    cache: rest.cache ?? "no-store",
    headers: {
      ...devHeaders(),
      ...(json !== undefined ? { "content-type": "application/json" } : {}),
      ...rest.headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, json: unknown) => request<T>(path, { method: "POST", json }),
  patch: <T>(path: string, json: unknown) => request<T>(path, { method: "PATCH", json }),
};
