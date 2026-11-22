"use client";

import { useAuth } from "@/components/AuthProvider";
import { getUsage } from "@/lib/api";
import { usd } from "@/lib/money";
import type { UsageBucket } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const label: Record<string, string> = {
  answer: "Answer",
  fix: "Answer repair",
  grounding: "Grounding check",
  rewrite: "Query rewrite",
  rerank: "Rerank",
  embed_query: "Embed question",
  embed_doc: "Embed files",
};

function Table({ title, rows, nice }: { title: string; rows: UsageBucket[]; nice?: boolean }) {
  if (rows.length === 0) return null;
  return (
    <div className="card top-gap">
      <h2 className="h2">{title}</h2>
      <table className="usage-table">
        <thead>
          <tr>
            <th>{title.replace("By ", "")}</th>
            <th className="num">Calls</th>
            <th className="num">Tokens in / out</th>
            <th className="num">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <td>{nice ? (label[r.label] ?? r.label) : r.label}</td>
              <td className="num">{r.calls}</td>
              <td className="num">
                {r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}
              </td>
              <td className="num">{usd(r.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function UsagePage() {
  const { user, loading: authLoading } = useAuth();
  const usage = useApi(getUsage, [user?.id], !authLoading && !!user);

  if (authLoading || (user && usage.loading)) return <p className="muted">Loading…</p>;
  if (!user) return <p className="muted">Sign in to see spending.</p>;
  if (usage.error) return <p className="err">{usage.error}</p>;
  const u = usage.data!;

  return (
    <section className="subject-page">
      <header className="page-head">
        <div>
          <h1>Spending</h1>
          <p className="muted">
            {u.scope === "all" ? "Everything spent through all admins' keys." : "What your own keys have spent."} Chat
            costs are reported by OpenRouter; embedding costs are estimated from text length and the configured price
            {u.estimated_usd > 0 && <> ({usd(u.estimated_usd)} of the total is estimated)</>}.
          </p>
        </div>
        <div>
          <span className="muted small">Total</span>
          <h1>{usd(u.total_usd)}</h1>
        </div>
      </header>

      <Table title="By purpose" rows={u.by_purpose} nice />
      {u.scope === "all" && <Table title="By admin" rows={u.by_admin} />}
      <Table title="By subject" rows={u.by_subject} />
      <Table title="By day (last 30 days)" rows={u.by_day} />

      {u.recent.length > 0 ? (
        <div className="card top-gap">
          <h2 className="h2">Recent calls</h2>
          <table className="usage-table">
            <thead>
              <tr>
                <th>When</th>
                <th>What</th>
                <th>For</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {u.recent.map((r, i) => (
                <tr key={i}>
                  <td>{new Date(r.at).toLocaleString()}</td>
                  <td>
                    {label[r.purpose] ?? r.purpose}
                    {r.admin && <span className="muted small"> · {r.admin}</span>}
                  </td>
                  <td>{r.question ?? r.subject ?? "—"}</td>
                  <td className="num">
                    {usd(r.cost_usd)}
                    {r.estimated && <span className="muted small"> est.</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted top-gap">Nothing spent yet.</p>
      )}
    </section>
  );
}
