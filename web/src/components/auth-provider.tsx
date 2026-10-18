"use client";

import type { Auth } from "@firebase/auth";
import { onIdTokenChanged, signOut as firebaseSignOut } from "@firebase/auth";
import { usePathname, useRouter } from "next/navigation";
import {
  Suspense,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { api, onSessionExpired } from "@/lib/api";
import { firebaseAuth, writeSession, type FirebaseConfig } from "@/lib/firebase";
import { PUBLIC_PATHS } from "@/lib/session";
import type { Me } from "@/lib/types";

interface Session {
  /** Null when sign-in is not Firebase (single-lender mode) or not loaded yet. */
  auth: Auth | null;
  me: Me | null;
  ready: boolean;
  /** Reload the person after their organisation or role changed. */
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession is used outside AuthProvider");
  return session;
}

/** Keeps the session cookie in step with Firebase and loads who the person is. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [auth, setAuth] = useState<Auth | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let unsubscribe = () => {};
    fetch("/api/config")
      .then((r) => r.json() as Promise<{ firebase: FirebaseConfig | null }>)
      .then(({ firebase }) => {
        if (!firebase) {
          // Single-lender sign-in: the server has already signed the officer in.
          api
            .me()
            .then(setMe)
            .finally(() => setReady(true));
          return;
        }
        const firebaseApp = firebaseAuth(firebase);
        setAuth(firebaseApp);
        onSessionExpired(async () => {
          if (!firebaseApp.currentUser) return false;
          await writeSession(firebaseApp.currentUser, true);
          return true;
        });
        unsubscribe = onIdTokenChanged(firebaseApp, async (user) => {
          await writeSession(user);
          setMe(user ? await api.me().catch(() => null) : null);
          setReady(true);
        });
      })
      .catch(() => setReady(true));
    return () => {
      unsubscribe();
      onSessionExpired(null);
    };
  }, []);

  const refresh = useCallback(async () => {
    if (auth?.currentUser) await writeSession(auth.currentUser, true);
    setMe(await api.me());
  }, [auth]);

  const signOut = useCallback(async () => {
    if (!auth) return;
    await firebaseSignOut(auth);
    await writeSession(null);
    setMe(null);
    router.replace("/login");
  }, [auth, router]);

  return (
    <SessionContext.Provider value={{ auth, me, ready, refresh, signOut }}>
      {/* The path is known only per request, so this streams in after prerendering. */}
      <Suspense fallback={null}>
        <SignInRedirect />
      </Suspense>
      {children}
    </SessionContext.Provider>
  );
}

/** Sends someone whose Firebase sign-in has ended to the sign-in page. */
function SignInRedirect() {
  const router = useRouter();
  const pathname = usePathname();
  const { auth, me, ready } = useSession();
  const onPublicPage = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    if (ready && auth && !me && !onPublicPage) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [ready, auth, me, onPublicPage, pathname, router]);
  return null;
}
