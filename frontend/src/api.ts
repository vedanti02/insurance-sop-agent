export type TraceEntry = { turn: number; kind: string; data: Record<string, any> };
export type State = Record<string, any> & { phase: string; trace: TraceEntry[]; history: { role: string; text: string; turn: number }[] };

const KEY = "sop_api_key";
export const getKey = () => sessionStorage.getItem(KEY) || "";
export const setKey = (k: string) => (k ? sessionStorage.setItem(KEY, k) : sessionStorage.removeItem(KEY));

async function req(path: string, init: RequestInit = {}) {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const k = getKey();
  if (k) headers["X-API-Key"] = k;
  const r = await fetch(path, { ...init, headers });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export type Vertical = { name: string; domain: string; scripts: Record<string, string> };

export const api = {
  health: () => req("/api/health"),
  verticals: (): Promise<{ verticals: Vertical[]; default: string }> => req("/api/verticals"),
  create: (opts: { consent_scenario?: string; vertical?: string; demo_today?: string }) =>
    req("/api/sessions", { method: "POST", body: JSON.stringify(opts) }),
  get: (id: string) => req(`/api/sessions/${id}`),
  send: (id: string, text: string) => req(`/api/sessions/${id}/messages`, { method: "POST", body: JSON.stringify({ text }) }),
  outbox: () => req("/api/outbox"),
};
