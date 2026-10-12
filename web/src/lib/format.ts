// Display helpers. Amounts use the browser locale; currencies are ISO codes from the case.

export function money(amount: number, currency: string): string {
  return `${Math.round(amount).toLocaleString()} ${currency}`;
}

export function percent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function title(slug: string): string {
  return slug
    .replace(/^synthetic-/, "")
    .split("-")
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
}
