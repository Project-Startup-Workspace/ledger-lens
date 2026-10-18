// Firebase Authentication in the browser. Only sign-in lives here; roles come from the API.
import { getApps, initializeApp } from "@firebase/app";
import { connectAuthEmulator, getAuth, type Auth, type User } from "@firebase/auth";

import { SESSION_COOKIE } from "./session";

export interface FirebaseConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  emulatorHost: string | null;
}

export function firebaseAuth({ emulatorHost, ...config }: FirebaseConfig): Auth {
  const existing = getApps()[0];
  const auth = getAuth(existing ?? initializeApp(config));
  if (emulatorHost && !existing) {
    connectAuthEmulator(auth, `http://${emulatorHost}`, { disableWarnings: true });
  }
  return auth;
}

/** Put the user's current ID token where the server can check it, or clear it. */
export async function writeSession(user: User | null, forceRefresh = false): Promise<void> {
  const secure = location.protocol === "https:" ? "; Secure" : "";
  if (!user) {
    document.cookie = `${SESSION_COOKIE}=; Path=/; Max-Age=0; SameSite=Strict${secure}`;
    return;
  }
  const token = await user.getIdToken(forceRefresh);
  // ID tokens last an hour; Firebase refreshes them before then while the page is open.
  document.cookie = `${SESSION_COOKIE}=${token}; Path=/; Max-Age=3600; SameSite=Strict${secure}`;
}
