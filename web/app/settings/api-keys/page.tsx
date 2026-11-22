"use client";

import { useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { getApiKeys, saveApiKeys } from "@/lib/api";
import { useApi } from "@/lib/useApi";

type Name = "gemini" | "openrouter";

const PROVIDERS: { name: Name; label: string; what: string; href: string }[] = [
  { name: "gemini", label: "Gemini API key", what: "Embeds the files you upload.", href: "https://aistudio.google.com/apikey" },
  { name: "openrouter", label: "OpenRouter API key", what: "Writes the answers.", href: "https://openrouter.ai/keys" },
];

export default function ApiKeysPage() {
  const { user, loading: authLoading } = useAuth();
  const status = useApi(getApiKeys, [user?.id], !authLoading && !!user);
  const [values, setValues] = useState<Record<Name, string>>({ gemini: "", openrouter: "" });
  const [busy, setBusy] = useState<Name | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const save = async (name: Name, value: string) => {
    setBusy(name);
    setMsg(null);
    try {
      status.setData(await saveApiKeys({ [name]: value }));
      setValues((v) => ({ ...v, [name]: "" }));
      setMsg({ ok: true, text: value ? "Key saved." : "Key removed." });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Something went wrong" });
    } finally {
      setBusy(null);
    }
  };

  if (authLoading || (user && status.loading)) return <p className="muted">Loading…</p>;
  if (!user) return <p className="muted">Sign in to manage your API keys.</p>;
  if (status.error) return <p className="err">{status.error}</p>;
  const st = status.data!;

  return (
    <section className="subject-page">
      <header className="page-head">
        <div>
          <h1>API keys</h1>
          <p className="muted">
            Uploads and answer generation run on your own keys, never anyone else&apos;s. Keys are stored encrypted and
            are only decrypted to make a request. They are never shown again.
          </p>
        </div>
      </header>

      {msg && (
        <p className={`banner ${msg.ok ? "ok" : "err"}`} role={msg.ok ? "status" : "alert"}>
          {msg.text}
        </p>
      )}

      <div className="card">
        {PROVIDERS.map((p) => {
          const isSet = st[`${p.name}_set`];
          const hint = st[`${p.name}_hint`];
          return (
            <form
              key={p.name}
              className="key-row"
              onSubmit={(e) => {
                e.preventDefault();
                if (values[p.name].trim()) save(p.name, values[p.name].trim());
              }}
            >
              <label className="field" style={{ marginBottom: 0 }}>
                <span>{p.label}</span>
                <span className="muted small" style={{ fontWeight: 400 }}>
                  {p.what}{" "}
                  <a href={p.href} target="_blank" rel="noreferrer">
                    Get a key
                  </a>
                </span>
              </label>
              <div className="add-row">
                <input
                  type="password"
                  autoComplete="off"
                  aria-label={p.label}
                  placeholder={isSet ? "Paste a new key to replace it" : "Paste your key"}
                  value={values[p.name]}
                  onChange={(e) => setValues((v) => ({ ...v, [p.name]: e.target.value }))}
                />
                <button className="btn primary" disabled={!values[p.name].trim() || busy === p.name}>
                  {isSet ? "Replace" : "Save"}
                </button>
                {isSet && (
                  <button type="button" className="link-danger" disabled={busy === p.name} onClick={() => save(p.name, "")}>
                    Remove
                  </button>
                )}
              </div>
              <span className={`key-state ${isSet ? "ok" : "muted"}`}>
                {isSet ? `Saved (ends in ${hint})` : "Not set"}
              </span>
            </form>
          );
        })}
      </div>
    </section>
  );
}
