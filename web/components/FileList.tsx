"use client";

import { formatSize } from "@/lib/files";
import type { FileKind } from "@/lib/types";

export type Item = {
  id: string;
  file: File;
  kind: FileKind;
  status: "pending" | "uploading" | "done" | "error";
  progress: number;
  error?: string;
};

type Props = {
  items: Item[];
  locked: boolean;
  onRemove: (id: string) => void;
  onKind: (id: string, kind: FileKind) => void;
};

export default function FileList({ items, locked, onRemove, onKind }: Props) {
  if (!items.length) return <p className="muted empty">No files added yet.</p>;

  return (
    <ul className="files">
      {items.map((it) => (
        <li key={it.id} className={`file ${it.status}`}>
          <div className="file-main">
            <span className="file-name" title={it.file.name}>
              {it.file.name}
            </span>
            <span className="muted">{formatSize(it.file.size)}</span>
          </div>

          <select
            data-kind={it.kind}
            aria-label={`Kind of ${it.file.name}`}
            value={it.kind}
            disabled={locked}
            onChange={(e) => onKind(it.id, e.target.value as FileKind)}
          >
            <option value="syllabus">Syllabus</option>
            <option value="reference">Reference</option>
          </select>

          <div className="file-status">
            {it.status === "pending" && <span className="muted">Ready</span>}
            {it.status === "uploading" && (
              <progress max={100} value={it.progress} aria-label="Upload progress" />
            )}
            {it.status === "done" && <span className="ok">Uploaded</span>}
            {it.status === "error" && (
              <span className="err" title={it.error}>
                {it.error ?? "Failed"}
              </span>
            )}
          </div>

          <button
            type="button"
            className="icon"
            aria-label={`Remove ${it.file.name}`}
            disabled={locked && it.status !== "error"}
            onClick={() => onRemove(it.id)}
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  );
}
