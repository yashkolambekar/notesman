"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import AdminOnly from "@/components/AdminOnly";
import { useAuth } from "@/components/AuthProvider";
import { createCourse, listCourses } from "@/lib/api";
import { useApi } from "@/lib/useApi";

export default function CoursesPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { data: courses, error, loading } = useApi(listCourses, [user?.id], !authLoading);
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setMsg(null);
    try {
      const c = await createCourse({ name: name.trim() });
      router.push(`/courses/${c.id}`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Could not create course");
    }
  };

  return (
    <section className="subjects-page">
      <header className="page-head">
        <div>
          <h1>Courses</h1>
          <p className="muted">
            {courses
              ? courses.length === 0
                ? "Nothing here yet."
                : `${courses.length} course${courses.length === 1 ? "" : "s"}. Open one to see its subjects.`
              : " "}
          </p>
        </div>
      </header>

      {(authLoading || loading) && <p className="muted">Loading…</p>}
      {(error || msg) && <p className="err">{error ?? msg}</p>}

      {courses && (
        <ul className="subject-grid">
          {courses.map((c) => (
            <li key={c.id} className="subject-tile">
              <div className="tile-top">
                <h2>{c.name}</h2>
                {c.description && <p className="muted small">{c.description}</p>}
                <div className="tile-tags">
                  <span className="tag-static ref">
                    {c.subject_count} subject{c.subject_count === 1 ? "" : "s"}
                  </span>
                </div>
              </div>
              <Link href={`/courses/${c.id}`} className="btn tile-open">
                Open course
              </Link>
            </li>
          ))}
        </ul>
      )}

      <AdminOnly>
        <form className="add-row top-gap" onSubmit={add}>
          <input value={name} maxLength={120} placeholder="New course name" onChange={(e) => setName(e.target.value)} />
          <button className="btn primary" disabled={!name.trim()}>
            Create course
          </button>
        </form>
      </AdminOnly>
    </section>
  );
}
