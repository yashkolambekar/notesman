"use client";

import { useState } from "react";

/** A heading with a Rename button for people who may edit it. `onSave` throws to show an error. */
export default function RenameTitle({
  value,
  canEdit,
  max,
  onSave,
  fallback = "",
}: {
  value: string;
  canEdit: boolean;
  max: number;
  onSave: (next: string) => Promise<void>;
  fallback?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!editing) {
    return (
      <h1 className="rename-title">
        {value || fallback}
        {canEdit && value && (
          <button
            type="button"
            className="rename-btn"
            onClick={() => {
              setDraft(value);
              setErr(null);
              setEditing(true);
            }}
          >
            Rename
          </button>
        )}
      </h1>
    );
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const next = draft.trim();
    if (!next || next === value) return setEditing(false);
    setBusy(true);
    setErr(null);
    try {
      await onSave(next);
      setEditing(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="rename-form">
      <div className="add-row">
        <input
          autoFocus
          value={draft}
          maxLength={max}
          aria-label="New name"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && setEditing(false)}
        />
        <button className="btn primary" disabled={busy || !draft.trim()}>
          Save
        </button>
        <button type="button" className="btn" onClick={() => setEditing(false)}>
          Cancel
        </button>
      </div>
      {err && <p className="err small" role="alert">{err}</p>}
    </form>
  );
}
