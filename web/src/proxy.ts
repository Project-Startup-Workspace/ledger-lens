/**
 * Sign-in for the web app. When LL_FIREBASE_PROJECT is set, every page and API call needs
 * a valid Firebase ID token in the session cookie; roles are applied by the API, which
 * checks the token again. When LL_WEB_USERS is set ("name:password,name2:password2"),
 * every page and API call needs HTTP Basic credentials, and the signed-in name becomes
 * the officer recorded on actions. Behind Identity-Aware Proxy, leave it unset and set
 * LL_IAP_AUDIENCE: the officer is then the email in IAP's signed assertion, verified
 * against Google's keys. A plain header is never trusted: anyone reaching the service
 * directly could send one.
 */
import { createRemoteJWKSet, decodeJwt, jwtVerify } from "jose";
import { NextResponse, type NextRequest } from "next/server";

import { PUBLIC_PATHS, SESSION_COOKIE } from "@/lib/session";

export const OFFICER_HEADER = "x-ll-officer";
// Signed-in pages must never sit in a shared cache such as the Firebase Hosting CDN,
// which would otherwise keep prerendered pages and serve them without sign-in.
const PRIVATE = "private, no-store";
const IAP_JWT_HEADER = "x-goog-iap-jwt-assertion";
const IAP_KEYS = createRemoteJWKSet(new URL("https://www.gstatic.com/iap/verify/public_key-jwk"));
const FIREBASE_KEYS = createRemoteJWKSet(
  new URL(
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com",
  ),
);

/** Whether the session cookie holds a genuine, unexpired ID token for this project. */
async function firebaseSignedIn(request: NextRequest, project: string): Promise<boolean> {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return false;
  const issuer = `https://securetoken.google.com/${project}`;
  if (process.env.FIREBASE_AUTH_EMULATOR_HOST) {
    // The local emulator signs nothing; its tokens are checked for shape and time only.
    // The variable is never set in deployment, and the API verifies every token again.
    try {
      const claims = decodeJwt(token);
      return (
        claims.aud === project && claims.iss === issuer && (claims.exp ?? 0) * 1000 > Date.now()
      );
    } catch {
      return false;
    }
  }
  try {
    await jwtVerify(token, FIREBASE_KEYS, {
      audience: project,
      issuer,
    });
    return true;
  } catch {
    return false;
  }
}

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

  // Identity-Aware Proxy takes precedence: when it fronts the app, its verified
  // assertion is the only identity, whatever else is configured.
  if (process.env.LL_IAP_AUDIENCE) {
    const officer = await iapOfficer(request, process.env.LL_IAP_AUDIENCE);
    if (!officer) {
      return new NextResponse("Identity-Aware Proxy sign-in required", {
        status: 401,
        headers: { "cache-control": PRIVATE },
      });
    }
    headers.set(OFFICER_HEADER, officer);
    return signedIn(headers);
  }

  const project = process.env.LL_FIREBASE_PROJECT;
  if (project) {
    const path = request.nextUrl.pathname;
    if (PUBLIC_PATHS.includes(path) || (await firebaseSignedIn(request, project))) {
      return signedIn(headers);
    }
    if (path.startsWith("/api/")) {
      return new NextResponse("Sign-in required", {
        status: 401,
        headers: { "cache-control": PRIVATE },
      });
    }
    // The sign-in page renews an expired token silently when Firebase still knows the user.
    const login = new URL("/login", request.url);
    login.searchParams.set("next", path + request.nextUrl.search);
    const response = NextResponse.redirect(login);
    response.headers.set("cache-control", PRIVATE);
    return response;
  }

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
        headers: {
          "www-authenticate": 'Basic realm="Ledger Lens", charset="UTF-8"',
          "cache-control": PRIVATE,
        },
      });
    }
    headers.set(OFFICER_HEADER, name);
    return signedIn(headers);
  }
  return NextResponse.next({ request: { headers } });
}

function signedIn(headers: Headers): NextResponse {
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("cache-control", PRIVATE);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
