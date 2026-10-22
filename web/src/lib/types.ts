// Mirrors the API contracts in agents/ledger_lens/shared/schemas.py (fields the UI uses).

export type CaseStatus = "draft" | "assessed" | "decided";
export type FindingStatus = "pass" | "fail" | "review" | "pending" | "not_applicable";
export type Outcome = "approve" | "refer" | "decline";

export interface BoundingBox {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface LedgerEntry {
  id: string;
  evidence_id: string;
  entry_date: string;
  description: string;
  amount: number;
  direction: "in" | "out";
  confidence: number;
  box: BoundingBox | null;
}

export interface EvidenceDocument {
  id: string;
  kind: "notebook" | "wallet_statement" | "bank_statement" | "receipt";
  filename: string;
  content_type: string;
}

export interface ExtractionResult {
  evidence_id: string;
  script: string;
  language: string;
  currency: string;
  entries: LedgerEntry[];
  warnings: string[];
  model: string;
}

export interface WeekTotal {
  week_start: string;
  iso_week: string;
  sales: number;
  expenses: number;
  net: number;
}

export interface CashFlowSummary {
  currency: string;
  weeks: WeekTotal[];
  total_sales: number;
  total_expenses: number;
  avg_weekly_sales: number;
  avg_weekly_net: number;
  sales_volatility: number;
  weeks_covered: number;
  entries_for_review: LedgerEntry[];
}

export interface ConsistencyFlag {
  week_start: string;
  notebook_sales: number;
  wallet_inflow: number;
  severity: "low" | "medium" | "high";
  explanation: string;
  officer_question: string;
}

export interface ConsistencyReport {
  status: "compared" | "insufficient_data";
  weeks_compared: number;
  baseline_ratio: number | null;
  flags: ConsistencyFlag[];
  consistency_score: number | null;
  notes: string[];
}

export interface ReasonCode {
  feature: string;
  label: string;
  contribution: number;
  text: string;
}

export interface CounterfactualStep {
  feature: string;
  text: string;
  sufficient: boolean;
}

export interface RiskResult {
  model_version: string;
  probability_of_default: number;
  grade: "A" | "B" | "C" | "D" | "E";
  recommendation: Outcome;
  reasons: ReasonCode[];
  path_to_approval: CounterfactualStep[];
  illustrative: boolean;
}

export interface Citation {
  title: string;
  clause: string;
  url: string;
  excerpt: string;
}

export interface Finding {
  rule_id: string;
  title: string;
  status: FindingStatus;
  severity: string;
  detail: string;
  citations: Citation[];
}

export interface ComplianceReport {
  jurisdiction: string;
  jurisdiction_name: string;
  rule_pack_version: string;
  findings: Finding[];
}

export interface Explanation {
  borrower_text: string;
  borrower_language: string;
  english_text: string | null;
  audio_available: boolean;
  written_by: string;
}

export interface Disclosure {
  apr_pct: number;
  total_repayable: number;
  instalment: number;
  instalments: number;
  acknowledged_at: string | null;
}

export interface OfficerDecision {
  officer_id: string;
  outcome: Outcome;
  recommended: Outcome;
  overridden: boolean;
  reason: string;
  decided_at: string;
}

export interface CreditFile {
  case_id: string;
  revision: number;
  status: CaseStatus;
  created_at: string;
  jurisdiction: string;
  applicant: {
    full_name: string;
    business_name: string;
    business_type: string;
    years_in_business: number;
    preferred_language: string;
  };
  loan: {
    amount: number;
    currency: string;
    tenor_months: number;
    annual_rate_pct: number;
    purpose: string;
  };
  evidence: EvidenceDocument[];
  extractions: ExtractionResult[];
  cash_flow: CashFlowSummary | null;
  consistency: ConsistencyReport | null;
  risk: RiskResult | null;
  compliance: ComplianceReport | null;
  explanation: Explanation | null;
  disclosure: Disclosure | null;
  decision: OfficerDecision | null;
  lender_org_id: string | null;
  business_org_id: string | null;
  credit_review: CreditReview | null;
  requests: EvidenceRequest[];
  engagements: Engagement[];
}

export interface CaseSummary {
  case_id: string;
  status: CaseStatus;
  business_name: string;
  jurisdiction: string;
  amount: number;
  currency: string;
  grade: string | null;
  recommendation: string | null;
  created_at: string;
  lender_org_id: string | null;
  business_org_id: string | null;
  reviewer: string | null;
  open_requests: number;
  engagements: Engagement["status"][];
}

export interface Jurisdiction {
  code: string;
  name: string;
  version: string;
}

export interface AuditEvent {
  seq: number;
  event_type: string;
  actor: string;
  at: string;
  hash: string;
}

export interface AuditLog {
  verification: { valid: boolean; events: number; error: string | null };
  events: AuditEvent[];
}

export type OrgType = "platform" | "lender" | "audit_firm" | "business";
export type Role =
  | "platform_admin"
  | "admin"
  | "loan_officer"
  | "credit_reviewer"
  | "audit_officer"
  | "audit_reviewer"
  | "owner"
  | "accountant";
export type OrgStatus = "active" | "pending" | "suspended";

export interface Organisation {
  id: string;
  name: string;
  type: OrgType;
  jurisdiction: string | null;
  status: OrgStatus;
}

export interface Me {
  uid: string;
  email: string;
  name: string;
  org: Organisation | null;
  role: Role | null;
  organisations_enabled: boolean;
}

export interface Member {
  uid: string;
  email: string;
  display_name: string;
  org_id: string;
  role: Role;
  disabled: boolean;
}

export interface AccessGrant {
  id: string;
  grantor_org_id: string;
  grantee_org_id: string;
  granted_by: string;
  granted_at: string;
  /** "pending" until the audit firm's admin accepts or declines. */
  status: "pending" | "active" | "declined";
  responded_by: string | null;
  responded_at: string | null;
  revoked_at: string | null;
  grantor_name: string;
  grantee_name: string;
  expires_at: string | null;
}

export interface CreditReview {
  reviewer_uid: string;
  reviewer: string;
  requested_by: string;
  requested_at: string;
}

export interface EvidenceRequest {
  id: string;
  from_org_id: string;
  requested_by: string;
  addressed_to: "lender" | "business";
  message: string;
  created_at: string;
  answer: string | null;
  answered_by: string | null;
  answered_at: string | null;
}

export interface AuditFinding {
  id: string;
  author: string;
  severity: "observation" | "issue";
  note: string;
  snapshot: string;
  recorded_at: string;
}

export interface Engagement {
  id: string;
  audit_firm_id: string;
  assignee_uid: string;
  assignee: string;
  assigned_by: string;
  assigned_at: string;
  status: "open" | "submitted" | "approved" | "returned";
  findings: AuditFinding[];
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  report_snapshot: string | null;
}

export interface PlatformSettings {
  config: {
    daily_model_calls: number | null;
    self_registration: boolean;
    updated_by: string | null;
  };
  deployment_daily_model_calls: number;
  effective_daily_model_calls: number;
  model_calls_today: number | null;
  llm_provider: string;
  model_extract: string;
  model_reason: string;
}
