"use client";

import { useRef, useState } from "react";
import { ACCEPT } from "@/lib/files";

type Props = {
  label: string;
  hint: string;
  disabled?: boolean;
  tone: "syllabus" | "reference";
  onFiles: (files: File[]) => void;
};

export default function FileDrop({ label, hint, disabled, tone, onFiles }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const take = (list: FileList | null) => {
    if (list && list.length) onFiles(Array.from(list));
    if (input.current) input.current.value = "";
  };

  return (
    <div
      className={`drop tone-${tone}${over ? " over" : ""}${disabled ? " disabled" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!disabled) take(e.dataTransfer.files);
      }}
    >
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={ACCEPT.extensions.join(",")}
        disabled={disabled}
        onChange={(e) => take(e.target.files)}
      />
      <strong>{label}</strong>
      <span className="muted">{hint}</span>
      <button
        type="button"
        className="btn ghost"
        disabled={disabled}
        onClick={() => input.current?.click()}
      >
        Choose files
      </button>
    </div>
  );
}
