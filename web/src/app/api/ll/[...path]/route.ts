/**
 * Server-side proxy to the Ledger Lens API.
 *
 * The browser only ever talks to this app. The API token and the officer identity are
 * added here, on the server, so neither can be read or forged from the browser.
 */
import type { NextRequest } from "next/server";

const API_URL = process.env.LL_API_URL ?? "http://localhost:8080";
const PASSTHROUGH_HEADERS = ["content-type", "accept"];

async function forward(request: NextRequest, ctx: RouteContext<"/api/ll/[...path]">) {
  const { path } = await ctx.params;
  const target = new URL(`${API_URL}/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  for (const name of PASSTHROUGH_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (process.env.LL_API_TOKEN) {
    headers.set("authorization", `Bearer ${process.env.LL_API_TOKEN}`);
    // Until officer sign-in exists, every action is attributed to the configured officer.
    headers.set("x-officer-id", process.env.LL_OFFICER_ID ?? "officer");
  }

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const response = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    // Required by Node's fetch when streaming a request body (uploads).
    ...(hasBody ? { duplex: "half" } : {}),
    cache: "no-store",
  } as RequestInit);

  const out = new Headers();
  for (const name of ["content-type", "content-disposition"]) {
    const value = response.headers.get(name);
    if (value) out.set(name, value);
  }
  return new Response(response.body, { status: response.status, headers: out });
}

export const GET = forward;
export const POST = forward;
