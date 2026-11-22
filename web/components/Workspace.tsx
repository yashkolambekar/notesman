"use client";

import { useEffect, useState } from "react";
import Md from "./Md";
import RenameTitle from "./RenameTitle";
import { usd } from "@/lib/money";
import Sidebar from "./Sidebar";
import QuestionPanel from "./QuestionPanel";
import {
  addQuestion,
  deleteQuestion,
  exportUrl,
  generateAnswer,
  lockQuestion,
  moveQuestion,
  renamePaper,
  saveAnswer,
  unlockQuestion,
} from "@/lib/api";
import type { Paper, Question, Subject } from "@/lib/types";

/** Citations like [1] stay on the server for the sources panel but never show in the paper. */
const stripCites = (md: string) => md.replace(/[ \t]?\[\d+\](?!\()/g, "");

type Props = { subject: Subject; paper: Paper };

export default function Workspace({ subject, paper }: Props) {
  const canWrite = subject.can_edit;
  const [preview, setPreview] = useState(false);
  // Non-admins (and anyone while auth is loading) only ever get the read-only view.
  const reader = !canWrite || preview;

  const [title, setTitle] = useState(paper.title);
  const [qs, setQs] = useState<Question[]>(paper.questions);
  const [activeId, setActiveId] = useState<string | null>(
    paper.questions.find((q) => q.status === "draft")?.id ?? paper.questions[0]?.id ?? null,
  );
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | "end" | null>(null);
  const [site, setSite] = useState(process.env.NEXT_PUBLIC_SITE_URL ?? "");
  useEffect(() => {
    if (!site) setSite(window.location.origin);
  }, [site]);

  const replace = (q: Question) => setQs((cur) => cur.map((x) => (x.id === q.id ? q : x)));

  /** Run an API call for one question, with a busy flag and an error banner. */
  const run = async <T,>(id: string, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy((b) => new Set(b).add(id));
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy((b) => {
        const n = new Set(b);
        n.delete(id);
        return n;
      });
    }
  };

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const prompt = draft.trim();
    if (!prompt || adding) return;
    setAdding(true);
    setError(null);
    try {
      const q = await addQuestion(paper.id, prompt);
      setQs((cur) => [...cur, q]);
      setActiveId(q.id);
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add question");
    } finally {
      setAdding(false);
    }
  };

  const regenerate = async (id: string, steer: { nudges: string[]; comment: string }) => {
    const q = await run(id, () => generateAnswer(id, steer));
    if (q) replace(q);
  };
  const save = async (id: string, answer: string) => {
    const q = await run(id, () => saveAnswer(id, answer));
    if (q) replace(q);
  };
  const lock = async (id: string) => {
    const q = await run(id, () => lockQuestion(id));
    if (q) replace(q);
  };
  const unlock = async (id: string) => {
    const q = await run(id, () => unlockQuestion(id));
    if (q) replace(q);
  };
  const remove = async (id: string) => {
    const ok = await run(id, () => deleteQuestion(id).then(() => true));
    if (!ok) return;
    const next = qs.filter((q) => q.id !== id);
    setQs(next);
    if (activeId === id) setActiveId(next[0]?.id ?? null);
  };

  /** Drop the dragged question before `target` (or at the end). One-row write on the server. */
  const drop = async () => {
    const id = dragId;
    const target = overId;
    setDragId(null);
    setOverId(null);
    if (!id || !target || target === id) return;

    const before = qs;
    const moving = qs.find((q) => q.id === id)!;
    const rest = qs.filter((q) => q.id !== id);
    const at = target === "end" ? rest.length : rest.findIndex((q) => q.id === target);
    if (at < 0) return;
    setQs([...rest.slice(0, at), moving, ...rest.slice(at)]); // optimistic
    try {
      await moveQuestion(id, target === "end" ? null : target);
    } catch (e) {
      setQs(before);
      setError(e instanceof Error ? e.message : "Could not reorder");
    }
  };

  const shown = reader ? qs.filter((q) => q.status === "locked") : qs;
  const lockedCount = qs.filter((q) => q.status === "locked").length;
  const activeIndex = qs.findIndex((q) => q.id === activeId);
  const active = activeIndex >= 0 ? qs[activeIndex] : null;

  return (
    <div className={`work${reader ? " reader" : ""}`}>
      <Sidebar
        subject={subject}
        paperId={paper.id}
        canWrite={!reader}
        currentTitle={title}
        current={{ locked: lockedCount, total: reader ? lockedCount : qs.length }}
      />

      <section className="doc-wrap">
        <div className="doc-bar">
          {canWrite ? (
            <div className="role-toggle" role="group" aria-label="View mode">
              <button type="button" className={!reader ? "on" : ""} onClick={() => setPreview(false)}>
                Admin
              </button>
              <button type="button" className={reader ? "on" : ""} onClick={() => setPreview(true)}>
                Reader
              </button>
            </div>
          ) : (
            <span />
          )}
          <div className="row tight">
            <button type="button" className="btn" onClick={() => window.print()}>
              Print
            </button>
            <a className="btn" href={exportUrl(paper.id)} download>
              Export .md
            </a>
          </div>
        </div>

        {error && (
          <p className="banner err" role="alert">
            {error}
            <button type="button" className="icon" aria-label="Dismiss" onClick={() => setError(null)}>
              ×
            </button>
          </p>
        )}

        <article className="doc">
          <div className="print-brand">
            <span className="print-name">Notesman</span>
            <a href={site || "/"}>{site || "notesman"}</a>
          </div>
          <header className="doc-head">
            <span className="eyebrow">{subject.name}</span>
            <RenameTitle
              value={title}
              canEdit={!reader}
              max={200}
              onSave={async (n) => {
                await renamePaper(paper.id, n);
                setTitle(n);
              }}
            />
            <p className="muted small">
              {shown.length} question{shown.length === 1 ? "" : "s"}
              {!reader && ` · ${lockedCount} locked, ${qs.length - lockedCount} draft`}
              {!reader && ` · ${usd(qs.reduce((n, q) => n + (q.cost_usd ?? 0), 0))} spent`}
            </p>
          </header>

          {shown.length === 0 && (
            <p className="muted empty-doc">
              {reader
                ? "Nothing has been finalised in this paper yet."
                : "No questions yet. Add the first one below."}
            </p>
          )}

          <ol className={`qs${qs.some((q) => q.status === "locked") ? "" : " print-all"}`}>
            {shown.map((q, i) => {
              const isActive = !reader && q.id === activeId;
              return (
                <li
                  key={q.id}
                  className={`q ${q.status}${isActive ? " active" : ""}${
                    overId === q.id && dragId !== q.id ? " drop-target" : ""
                  }${dragId === q.id ? " dragging" : ""}`}
                  draggable={!reader}
                  onDragStart={() => setDragId(q.id)}
                  onDragOver={(e) => {
                    if (!dragId) return;
                    e.preventDefault();
                    setOverId(q.id);
                  }}
                  onDrop={drop}
                  onDragEnd={() => {
                    setDragId(null);
                    setOverId(null);
                  }}
                  onClick={() => !reader && setActiveId(q.id)}
                >
                  <div className="q-head">
                    {!reader && (
                      <span className="grip" aria-hidden title="Drag to reorder">
                        ⋮⋮
                      </span>
                    )}
                    <span className="q-num">{i + 1}.</span>
                    <h2 className="q-prompt">{q.prompt}</h2>
                    {!reader && (
                      <span className={`chip ${q.status}`}>{q.status === "locked" ? "Locked" : "Draft"}</span>
                    )}
                  </div>
                  <div className="q-body">
                    {busy.has(q.id) ? (
                      <p className="muted thinking">Working…</p>
                    ) : q.answer_md.trim() ? (
                      <Md>{stripCites(q.answer_md)}</Md>
                    ) : (
                      <p className="muted no-answer">No answer yet.</p>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>

          {dragId && (
            <div
              className={`end-drop${overId === "end" ? " over" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setOverId("end");
              }}
              onDrop={drop}
            >
              Drop here to move to the end
            </div>
          )}

          {!reader && (
            <form className="add-q" onSubmit={add}>
              <label htmlFor="newq" className="eyebrow">
                Add a question
              </label>
              <div className="add-row">
                <input
                  id="newq"
                  value={draft}
                  maxLength={2000}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Type the next question and press Enter"
                />
                <button type="submit" className="btn primary" disabled={!draft.trim() || adding}>
                  {adding ? "Adding…" : "Add"}
                </button>
              </div>
            </form>
          )}
        </article>
      </section>

      <footer className="print-foot">
        Made with <a href={site || "/"}>Notesman</a>
        {site && <> · {site.replace(/^https?:\/\//, "")}</>}
      </footer>

      {!reader && active && (
        <QuestionPanel
          key={active.id + active.status}
          q={active}
          index={activeIndex}
          busy={busy.has(active.id)}
          onRegenerate={(s) => regenerate(active.id, s)}
          onSave={(a) => save(active.id, a)}
          onLock={() => lock(active.id)}
          onUnlock={() => unlock(active.id)}
          onDelete={() => remove(active.id)}
        />
      )}
    </div>
  );
}
