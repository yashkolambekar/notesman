"use client";

import { useEffect, useState } from "react";
import RequireRole from "@/components/RequireRole";
import type { Me } from "@/lib/auth";

type AdminUser = Me & { subject_ids: string[] };
type SubjectChoice = { id: string; course_id: string; name: string; course_name: string };

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { credentials: "same-origin", ...init });
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Failed (${r.status})`);
  return r.json();
}

const put = <T,>(url: string, body: unknown) =>
  call<T>(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function Users() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [subjects, setSubjects] = useState<SubjectChoice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      call<AdminUser[]>("/api/v1/admin/users"),
      call<SubjectChoice[]>("/api/v1/admin/subjects"),
    ])
      .then(([u, s]) => {
        setUsers(u);
        setSubjects(s);
      })
      .catch((e) => setError(e.message));
  }, []);

  const save = async (id: string, fn: () => Promise<AdminUser>) => {
    setSaving(id);
    setError(null);
    try {
      const updated = await fn();
      setUsers((cur) => cur?.map((u) => (u.id === id ? updated : u)) ?? cur);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setSaving(null);
    }
  };

  const setRole = (id: string, role: "user" | "admin") =>
    save(id, () => put<AdminUser>(`/api/v1/admin/users/${id}/role`, { role }));

  const toggleCourse = (u: AdminUser, courseId: string) => {
    const ids = subjects.filter((s) => s.course_id === courseId).map((s) => s.id);
    const all = ids.every((id) => u.subject_ids.includes(id));
    const next = all
      ? u.subject_ids.filter((x) => !ids.includes(x))
      : [...new Set([...u.subject_ids, ...ids])];
    return save(u.id, () => put<AdminUser>(`/api/v1/admin/users/${u.id}/subjects`, { subject_ids: next }));
  };

  const courses = [...new Map(subjects.map((s) => [s.course_id, s.course_name])).entries()];

  const toggle = (u: AdminUser, subjectId: string) => {
    const ids = u.subject_ids.includes(subjectId)
      ? u.subject_ids.filter((x) => x !== subjectId)
      : [...u.subject_ids, subjectId];
    return save(u.id, () => put<AdminUser>(`/api/v1/admin/users/${u.id}/subjects`, { subject_ids: ids }));
  };

  return (
    <section>
      <header className="page-head">
        <div>
          <h1>Admins</h1>
          <p className="muted">
            People who have signed in. Make someone an admin of everything, or keep them a user and
            assign the subjects they can administer.
          </p>
        </div>
      </header>

      {error && <p className="err" role="alert">{error}</p>}
      {!users && !error && <p className="muted">Loading…</p>}

      {users && (
        <ul className="files users">
          {users.map((u) => (
            <li key={u.id} className="file user-row" style={{ flexWrap: "wrap" }}>
              <div className="file-main">
                <span className="file-name">{u.name ?? u.email}</span>
                <span className="muted">{u.email}</span>
              </div>
              {u.role === "superadmin" ? (
                <span className="chip role-superadmin">superadmin</span>
              ) : (
                <>
                  {u.role === "user" && (
                    <button type="button" className="btn" onClick={() => setOpen(open === u.id ? null : u.id)}>
                      {u.subject_ids.length
                        ? `${u.subject_ids.length} subject${u.subject_ids.length === 1 ? "" : "s"}`
                        : "Assign subjects"}
                    </button>
                  )}
                  <select
                    value={u.role}
                    disabled={saving === u.id}
                    onChange={(e) => setRole(u.id, e.target.value as "user" | "admin")}
                    aria-label={`Role of ${u.email}`}
                  >
                    <option value="user">User (read only, plus assigned subjects)</option>
                    <option value="admin">Admin (can edit everything)</option>
                  </select>
                </>
              )}
              {open === u.id && u.role === "user" && (
                <div style={{ flexBasis: "100%" }}>
                  {subjects.length === 0 && <p className="muted small">No subjects exist yet.</p>}
                  {courses.map(([cid, cname]) => {
                    const inCourse = subjects.filter((s) => s.course_id === cid);
                    const have = inCourse.filter((s) => u.subject_ids.includes(s.id)).length;
                    return (
                      <div key={cid} className="top-gap">
                        <label>
                          <input
                            type="checkbox"
                            checked={have === inCourse.length}
                            ref={(el) => {
                              if (el) el.indeterminate = have > 0 && have < inCourse.length;
                            }}
                            disabled={saving === u.id}
                            onChange={() => toggleCourse(u, cid)}
                          />{" "}
                          <strong>{cname}</strong>{" "}
                          <span className="muted small">· whole course ({have}/{inCourse.length})</span>
                        </label>
                        <ul className="plain" style={{ marginLeft: 22 }}>
                          {inCourse.map((s) => (
                            <li key={s.id}>
                              <label>
                                <input
                                  type="checkbox"
                                  checked={u.subject_ids.includes(s.id)}
                                  disabled={saving === u.id}
                                  onChange={() => toggle(u, s.id)}
                                />{" "}
                                {s.name}
                              </label>
                            </li>
                          ))}
                        </ul>
                      </div>
                    );
                  })}
                </div>
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
