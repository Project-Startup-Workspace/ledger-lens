"use client";

import { AuditorHome } from "./auditor-home";
import { useSession } from "./auth-provider";
import { CaseList } from "./case-list";
import { FinishSetup } from "./finish-setup";
import { OwnerHome } from "./owner-home";
import { PlatformAdmin } from "./platform-admin";

/** Each kind of organisation starts from its own view of the same platform. */
export function Home() {
  const { me, ready } = useSession();
  if (!ready || !me) return <p className="text-sm text-slate-500">Loading…</p>;
  switch (me.org?.type) {
    case "lender":
      return <CaseList />;
    case "business":
      return <OwnerHome />;
    case "audit_firm":
      return <AuditorHome />;
    case "platform":
      return <PlatformAdmin />;
    default:
      return <FinishSetup />;
  }
}
