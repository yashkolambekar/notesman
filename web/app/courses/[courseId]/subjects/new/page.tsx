"use client";

import Link from "next/link";
import { use, useState } from "react";
import FileDrop from "@/components/FileDrop";
import FileList, { type Item } from "@/components/FileList";
import { createSubject, uploadFile } from "@/lib/api";
import type { FileKind } from "@/lib/types";
import { validateFile } from "@/lib/files";
import RequireRole from "@/components/RequireRole";

const NAME_MAX = 120;

function NewSubjectForm({ courseId }: { courseId: string }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [notices, setNotices] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [subjectId, setSubjectId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);

  const patch = (id: string, p: Partial<Item>) =>
    setItems((cur) => cur.map((it) => (it.id === id ? { ...it, ...p } : it)));

  const addFiles = (kind: FileKind, files: File[]) => {
    const problems: string[] = [];
    const fresh: Item[] = [];
    for (const file of files) {
      const bad = validateFile(file);
      if (bad) {
        problems.push(`${file.name}: ${bad}`);
        continue;
      }
      const dup = [...items, ...fresh].some(
        (i) => i.file.name === file.name && i.file.size === file.size,
      );
      if (dup) {
        problems.push(`${file.name}: already added`);
        continue;
      }
      fresh.push({ id: crypto.randomUUID(), file, kind, status: "pending", progress: 0 });
    }
    setNotices(problems);
    if (fresh.length) setItems((cur) => [...cur, ...fresh]);
  };

  const hasSyllabus = items.some((i) => i.kind === "syllabus");
  const nameOk = name.trim().length > 0;
  const pending = items.filter((i) => i.status !== "done");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!nameOk || busy) return;
    setBusy(true);
    setError(null);

    try {
      let id = subjectId;
      if (!id) {
        const s = await createSubject(courseId, {
          name: name.trim(),
          description: description.trim() || undefined,
        });
        id = s.id;
        setSubjectId(id);
      }

      let failed = 0;
      for (const it of items) {
        if (it.status === "done") continue;
        patch(it.id, { status: "uploading", progress: 0, error: undefined });
        try {
          await uploadFile(id, it.file, it.kind, (p) => patch(it.id, { progress: p }));
          patch(it.id, { status: "done", progress: 100 });
        } catch (err) {
          failed++;
          patch(it.id, {
            status: "error",
            error: err instanceof Error ? err.message : "Upload failed",
          });
        }
      }
      if (failed === 0) setFinished(true);
      else setError(`${failed} file${failed > 1 ? "s" : ""} failed. Retry or remove them.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create subject");
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setName("");
    setDescription("");
    setItems([]);
    setNotices([]);
    setSubjectId(null);
    setError(null);
    setFinished(false);
  };

  if (finished) {
    return (
      <section className="card center">
        <h1>Subject created</h1>
        <p className="muted">
          <strong>{name.trim()}</strong> is ready. {items.length} file
          {items.length === 1 ? "" : "s"} uploaded. Processing for search comes next.
        </p>
        <div className="row">
          {subjectId && (
            <Link href={`/subjects/${subjectId}`} className="btn primary">
              Open subject
            </Link>
          )}
          <button className="btn" onClick={reset}>
            Create another
          </button>
        </div>
      </section>
    );
  }

  const formLocked = busy || subjectId !== null;

  return (
    <form className="card" onSubmit={submit} noValidate>
      <h1>New subject</h1>
      <p className="muted lead">
        Add the syllabus and reference material. Papers for this subject will answer from these
        files.
      </p>

      <label className="field">
        <span>Subject name</span>
        <input
          value={name}
          maxLength={NAME_MAX}
          placeholder="e.g. Operating Systems"
          disabled={formLocked}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
      </label>

      <label className="field">
        <span>
          Description <span className="muted">(optional)</span>
        </span>
        <textarea
          rows={2}
          value={description}
          placeholder="Course code, semester, anything that helps you find it later"
          disabled={formLocked}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>

      <div className="drops">
        <FileDrop
          label="Syllabus"
          tone="syllabus"
          hint="Sets scope and depth of answers"
          disabled={busy}
          onFiles={(f) => addFiles("syllabus", f)}
        />
        <FileDrop
          label="References"
          tone="reference"
          hint="Textbooks, notes, slides: the facts"
          disabled={busy}
          onFiles={(f) => addFiles("reference", f)}
        />
      </div>
      <p className="muted small">PDF, EPUB, DOCX, PPTX, PNG, JPG, TXT, MD. Up to 200 MB each.</p>

      {notices.length > 0 && (
        <ul className="notices" role="alert">
          {notices.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}

      <FileList
        items={items}
        locked={busy}
        onRemove={(id) => setItems((cur) => cur.filter((i) => i.id !== id))}
        onKind={(id, kind) => patch(id, { kind })}
      />

      {items.length > 0 && !hasSyllabus && (
        <p className="warn small">
          No syllabus file yet. Answers will not be scoped to a syllabus until you add one.
        </p>
      )}

      {error && (
        <p className="err" role="alert">
          {error}
        </p>
      )}

      <div className="row end">
        <button className="btn primary" type="submit" disabled={!nameOk || busy}>
          {busy
            ? "Uploading…"
            : subjectId
              ? `Retry ${pending.length} file${pending.length === 1 ? "" : "s"}`
              : "Create subject"}
        </button>
      </div>
    </form>
  );
}

export default function NewSubjectPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  return (
    <RequireRole role="admin">
      <NewSubjectForm courseId={courseId} />
    </RequireRole>
  );
}
