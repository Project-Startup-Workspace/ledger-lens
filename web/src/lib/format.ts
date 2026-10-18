// Display helpers. Amounts use the browser locale; currencies are ISO codes from the case.

export function money(amount: number, currency: string): string {
  return `${Math.round(amount).toLocaleString()} ${currency}`;
}

export function percent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

/**
 * "12 Oct" from an ISO date or timestamp. Date-only values (ledger days, week starts)
 * are calendar dates, so they are shown in UTC; otherwise viewers west of UTC would
 * see the previous day.
 */
export function shortDate(iso: string): string {
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    ...(dateOnly ? { timeZone: "UTC" } : {}),
  });
}

export function title(slug: string): string {
  return slug
    .replace(/^synthetic-/, "")
    .split("-")
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}

const ORG_LABELS = {
  platform: "platform",
  lender: "lender",
  audit_firm: "audit firm",
  business: "business",
} as const;

export const orgLabel = (type: keyof typeof ORG_LABELS): string => ORG_LABELS[type];

export function roleLabel(role: string | null): string {
  return role === "platform_admin" ? "platform admin" : (role ?? "no role yet");
}
