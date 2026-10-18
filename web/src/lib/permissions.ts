// What the signed-in person may do with a case. The API enforces the same rules
// (agents/ledger_lens/access.py); this only decides which controls to show.
import type { CreditFile, Me } from "./types";

export interface CasePermissions {
  prepare: boolean;
  explain: boolean;
  decide: boolean;
  review: boolean;
  send: boolean;
}

export function permissions(me: Me | null, credit: CreditFile): CasePermissions {
  const type = me?.org?.type;
  const open = credit.status !== "decided";
  const lender = type === "lender";
  const owner = type === "business";
  const unsent = credit.lender_org_id === null;
  return {
    prepare: open && (lender || (owner && unsent)),
    explain: lender || owner,
    decide: open && lender,
    review: type === "audit_firm",
    send: owner && unsent && open,
  };
}
