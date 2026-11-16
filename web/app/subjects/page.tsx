"use client";

import Link from "next/link";
import AdminOnly from "@/components/AdminOnly";
import { useAuth } from "@/components/AuthProvider";
import { listSubjects } from "@/lib/api";
import { isAdmin } from "@/lib/auth";
import { useApi } from "@/lib/useApi";

export default function SubjectsPage() {
  const { user, loading: authLoading } = useAuth();
  const { data: subjects, error, loading } = useApi(listSubjects, [user?.id], !authLoading);
  const admin = isAdmin(user);

  return (
    <section className="subjects-page">
      <header className="page-head">
        <div>
          <h1>Subjects</h1>
          <p className="muted">
            {subjects
              ? subjects.length === 0
                ? "Nothing here yet."
                : `${subjects.length} subject${subjects.length === 1 ? "" : "s"}. Open one to see its papers.`
              : " "}
          </p>
        </div>
        <AdminOnly>
          <Link href="/subjects/new" className="btn primary">
            + New subject
          </Link>
        </AdminOnly>
      </header>

      {(authLoading || loading) && <p className="muted">Loading…</p>}
      {error && <p className="err">{error}</p>}

      {subjects && subjects.length === 0 && !admin && (
        <p className="muted">No subjects have been published yet.</p>
      )}

      {subjects && (subjects.length > 0 || admin) && (
        <ul className="subject-grid">
          {subjects.map((s) => {
            const total = s.papers.reduce((n, p) => n + p.total, 0);
            const locked = s.papers.reduce((n, p) => n + p.locked, 0);
            return (
              <li key={s.id} className="subject-tile">
                <div className="tile-top">
                  <h2>{s.name}</h2>
                  {s.description && <p className="muted small">{s.description}</p>}
                  <div className="tile-tags">
                    <span className="tag-static syl">{s.syllabus_files} syllabus</span>
                    <span className="tag-static ref">{s.reference_files} references</span>
                  </div>
                </div>

                <div className="tile-papers">
                  <span className="eyebrow">
                    {s.papers.length} paper{s.papers.length === 1 ? "" : "s"}
                    {admin && total > 0 && ` · ${locked}/${total} answers locked`}
                  </span>
                  {s.papers.length === 0 ? (
                    <p className="muted small">No papers yet.</p>
                  ) : (
                    <ul>
                      {s.papers.map((p) => (
                        <li key={p.id}>
                          <Link href={`/subjects/${s.id}/papers/${p.id}`}>
                            <span>{p.title}</span>
                            <span className="muted small">{p.total === 0 ? "empty" : admin ? `${p.locked}/${p.total}` : p.total}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <Link href={`/subjects/${s.id}`} className="btn tile-open">
                  Open subject
                </Link>
              </li>
            );
          })}

          <AdminOnly>
            <li className="subject-tile new-tile">
              <Link href="/subjects/new">
                <span className="plus">+</span>
                <strong>New subject</strong>
                <span className="muted small">Upload a syllabus and references</span>
              </Link>
            </li>
          </AdminOnly>
        </ul>
      )}
    </section>
  );
}
