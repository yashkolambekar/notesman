"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { createPaper } from "@/lib/api";
import type { Subject } from "@/lib/types";

type Props = {
  subject: Subject;
  paperId: string;
  canWrite: boolean;
  /** Live counts for the open paper, so the list stays right while you edit. */
  current?: { locked: number; total: number };
};

export default function Sidebar({ subject, paperId, canWrite, current }: Props) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const p = await createPaper(subject.id, title.trim());
      router.push(`/subjects/${subject.id}/papers/${p.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create paper");
      setBusy(false);
    }
  };

  return (
    <aside className="side">
      <Link href="/subjects" className="back">
        ← All subjects
      </Link>

      <div className="side-block subject-card">
        <span className="eyebrow">Subject</span>
        <Link href={`/subjects/${subject.id}`} className="subject-name">
          {subject.name}
        </Link>
        <span className="muted small">
          {subject.syllabus_files} syllabus · {subject.reference_files} references
        </span>
      </div>

      <div className="side-block">
        <span className="eyebrow">Papers</span>
        {subject.papers.length === 0 && <p className="muted small">No papers yet.</p>}
        <ul className="paper-list">
          {subject.papers.map((p) => {
            const counts = p.id === paperId && current ? current : p;
            return (
              <li key={p.id}>
                <Link
                  href={`/subjects/${subject.id}/papers/${p.id}`}
                  className={p.id === paperId ? "active" : ""}
                >
                  <span className="paper-title">{p.title}</span>
                  <span className="muted small">
                    {counts.total === 0
                      ? "empty"
                      : canWrite
                        ? `${counts.locked}/${counts.total} locked`
                        : `${counts.total} question${counts.total === 1 ? "" : "s"}`}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>

        {canWrite &&
          (adding ? (
            <form onSubmit={add} className="new-paper">
              <input
                autoFocus
                value={title}
                maxLength={200}
                placeholder="Paper title"
                onChange={(e) => setTitle(e.target.value)}
              />
              <div className="row tight">
                <button className="btn primary" type="submit" disabled={!title.trim() || busy}>
                  Create
                </button>
                <button className="btn" type="button" onClick={() => setAdding(false)}>
                  Cancel
                </button>
              </div>
              {error && <p className="err small">{error}</p>}
            </form>
          ) : (
            <button type="button" className="btn ghost wide" onClick={() => setAdding(true)}>
              + New paper
            </button>
          ))}
      </div>
    </aside>
  );
}
