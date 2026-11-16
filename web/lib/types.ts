export type FileKind = "syllabus" | "reference";

export type PaperMeta = { id: string; title: string; locked: number; total: number };

export type Subject = {
  id: string;
  name: string;
  description: string | null;
  syllabus_files: number;
  reference_files: number;
  papers: PaperMeta[];
};

export type SubjectFile = {
  id: string;
  kind: FileKind;
  filename: string;
  size_bytes: number;
  status: "queued" | "processing" | "ready" | "failed";
  error: string | null;
  chunk_count: number | null;
  created_at: string;
};

export type Source = { n?: number; file: string; page: number | null; section?: string; snippet: string };

export type Question = {
  id: string;
  position: string;
  prompt: string;
  answer_md: string;
  status: "draft" | "locked";
  syllabus_match: string | null;
  sources: Source[];
  previous_answer_md: string | null;
  last_steer: { nudges: string[]; comment: string } | null;
};

export type Paper = { id: string; subject_id: string; title: string; questions: Question[] };
