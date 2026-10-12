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
  translated: boolean;
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
