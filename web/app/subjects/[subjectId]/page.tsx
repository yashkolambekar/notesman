"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import RenameTitle from "@/components/RenameTitle";
import { archivePaper, archiveSubject, createPaper, unarchivePaper, unarchiveSubject, deleteFile, deleteSubject, getSubject, listFiles, renamePaper, renameSubject, retryFile, uploadFile } from "@/lib/api";
import { isAdmin } from "@/lib/auth";
import { formatSize, validateFile } from "@/lib/files";
import type { FileKind } from "@/lib/types";
import { useApi } from "@/lib/useApi";

export default function SubjectPage({ params }: { params: Promise<{ subjectId: string }> }) {
  const { subjectId } = use(params);
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const globalAdmin = isAdmin(user);

  const subject = useApi(() => getSubject(subjectId), [subjectId, user?.id], !authLoading);
  // Admin rights are per subject: a global admin, or a user the superadmin assigned to it.
  const admin = subject.data?.can_edit ?? false;
  const files = useApi(() => (admin ? listFiles(subjectId) : Promise.resolve([])), [subjectId, admin], !authLoading);

  // Keep the file list fresh while the worker is processing something.
  const working = files.data?.some((f) => f.status === "queued" || f.status === "processing");
  const reloadFiles = files.reload;
  useEffect(() => {
    if (!working) return;
    const t = setInterval(reloadFiles, 4000);
    return () => clearInterval(t);
  }, [working, reloadFiles]);

  const [title, setTitle] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const pick = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<FileKind>("reference");

  const guard = async (fn: () => Promise<void>) => {
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Something went wrong");
    }
  };

  const addPaper = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    guard(async () => {
      const p = await createPaper(subjectId, title.trim());
      router.push(`/subjects/${subjectId}/papers/${p.id}`);
    });
  };

  const upload = (list: FileList | null) =>
    guard(async () => {
      for (const f of Array.from(list ?? [])) {
        const bad = validateFile(f);
        if (bad) throw new Error(`${f.name}: ${bad}`);
        setUploading(f.name);
        try {
          await uploadFile(subjectId, f, kind, () => {});
        } finally {
          setUploading(null);
        }
      }
      files.reload();
      subject.reload();
    });

  if (authLoading || subject.loading) return <p className="muted">Loading…</p>;
  if (subject.error || !subject.data) return <p className="err">{subject.error ?? "Not found"}</p>;
  const s = subject.data;

  return (
    <section className="subject-page">
      <Link href={`/courses/${s.course_id}`} className="back">
        ← {s.course_name}
      </Link>
      <header className="page-head">
        <div>
          <RenameTitle
            value={s.name}
            canEdit={admin}
            max={120}
            onSave={async (n) => {
              await renameSubject(subjectId, n);
              subject.reload();
            }}
          />
          {s.description && <p className="muted">{s.description}</p>}
        </div>
      </header>

      {s.archived && (
        <p className="banner" role="status">
          This subject is archived: readers cannot see it.{" "}
          {admin && (
            <button type="button" className="rename-btn" onClick={() => guard(async () => { await unarchiveSubject(s.id); subject.reload(); })}>
              Restore
            </button>
          )}
        </p>
      )}

      {msg && <p className="banner err" role="alert">{msg}</p>}

      <div className="card">
        <h2 className="h2">Papers <span className="muted small">({s.papers.length})</span></h2>
        {s.papers.length === 0 ? (
          <p className="muted">{admin ? "No papers yet. Create the first one." : "No papers have been published yet."}</p>
        ) : (
          <ul className="paper-grid">
            {s.papers.map((p) => {
              const pct = p.total ? Math.round((p.locked / p.total) * 100) : 0;
              const done = p.total > 0 && p.locked === p.total;
              return (
                <li key={p.id} className="paper-card">
                  <Link href={`/subjects/${s.id}/papers/${p.id}`}>
                    <h3>{p.title}</h3>
                    <div className="paper-count">
                      <strong>{p.total}</strong>
                      <span className="muted">{p.total === 1 ? "question" : "questions"}</span>
                    </div>
                    {admin && p.total > 0 && (
                      <div className="paper-progress">
                        <div className="bar" aria-hidden="true">
                          <span style={{ width: `${pct}%` }} />
                        </div>
                        <span className={`small ${done ? "ok" : "muted"}`}>
                          {done ? "All locked" : `${p.locked}/${p.total} locked`}
                        </span>
                      </div>
                    )}
                    {p.total === 0 && <span className="muted small">Empty</span>}
                  </Link>
                  {admin && (
                    <span className="paper-actions">
                    <button
                      type="button"
                      className="rename-btn"
                      onClick={() => {
                        const n = prompt("Rename paper", p.title)?.trim();
                        if (n && n !== p.title) guard(async () => { await renamePaper(p.id, n); subject.reload(); });
                      }}
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      className="rename-btn"
                      onClick={() => guard(async () => { await archivePaper(p.id); subject.reload(); })}
                    >
                      Archive
                    </button>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {admin && (
          <form className="add-row top-gap" onSubmit={addPaper}>
            <input value={title} maxLength={200} placeholder="New paper title" onChange={(e) => setTitle(e.target.value)} />
            <button className="btn primary" disabled={!title.trim()}>
              Create paper
            </button>
          </form>
        )}
      </div>

      {admin && s.archived_papers.length > 0 && (
        <div className="card top-gap">
          <h2 className="h2">Archived papers <span className="muted small">({s.archived_papers.length})</span></h2>
          <ul className="files">
            {s.archived_papers.map((p) => (
              <li key={p.id} className="file">
                <div className="file-main">
                  <Link href={`/subjects/${s.id}/papers/${p.id}`} className="file-name">{p.title}</Link>
                  <span className="muted">{p.total} question{p.total === 1 ? "" : "s"}</span>
                </div>
                <button
                  type="button"
                  className="btn"
                  onClick={() => guard(async () => { await unarchivePaper(p.id); subject.reload(); })}
                >
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {admin && (
        <div className="card top-gap">
          <h2 className="h2">Files</h2>
          {files.data && files.data.length === 0 && <p className="muted">No files yet.</p>}
          {files.data && files.data.length > 0 && (
            <ul className="files">
              {files.data.map((f) => (
                <li key={f.id} className={`file subject-file ${f.status}`}>
                  <div className="file-main">
                    <span className="file-name" title={f.filename}>{f.filename}</span>
                    <span className="muted">{formatSize(f.size_bytes)}</span>
                  </div>
                  <span className={`chip ${f.kind === "syllabus" ? "role-admin" : "locked"}`}>{f.kind}</span>
                  <span className="file-state">
                    {f.status === "ready" && (
                      <span className="ok small">{f.chunk_count} chunks</span>
                    )}
                    {(f.status === "queued" || f.status === "processing") && (
                      <span className="muted small">{f.status === "queued" ? "waiting for worker" : "processing…"}</span>
                    )}
                    {f.status === "failed" && (
                      <>
                        <span className="err small" title={f.error ?? ""}>{f.error ?? "failed"}</span>
                        <button
                          type="button"
                          className="link-danger retry"
                          onClick={() => guard(async () => { await retryFile(f.id); files.reload(); })}
                        >
                          Retry
                        </button>
                      </>
                    )}
                  </span>
                  <button
                    type="button"
                    className="icon"
                    aria-label={`Delete ${f.filename}`}
                    onClick={() => confirm(`Delete ${f.filename}?`) && guard(async () => { await deleteFile(f.id); files.reload(); subject.reload(); })}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="add-row top-gap">
            <select value={kind} onChange={(e) => setKind(e.target.value as FileKind)} aria-label="Kind of new files">
              <option value="reference">Reference</option>
              <option value="syllabus">Syllabus</option>
            </select>
            <input ref={pick} type="file" multiple hidden onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
            <button type="button" className="btn" disabled={!!uploading} onClick={() => pick.current?.click()}>
              {uploading ? `Uploading ${uploading}…` : "Add files"}
            </button>
          </div>
        </div>
      )}

      {admin && !s.archived && (
        <p className="top-gap">
          <button
            type="button"
            className="rename-btn"
            style={{ marginLeft: 0 }}
            onClick={() =>
              confirm(`Archive "${s.name}"? Readers will no longer see it. You can restore it later.`) &&
              guard(async () => { await archiveSubject(s.id); router.push(`/courses/${s.course_id}`); })
            }
          >
            Archive subject
          </button>
        </p>
      )}

      {globalAdmin && (
        <p className="top-gap">
          <button
            type="button"
            className="link-danger"
            onClick={() =>
              confirm(`Delete "${s.name}" with all its papers and files? This cannot be undone.`) &&
              guard(async () => { await deleteSubject(s.id); router.push(`/courses/${s.course_id}`); })
            }
          >
            Delete subject
          </button>
        </p>
      )}
    </section>
  );
}
