"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "./AuthProvider";
import { isAdmin, isSuperadmin, loginUrl } from "@/lib/auth";

export default function TopBar() {
  const { user, loading, signOut } = useAuth();
  const path = usePathname();

  return (
    <header className="top">
      <span className="brand">
        <span className="mark" aria-hidden />
        Notesman
      </span>

      <nav className="topnav">
        <Link href="/courses">Courses</Link>
        {user && <Link href="/settings/api-keys">API keys</Link>}
        {user && <Link href="/settings/usage">Spending</Link>}
        {isSuperadmin(user) && <Link href="/admin/users">Admins</Link>}

        {!loading &&
          (user ? (
            <span className="who">
              {user.picture && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={user.picture} alt="" className="avatar" referrerPolicy="no-referrer" />
              )}
              <span className="who-name" title={user.email}>
                {user.name ?? user.email}
              </span>
              {user.role !== "user" && <span className={`chip role-${user.role}`}>{user.role}</span>}
              <button type="button" className="signout" onClick={signOut}>
                Sign out
              </button>
            </span>
          ) : (
            <a className="btn signin" href={loginUrl(path || "/")}>
              Sign in with Google
            </a>
          ))}
      </nav>
    </header>
  );
}
