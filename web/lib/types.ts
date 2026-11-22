export type FileKind = "syllabus" | "reference";

export type PaperMeta = { id: string; title: string; locked: number; total: number };

export type Course = {
  id: string;
  name: string;
  description: string | null;
  subject_count: number;
  can_edit: boolean;
};

export type Quality = {
  avg: number; // 0-10, mean of the three examiner scores
  completeness: number;
  correctness: number;
  accuracy: number;
  checked: number; // answers that have been scored
};

export type Subject = {
  id: string;
  course_id: string;
  course_name: string;
  can_edit: boolean;
  name: string;
  description: string | null;
  syllabus_files: number;
  reference_files: number;
  papers: PaperMeta[];
  archived: boolean;
  archived_papers: PaperMeta[]; // only for admins of the subject
  quality: Quality | null;
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

export type Evaluation = {
  completeness: number;
  correctness: number;
  accuracy: number;
  summary: string;
  issues: string[];
  missing: string[];
  model: string;
  at: string;
};

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
  cost_usd: number | null; // admins only
  cost_calls: number | null;
  evaluation: Evaluation | null; // admins only
  evaluation_stale: boolean | null; // answer changed since it was scored
};

export type Paper = { id: string; subject_id: string; title: string; questions: Question[] };

export type KeyStatus = {
  gemini_set: boolean;
  gemini_hint: string | null;
  openrouter_set: boolean;
  openrouter_hint: string | null;
};

export type CourseSpend = {
  total_usd: number;
  by_admin: { name: string; cost_usd: number }[];
  papers: number;
  questions: number;
  embed_calls: number;
  chat_calls: number;
  input_tokens: number;
  output_tokens: number;
};

export type UsageBucket = { label: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number };
export type RecentCall = {
  at: string;
  purpose: string;
  model: string;
  cost_usd: number;
  estimated: boolean;
  subject: string | null;
  question: string | null;
  admin: string | null;
};
export type Usage = {
  scope: "own" | "all";
  total_usd: number;
  estimated_usd: number;
  by_purpose: UsageBucket[];
  by_subject: UsageBucket[];
  by_day: UsageBucket[];
  by_admin: UsageBucket[];
  recent: RecentCall[];
};
