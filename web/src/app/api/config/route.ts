import { connection } from "next/server";

/** Firebase's web settings, read at request time so one image serves any project. */
export async function GET() {
  await connection();
  const projectId = process.env.LL_FIREBASE_PROJECT;
  const firebase = projectId
    ? {
        apiKey: process.env.LL_FIREBASE_API_KEY ?? "",
        authDomain: process.env.LL_FIREBASE_AUTH_DOMAIN ?? `${projectId}.firebaseapp.com`,
        projectId,
        // Local development against the Firebase Auth emulator only.
        emulatorHost: process.env.FIREBASE_AUTH_EMULATOR_HOST ?? null,
      }
    : null;
  return Response.json({ firebase }, { headers: { "cache-control": "private, no-store" } });
}
