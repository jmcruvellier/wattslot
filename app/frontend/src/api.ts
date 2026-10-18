// Accès à l'API de l'application. URL relatives : derrière l'ingress de Home Assistant,
// l'application est servie sous un préfixe variable.

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: unknown = null, // corps « detail » de FastAPI, s'il y en a un
  ) {
    super(`HTTP ${status}`);
  }
}

async function failure(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return new ApiError(response.status, body.detail ?? null);
  } catch {
    return new ApiError(response.status);
  }
}

export async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export async function putJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}
