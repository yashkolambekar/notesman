"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { Me } from "@/lib/auth";

type Ctx = { user: Me | null; loading: boolean; signOut: () => Promise<void> };

const AuthContext = createContext<Ctx>({ user: null, loading: true, signOut: async () => {} });

export const useAuth = () => useContext(AuthContext);

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    fetch("/api/v1/me", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : { user: null }))
      .then((d) => live && setUser(d.user ?? null))
      .catch(() => live && setUser(null))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, []);

  const signOut = useCallback(async () => {
    await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" });
    setUser(null);
  }, []);

  return <AuthContext.Provider value={{ user, loading, signOut }}>{children}</AuthContext.Provider>;
}
