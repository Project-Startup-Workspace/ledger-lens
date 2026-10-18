// Typed calls to the Ledger Lens API, through this app's server-side proxy.
import type {
  AccessGrant,
  AuditLog,
  CaseSummary,
  ComplianceReport,
  CreditFile,
  Explanation,
  Jurisdiction,
  Me,
  Member,
  Organisation,
  OrgStatus,
  OrgType,
  Outcome,
  PlatformSettings,
  Role,
} from "./types";

const BASE = "/api/ll";

export interface NewAccount {
  email: string;
  display_name: string;
  password: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

// Set by the session provider: renews an expired sign-in, true if it did.
let renewSession: (() => Promise<boolean>) | null = null;
export function onSessionExpired(renew: (() => Promise<boolean>) | null): void {
  renewSession = renew;
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response = await fetch(`${BASE}${path}`, init);
  // A tab left open past the token's hour: renew once and retry. Bodies here are strings
  // or form data, never streams, so the request can be sent again.
  if (response.status === 401 && renewSession && (await renewSession())) {
    response = await fetch(`${BASE}${path}`, init);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    // FastAPI sends a string for refusals and a list for invalid input.
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : Array.isArray(body.detail) && body.detail[0]?.msg
          ? `${body.detail[0].loc?.at(-1) ?? "input"}: ${body.detail[0].msg}`
          : response.statusText;
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
  sendApplication: (id: string, lenderOrgId: string) =>
    request<CreditFile>(`/cases/${id}/send`, json({ lender_org_id: lenderOrgId })),
  assignReviewer: (id: string, reviewerUid: string) =>
    request<CreditFile>(`/cases/${id}/credit-review`, json({ reviewer_uid: reviewerUid })),
  ask: (id: string, addressedTo: "lender" | "business", message: string) =>
    request<CreditFile>(`/cases/${id}/requests`, json({ addressed_to: addressedTo, message })),
  answer: (id: string, requestId: string, answer: string) =>
    request<CreditFile>(`/cases/${id}/requests/${requestId}/answer`, json({ answer })),
  assignEngagement: (id: string, assigneeUid: string) =>
    request<CreditFile>(`/cases/${id}/engagements`, json({ assignee_uid: assigneeUid })),
  addFinding: (id: string, severity: "observation" | "issue", note: string) =>
    request<CreditFile>(`/cases/${id}/findings`, json({ severity, note })),
  submitFindings: (id: string) =>
    request<CreditFile>(`/cases/${id}/findings/submit`, { method: "POST" }),
  reviewEngagement: (id: string, engagementId: string, approve: boolean, note: string) =>
    request<CreditFile>(`/cases/${id}/engagements/${engagementId}/review`, json({ approve, note })),
  me: () => request<Me>("/me"),
  registerOrganisation: (name: string, type: OrgType, jurisdiction: string | null) =>
    request<Me>("/me/organisation", json({ name, type, jurisdiction })),
  setOrganisationStatus: (orgId: string, status: OrgStatus) =>
    request<Organisation>(`/organisations/${orgId}/status`, json({ status })),
  platformSettings: () => request<PlatformSettings>("/platform/settings"),
  updatePlatformSettings: (changes: {
    daily_model_calls?: number | null;
    self_registration?: boolean;
  }) => request<PlatformSettings>("/platform/settings", json(changes)),
  colleagues: (role?: Role) => request<Member[]>(role ? `/colleagues?role=${role}` : "/colleagues"),
  changeRole: (uid: string, role: Role) =>
    request<Member>(`/members/${encodeURIComponent(uid)}/role`, json({ role })),
  organisations: (type?: OrgType) =>
    request<Organisation[]>(type ? `/organisations?type=${type}` : "/organisations"),
  createOrganisation: (body: {
    name: string;
    type: OrgType;
    jurisdiction: string | null;
    admin: NewAccount;
  }) => request<Organisation>("/organisations", json(body)),
  members: () => request<Member[]>("/members"),
  addMember: (body: NewAccount & { role: Role }) => request<Member>("/members", json(body)),
  removeMember: (uid: string) =>
    request<Member>(`/members/${encodeURIComponent(uid)}/remove`, { method: "POST" }),
  grants: () => request<AccessGrant[]>("/grants"),
  grant: (granteeOrgId: string) =>
    request<AccessGrant>("/grants", json({ grantee_org_id: granteeOrgId })),
  revoke: (grantId: string) =>
    request<AccessGrant>(`/grants/${grantId}/revoke`, { method: "POST" }),
  organisationAudit: () => request<AuditLog>("/organisation/audit"),
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
