"use client";

import { use } from "react";
import { useAuth } from "@/components/AuthProvider";
import Workspace from "@/components/Workspace";
import { getPaper, getSubject } from "@/lib/api";
import { useApi } from "@/lib/useApi";

export default function PaperPage({
  params,
}: {
  params: Promise<{ subjectId: string; paperId: string }>;
}) {
  const { subjectId, paperId } = use(params);
  const { user, loading: authLoading } = useAuth();

  // Wait for auth first, so an admin's first load already includes drafts.
  const { data, error, loading } = useApi(
    () => Promise.all([getSubject(subjectId), getPaper(paperId)]),
    [subjectId, paperId, user?.id],
    !authLoading,
  );

  if (authLoading || loading) return <p className="muted">Loading…</p>;
  if (error || !data) return <p className="err">{error ?? "Not found"}</p>;

  const [subject, paper] = data;
  return <Workspace key={`${paper.id}:${user?.id ?? "anon"}`} subject={subject} paper={paper} />;
}
