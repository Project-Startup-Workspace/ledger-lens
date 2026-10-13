/**
 * Sign-in for the web app. When LL_WEB_USERS is set ("name:password,name2:password2"),
 * every page and API call needs HTTP Basic credentials, and the signed-in name becomes
 * the officer recorded on actions. Behind Identity-Aware Proxy, leave it unset and set
 * LL_IAP_AUDIENCE: the officer is then the email in IAP's signed assertion, verified
 * against Google's keys. A plain header is never trusted: anyone reaching the service
 * directly could send one.
 */
import { createRemoteJWKSet, jwtVerify } from "jose";
import { NextResponse, type NextRequest } from "next/server";

export const OFFICER_HEADER = "x-ll-officer";
const IAP_JWT_HEADER = "x-goog-iap-jwt-assertion";
const IAP_KEYS = createRemoteJWKSet(new URL("https://www.gstatic.com/iap/verify/public_key-jwk"));

/** The signed-in email from an IAP assertion, or null if it is missing or not genuine. */
async function iapOfficer(request: NextRequest, audience: string): Promise<string | null> {
  const token = request.headers.get(IAP_JWT_HEADER);
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, IAP_KEYS, {
      audience,
      issuer: "https://cloud.google.com/iap",
    });
    return typeof payload.email === "string" ? payload.email : null;
  } catch {
    return null;
  }
}

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

export async function proxy(request: NextRequest) {
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
  } else if (process.env.LL_IAP_AUDIENCE) {
    const officer = await iapOfficer(request, process.env.LL_IAP_AUDIENCE);
    if (!officer) return new NextResponse("Identity-Aware Proxy sign-in required", { status: 401 });
    headers.set(OFFICER_HEADER, officer);
  }
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
