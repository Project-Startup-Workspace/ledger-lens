// Typed calls to the Ledger Lens API, through this app's server-side proxy.
import type {
  AuditLog,
  CaseSummary,
  ComplianceReport,
  CreditFile,
  Explanation,
  Jurisdiction,
  Outcome,
} from "./types";

const BASE = "/api/ll";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : response.statusText;
    throw new ApiError(response.status, detail);
  }
  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await send(path, init)).json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listCases: () => request<CaseSummary[]>("/cases"),
  demoCases: () => request<string[]>("/demo-cases"),
  openDemo: (slug: string) => request<CreditFile>(`/demo-cases/${slug}`, { method: "POST" }),
  createCase: (body: unknown) => request<CreditFile>("/cases", json(body)),
  getCase: (id: string) => request<CreditFile>(`/cases/${id}`),
  jurisdictions: () => request<Jurisdiction[]>("/jurisdictions"),
  upload: (id: string, kind: string, file: File) => {
    const form = new FormData();
    form.append("kind", kind);
    form.append("file", file);
    return request<unknown>(`/cases/${id}/evidence`, { method: "POST", body: form });
  },
  assess: (id: string) => request<CreditFile>(`/cases/${id}/assess`, { method: "POST" }),
  compliance: (id: string, jurisdiction: string) =>
    request<ComplianceReport>(`/cases/${id}/compliance?jurisdiction=${jurisdiction}`),
  explain: (id: string, language: string) =>
    request<Explanation>(`/cases/${id}/explanation`, json({ language })),
  acknowledge: (id: string) =>
    request<CreditFile>(`/cases/${id}/disclosure/acknowledge`, json({ blank_fields: [] })),
  decide: (id: string, outcome: Outcome, reason: string) =>
    request<CreditFile>(`/cases/${id}/decision`, json({ outcome, reason })),
  audit: (id: string) => request<AuditLog>(`/cases/${id}/audit`),
  /** Records the export in the audit chain, so it is a POST and runs only on a click. */
  exportAuditPack: async (id: string): Promise<Blob> =>
    (await send(`/cases/${id}/audit-pack`, { method: "POST" })).blob(),
};

export const urls = {
  evidenceFile: (id: string, evidenceId: string) =>
    `${BASE}/cases/${id}/evidence/${evidenceId}/file`,
  // The query only busts the browser cache when the language changes; the API ignores it.
  audio: (id: string, language: string) => `${BASE}/cases/${id}/explanation/audio?lang=${language}`,
  report: (id: string) => `${BASE}/cases/${id}/report`,
};
