/**
 * Sign-in for the web app. When LL_WEB_USERS is set ("name:password,name2:password2"),
 * every page and API call needs HTTP Basic credentials, and the signed-in name becomes
 * the officer recorded on actions. Behind Identity-Aware Proxy, leave it unset.
 */
import { NextResponse, type NextRequest } from "next/server";

export const OFFICER_HEADER = "x-ll-officer";

/** "name:pass:word" -> ["name", "pass:word"]; passwords may contain colons. */
function splitFirstColon(value: string): [string, string] {
  const at = value.indexOf(":");
  return at < 0 ? [value, ""] : [value.slice(0, at), value.slice(at + 1)];
}

function users(): Map<string, string> {
  const pairs = (process.env.LL_WEB_USERS ?? "").split(",").filter(Boolean);
  return new Map(pairs.map(splitFirstColon));
}

/** Compare without stopping at the first difference, so timing reveals nothing. */
function safeEqual(a: string, b: string): boolean {
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return diff === 0;
}

export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete(OFFICER_HEADER); // never trust a client-supplied identity

  const known = users();
  if (known.size > 0) {
    const encoded = request.headers.get("authorization")?.replace(/^Basic /, "") ?? "";
    let decoded = "";
    try {
      decoded = atob(encoded);
    } catch {
      // malformed header: treated as no credentials
    }
    const [name, password] = splitFirstColon(decoded);
    const expected = known.get(name);
    if (expected === undefined || !safeEqual(password, expected)) {
      return new NextResponse("Sign-in required", {
        status: 401,
        headers: { "www-authenticate": 'Basic realm="Ledger Lens", charset="UTF-8"' },
      });
    }
    headers.set(OFFICER_HEADER, name);
  }
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
