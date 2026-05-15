const defaultBaseUrl = "http://127.0.0.1:9000";

export function getBaseUrl(): string {
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }
  return defaultBaseUrl;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  const url = `${baseUrl}${path}`;
  const headers: Record<string, string> = {};
  if (options.headers) {
    const original = options.headers as Record<string, string>;
    Object.keys(original).forEach((key) => {
      headers[key] = original[key];
    });
  }
  if (options.body && !Object.keys(headers).some((key) => key.toLowerCase() === "content-type")) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "include",
    cache: options.cache ?? "no-store",
  });
  const responseText = await response.text();
  if (!response.ok) {
    let detail: unknown = responseText;
    try {
      detail = responseText ? JSON.parse(responseText) : responseText;
    } catch {
      detail = responseText;
    }
    throw new Error(`Request failed: ${response.status} ${JSON.stringify(detail)}`);
  }
  if (!responseText) {
    return undefined as T;
  }
  return JSON.parse(responseText) as T;
}
