"use client";

import { memo, useState } from "react";

/** Owns the text being typed, so a keystroke re-renders only this form and not the whole paper. */
function AddQuestion({ onAdd }: { onAdd: (prompt: string) => Promise<boolean> }) {
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const prompt = draft.trim();
    if (!prompt || adding) return;
    setAdding(true);
    try {
      if (await onAdd(prompt)) setDraft("");
    } finally {
      setAdding(false);
    }
  };

  return (
    <form className="add-q" onSubmit={submit}>
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
  );
}

export default memo(AddQuestion);
