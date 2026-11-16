"use client";

import { useEffect, useState } from "react";
import RequireRole from "@/components/RequireRole";
import type { Me } from "@/lib/auth";

function Users() {
  const [users, setUsers] = useState<Me[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/admin/users", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Failed to load (${r.status})`))))
      .then(setUsers)
      .catch((e) => setError(e.message));
  }, []);

  const setRole = async (id: string, role: "user" | "admin") => {
    setSaving(id);
    setError(null);
    try {
      const r = await fetch(`/api/v1/admin/users/${id}/role`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Failed (${r.status})`);
      const updated: Me = await r.json();
      setUsers((cur) => cur?.map((u) => (u.id === id ? updated : u)) ?? cur);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setSaving(null);
    }
  };

  return (
    <section>
      <header className="page-head">
        <div>
          <h1>Admins</h1>
          <p className="muted">People who have signed in. Promote someone to let them edit.</p>
        </div>
      </header>

      {error && <p className="err" role="alert">{error}</p>}
      {!users && !error && <p className="muted">Loading…</p>}

      {users && (
        <ul className="files users">
          {users.map((u) => (
            <li key={u.id} className="file user-row">
              <div className="file-main">
                <span className="file-name">{u.name ?? u.email}</span>
                <span className="muted">{u.email}</span>
              </div>
              {u.role === "superadmin" ? (
                <span className="chip role-superadmin">superadmin</span>
              ) : (
                <select
                  value={u.role}
                  disabled={saving === u.id}
                  onChange={(e) => setRole(u.id, e.target.value as "user" | "admin")}
                  aria-label={`Role of ${u.email}`}
                >
                  <option value="user">User (read only)</option>
                  <option value="admin">Admin (can edit)</option>
                </select>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function AdminUsersPage() {
  return (
    <RequireRole role="superadmin">
      <Users />
    </RequireRole>
  );
}
