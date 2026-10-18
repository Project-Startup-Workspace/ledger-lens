// What the signed-in person may do with a case. The API enforces the same rules
// (agents/ledger_lens/access.py); this only decides which controls to show.
import type { CreditFile, Engagement, Me } from "./types";

export interface CasePermissions {
  upload: boolean;
  prepare: boolean;
  explain: boolean;
  acknowledge: boolean;
  send: boolean;
  assignReviewer: boolean;
  decide: boolean;
  /** Who this person may ask for evidence. */
  askTo: ("lender" | "business")[];
  answerAs: "lender" | "business" | null;
  assignEngagement: boolean;
  /** This person's own open engagement, where they record findings. */
  engagement: Engagement | null;
  approveReport: boolean;
}

export function permissions(me: Me | null, credit: CreditFile): CasePermissions {
  const type = me?.org?.type;
  const role = me?.role;
  const open = credit.status !== "decided";
  const unsent = credit.lender_org_id === null && credit.business_org_id !== null;
  const lender = type === "lender";
  const preparer = lender && (role === "admin" || role === "loan_officer");
  const owner = type === "business" && role === "owner";
  const openRequestToBusiness = credit.requests.some(
    (r) => r.answer === null && r.addressed_to === "business",
  );
  const mine = credit.engagements.find((e) => e.assignee_uid === me?.uid) ?? null;
  const working = mine && (mine.status === "open" || mine.status === "returned") ? mine : null;
  const firm = credit.engagements.filter((e) => e.audit_firm_id === me?.org?.id);
  const askTo: ("lender" | "business")[] = [];
  if (lender && credit.business_org_id) askTo.push("business");
  if (working) {
    if (credit.lender_org_id) askTo.push("lender");
    if (credit.business_org_id) askTo.push("business");
  }
  return {
    upload: open && (preparer || (type === "business" && (unsent || openRequestToBusiness))),
    prepare: open && (preparer || (type === "business" && unsent)),
    explain: lender || type === "business",
    acknowledge: open && (preparer || owner),
    send: owner && unsent && open,
    assignReviewer: open && preparer && credit.status === "assessed",
    decide:
      open &&
      lender &&
      (role === "admin" ||
        (role === "credit_reviewer" && credit.credit_review?.reviewer_uid === me?.uid)),
    askTo,
    answerAs: lender ? "lender" : type === "business" ? "business" : null,
    assignEngagement:
      type === "audit_firm" && role === "admin" && !firm.some((e) => e.status !== "approved"),
    engagement: working,
    approveReport:
      type === "audit_firm" &&
      (role === "admin" || role === "audit_reviewer") &&
      firm.some((e) => e.status === "submitted"),
  };
}
