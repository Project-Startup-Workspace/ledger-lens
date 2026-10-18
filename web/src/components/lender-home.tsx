"use client";

import { useSession } from "./auth-provider";
import { CaseList } from "./case-list";

/** Loan officers open and prepare cases; credit reviewers see those sent to them first. */
export function LenderHome() {
  const { me } = useSession();
  if (me?.role === "credit_reviewer") {
    return (
      <div className="space-y-4">
        <CaseList
          title="Sent to you for a decision"
          demos={false}
          only={(c) => c.reviewer === me.email}
          empty="Nothing is waiting for your decision."
        />
        <CaseList title="All cases" demos={false} />
      </div>
    );
  }
  return <CaseList />;
}
