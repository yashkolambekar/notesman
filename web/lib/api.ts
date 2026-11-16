import type { FileKind, Paper, PaperMeta, Question, Subject, SubjectFile } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api"; // proxied to the FastAPI server by next.config.ts

async function detail(res: Response): Promise<string> {
  try {
    const j = await res.json();
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d: { msg: string }) => d.msg).join(", ");
  } catch {}
  return `Request failed (${res.status})`;
}

async function req<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return res.status === 204 ? (undefined as T) : res.json();
}

const post = <T>(path: string, json: unknown = {}) => req<T>(path, { method: "POST", json });

// subjects
export const listSubjects = () => req<Subject[]>("/v1/subjects");
export const getSubject = (id: string) => req<Subject>(`/v1/subjects/${id}`);
export const createSubject = (input: { name: string; description?: string }) =>
  post<Subject>("/v1/subjects", input);
export const deleteSubject = (id: string) => req<void>(`/v1/subjects/${id}`, { method: "DELETE" });

// files
export const listFiles = (subjectId: string) => req<SubjectFile[]>(`/v1/subjects/${subjectId}/files`);
export const retryFile = (id: string) => post<SubjectFile>(`/v1/files/${id}/retry`);
export const deleteFile = (id: string) => req<void>(`/v1/files/${id}`, { method: "DELETE" });

export function uploadFile(
  subjectId: string,
  file: File,
  kind: FileKind,
  onProgress: (pct: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/v1/subjects/${subjectId}/files`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      let msg = `Upload failed (${xhr.status})`;
      try {
        const d = JSON.parse(xhr.responseText).detail;
        if (typeof d === "string") msg = d;
      } catch {}
      reject(new ApiError(xhr.status, msg));
    };
    xhr.onerror = () => reject(new Error("Network error"));
    const body = new FormData();
    body.append("file", file);
    body.append("kind", kind);
    xhr.send(body);
  });
}

// papers
export const createPaper = (subjectId: string, title: string) =>
  post<PaperMeta>(`/v1/subjects/${subjectId}/papers`, { title });
export const getPaper = (id: string) => req<Paper>(`/v1/papers/${id}`);
export const deletePaper = (id: string) => req<void>(`/v1/papers/${id}`, { method: "DELETE" });
export const exportUrl = (paperId: string) => `${BASE}/v1/papers/${paperId}/export`;

// questions
export const addQuestion = (paperId: string, prompt: string) =>
  post<Question>(`/v1/papers/${paperId}/questions`, { prompt });
export const saveAnswer = (id: string, answer_md: string) =>
  req<Question>(`/v1/questions/${id}`, { method: "PATCH", json: { answer_md } });
export const lockQuestion = (id: string) => post<Question>(`/v1/questions/${id}/lock`);
export const unlockQuestion = (id: string) => post<Question>(`/v1/questions/${id}/unlock`);
export const moveQuestion = (id: string, beforeId: string | null) =>
  post<Question>(`/v1/questions/${id}/move`, { before_id: beforeId });
export const deleteQuestion = (id: string) => req<void>(`/v1/questions/${id}`, { method: "DELETE" });
export const generateAnswer = (id: string, steer: { nudges: string[]; comment: string }) =>
  post<Question>(`/v1/questions/${id}/generate`, steer);
