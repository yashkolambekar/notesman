"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "./AuthProvider";
import { isAdmin, isSuperadmin, loginUrl } from "@/lib/auth";

export default function RequireRole({
  role,
  children,
}: {
  role: "admin" | "superadmin";
  children: React.ReactNode;
}) {
  const { user, loading } = useAuth();
  const path = usePathname();

  if (loading) return null;
  const ok = role === "superadmin" ? isSuperadmin(user) : isAdmin(user);
  if (ok) return <>{children}</>;

  return (
    <section className="card center">
      <h1>{user ? "Not allowed" : "Sign in required"}</h1>
      <p className="muted">
        {user
          ? `This page is for ${role === "superadmin" ? "the superadmin" : "admins"} only.`
          : "This page is for admins. Sign in with your Google account."}
      </p>
      {!user && (
        <div className="row">
          <a className="btn primary" href={loginUrl(path || "/")}>
            Sign in with Google
          </a>
        </div>
      )}
    </section>
  );
}
