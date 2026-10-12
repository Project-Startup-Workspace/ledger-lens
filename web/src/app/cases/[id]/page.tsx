import { Suspense } from "react";

import { CaseWorkspace } from "@/components/case-workspace";

export default function CasePage() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">Loading case…</p>}>
      <CaseWorkspace />
    </Suspense>
  );
}
