"use client";

import { useState } from "react";
import { usd } from "@/lib/money";
import Md from "./Md";
import type { Question } from "@/lib/types";

const NUDGES = ["Shorter", "More detail", "Add example", "Simpler words"];

type Props = {
  q: Question;
  index: number;
  busy: boolean;
  onRegenerate: (steer: { nudges: string[]; comment: string }) => void;
  /** Set when the last attempt found nothing relevant in the files: offer to answer from general knowledge. */
  noMaterial?: boolean;
  onAnswerAnyway?: () => void;
  onSave: (answer: string) => Promise<void>;
  onLock: () => void;
  onUnlock: () => void;
  onDelete: () => void;
};

export default function QuestionPanel({
  q,
  index,
  busy,
  onRegenerate,
  noMaterial,
  onAnswerAnyway,
  onSave,
  onLock,
  onUnlock,
  onDelete,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(q.answer_md);
  const [picked, setPicked] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const locked = q.status === "locked";
  const hasSteer = picked.length > 0 || comment.trim().length > 0;
  const hasAnswer = q.answer_md.trim().length > 0;
  const steer = q.last_steer
    ? [...q.last_steer.nudges, q.last_steer.comment].filter(Boolean).join(" · ")
    : "";

  const regenerate = () => {
    onRegenerate({ nudges: picked, comment: comment.trim() });
    setPicked([]);
    setComment("");
  };

  return (
    <aside className="panel">
      <div className="panel-head">
        <span className="eyebrow">Question {index + 1}</span>
        <span className={`chip ${q.status}`}>{locked ? "Locked" : "Draft"}</span>
      </div>
      <p className="panel-prompt">{q.prompt}</p>

      {q.syllabus_match && (
        <div className="match">
          <span className="eyebrow">Syllabus match</span>
          <span>{q.syllabus_match}</span>
        </div>
      )}

      {q.sources.length > 0 && (
        <div className="panel-section">
          <span className="eyebrow">Sources</span>
          <ul className="sources">
            {q.sources.map((s, i) => (
              <li key={i}>
                <span className="src-file">
                  [{s.n ?? i + 1}] {s.file} {s.page != null && <em>p. {s.page}</em>}
                  {s.section && <em> · {s.section}</em>}
                </span>
                <span className="src-snippet">“{s.snippet}”</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {locked ? (
        <div className="panel-section">
          <p className="muted small">
            This answer is locked and appears in the printed paper. Unlock it to regenerate or edit.
          </p>
          <button type="button" className="btn wide" disabled={busy} onClick={onUnlock}>
            Unlock
          </button>
        </div>
      ) : editing ? (
        <div className="panel-section">
          <span className="eyebrow">{hasAnswer ? "Edit answer (Markdown)" : "Write the answer (Markdown)"}</span>
          <textarea className="editor" rows={12} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row">
            <button
              type="button"
              className="btn primary"
              disabled={busy}
              onClick={async () => {
                await onSave(text);
                setEditing(false);
              }}
            >
              Save
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setText(q.answer_md);
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="panel-section">
          <span className="eyebrow">Steer the next answer</span>
          <div className="nudges">
            {NUDGES.map((n) => {
              const on = picked.includes(n);
              return (
                <button
                  key={n}
                  type="button"
                  className={`tag${on ? " on" : ""}`}
                  aria-pressed={on}
                  disabled={busy}
                  onClick={() => setPicked((cur) => (on ? cur.filter((x) => x !== n) : [...cur, n]))}
                >
                  {n}
                </button>
              );
            })}
          </div>
          <textarea
            className="steer"
            rows={3}
            value={comment}
            disabled={busy}
            placeholder="Your comment, e.g. “Use the PCB diagram from the notes and keep it under 100 words.”"
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !busy) regenerate();
            }}
          />
          {q.cost_usd !== null && q.cost_calls ? (
            <p className="muted small last-steer">
              Cost so far {usd(q.cost_usd)} · {q.cost_calls} call{q.cost_calls === 1 ? "" : "s"}
            </p>
          ) : null}
          {steer && (
            <p className="muted small last-steer">
              Last steer: <em>{steer}</em>
            </p>
          )}
          {noMaterial && (
            <p className="banner" role="alert">
              <span>
                Nothing in this subject&apos;s files is relevant to this question. Reword it, upload material that covers
                it, or answer anyway from general knowledge (marked with a warning, no sources).
              </span>
              <button type="button" className="btn primary" disabled={busy} onClick={onAnswerAnyway}>
                Answer anyway
              </button>
            </p>
          )}
          <div className="row">
            <button type="button" className="btn" disabled={busy} onClick={regenerate}>
              {busy ? "Working…" : hasAnswer ? (hasSteer ? "Regenerate with notes" : "Regenerate") : "Find answer"}
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => {
                setText(q.answer_md);
                setEditing(true);
              }}
            >
              {hasAnswer ? "Edit" : "Write"}
            </button>
            <button type="button" className="btn primary" disabled={busy || !hasAnswer} onClick={onLock}>
              Lock
            </button>
          </div>
        </div>
      )}

      {!locked && !editing && (
        <button type="button" className="link-danger" disabled={busy} onClick={onDelete}>
          Delete question
        </button>
      )}

      {q.previous_answer_md && !locked && (
        <details className="prev">
          <summary>Previously locked text</summary>
          <Md>{q.previous_answer_md}</Md>
        </details>
      )}
    </aside>
  );
}
