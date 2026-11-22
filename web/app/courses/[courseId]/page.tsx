"use client";

import Link from "next/link";
import AdminOnly from "@/components/AdminOnly";
import { useAuth } from "@/components/AuthProvider";
import { use } from "react";
import { useRouter } from "next/navigation";
import RenameTitle from "@/components/RenameTitle";
import { compact, usd } from "@/lib/money";
import { deleteCourse, getCourse, getCourseSpend, listSubjects, renameCourse, unarchiveSubject } from "@/lib/api";
import { isAdmin } from "@/lib/auth";
import { useApi } from "@/lib/useApi";

export default function CoursePage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const course = useApi(() => getCourse(courseId), [courseId], !authLoading);
  const { data: allSubjects, error, loading, reload } = useApi(() => listSubjects(courseId), [courseId, user?.id], !authLoading);
  const spend = useApi(() => getCourseSpend(courseId), [courseId, user?.id], !authLoading);
  const subjects = allSubjects?.filter((s) => !s.archived) ?? null;
  const archivedSubjects = allSubjects?.filter((s) => s.archived) ?? [];
  const admin = isAdmin(user);
  const newHref = `/courses/${courseId}/subjects/new`;
  if (course.error) return <p className="err">{course.error}</p>;

  return (
    <section className="subjects-page">
      <Link href="/courses" className="back">
        ← All courses
      </Link>
      <header className="page-head">
        <div>
          <RenameTitle
            value={course.data?.name ?? ""}
            fallback="Course"
            canEdit={course.data?.can_edit ?? false}
            max={120}
            onSave={async (n) => {
              course.setData(await renameCourse(courseId, n));
            }}
          />
          {course.data?.description && <p className="muted">{course.data.description}</p>}
          {spend.data && spend.data.total_usd > 0 && (
            <p className="muted small spend-line">
              {usd(spend.data.total_usd)} spent · {spend.data.papers} paper{spend.data.papers === 1 ? "" : "s"} ·{" "}
              {spend.data.questions} question{spend.data.questions === 1 ? "" : "s"} ·{" "}
              {compact(spend.data.embed_calls)} embedding call{spend.data.embed_calls === 1 ? "" : "s"} ·{" "}
              {compact(spend.data.chat_calls)} chat call{spend.data.chat_calls === 1 ? "" : "s"} ·{" "}
              {compact(spend.data.input_tokens)} tokens in / {compact(spend.data.output_tokens)} out
              <br />
              paid by {spend.data.by_admin.map((a) => `${a.name} (${usd(a.cost_usd)})`).join(", ")}
            </p>
          )}
          <p className="muted">
            {subjects
              ? subjects.length === 0
                ? "Nothing here yet."
                : `${subjects.length} subject${subjects.length === 1 ? "" : "s"}. Open one to see its papers.`
              : " "}
          </p>
        </div>
        <AdminOnly>
          <Link href={newHref} className="btn primary">
            + New subject
          </Link>
        </AdminOnly>
      </header>

      {(authLoading || loading) && <p className="muted">Loading…</p>}
      {error && <p className="err">{error}</p>}

      {subjects && subjects.length === 0 && !admin && (
        <p className="muted">No subjects in this course yet.</p>
      )}

      {subjects && (subjects.length > 0 || admin) && (
        <ul className="subject-grid">
          {subjects.map((s) => {
            const total = s.papers.reduce((n, p) => n + p.total, 0);
            const locked = s.papers.reduce((n, p) => n + p.locked, 0);
            const edit = s.can_edit;
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
                    {edit && total > 0 && ` · ${locked}/${total} answers locked`}
                  </span>
                  {s.papers.length === 0 ? (
                    <p className="muted small">No papers yet.</p>
                  ) : (
                    <ul>
                      {s.papers.map((p) => (
                        <li key={p.id}>
                          <Link href={`/subjects/${s.id}/papers/${p.id}`}>
                            <span>{p.title}</span>
                            <span className="muted small">{p.total === 0 ? "empty" : edit ? `${p.locked}/${p.total}` : p.total}</span>
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
              <Link href={newHref}>
                <span className="plus">+</span>
                <strong>New subject</strong>
                <span className="muted small">Upload a syllabus and references</span>
              </Link>
            </li>
          </AdminOnly>
        </ul>
      )}

      {archivedSubjects.length > 0 && (
        <div className="card top-gap">
          <h2 className="h2">Archived subjects <span className="muted small">({archivedSubjects.length})</span></h2>
          <ul className="files">
            {archivedSubjects.map((s) => (
              <li key={s.id} className="file">
                <div className="file-main">
                  <Link href={`/subjects/${s.id}`} className="file-name">{s.name}</Link>
                </div>
                <button
                  type="button"
                  className="btn"
                  onClick={() => unarchiveSubject(s.id).then(reload)}
                >
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {admin && (
        <p className="top-gap">
          <button
            type="button"
            className="link-danger"
            onClick={() =>
              confirm(`Delete course "${course.data?.name}" with all its subjects, papers and files? This cannot be undone.`) &&
              deleteCourse(courseId).then(() => router.push("/courses"))
            }
          >
            Delete course
          </button>
        </p>
      )}
    </section>
  );
}
