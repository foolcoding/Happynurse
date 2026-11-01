"use client";

import { useCallback, useEffect, useState } from "react";

// 관리자: 지침 PDF를 끌어다 놓으면 검사를 거쳐 통과한 판이 승인 대기로 오고, 관리자가 반영해야 검색에 들어간다

type Check = {
  name: string;
  value: string | number;
  limit: string;
  ok: boolean;
};
type Entry = {
  live: { version: string; chunks: number; updated_at: string } | null;
  job: {
    status:
      | "queued"
      | "processing"
      | "pending"
      | "live"
      | "failed"
      | "rejected";
    step: string | null;
    version: string;
    file: string;
    checks: Check[];
    error: string | null;
    chunks?: number;
    updated_at: string;
  } | null;
};

const STATUS: Record<string, string> = {
  queued: "대기",
  processing: "처리 중",
  pending: "승인 대기",
  live: "반영됨",
  failed: "검사 실패",
  rejected: "반려됨",
};

export default function Admin() {
  const [docs, setDocs] = useState<Record<string, Entry>>({});
  const [file, setFile] = useState<File | null>(null);
  const [form, setForm] = useState({ doc_id: "", version: "", exclude: "" });
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState("");
  const [over, setOver] = useState(false);

  const load = useCallback(async () => {
    const r = await fetch("/api/documents");
    if (r.ok) setDocs(await r.json());
  }, []);

  useEffect(() => {
    setToken(sessionStorage.getItem("adminToken") ?? ""); // 탭을 닫으면 사라짐
    load();
  }, [load]);

  // 처리 중인 작업이 있을 때만 2초마다 상태 확인
  const running = Object.values(docs).some(
    (d) => d.job?.status === "queued" || d.job?.status === "processing",
  );
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [running, load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    sessionStorage.setItem("adminToken", token);
    const body = new FormData();
    body.append("file", file);
    Object.entries(form).forEach(([k, v]) => body.append(k, v));
    setMsg("올리는 중…");
    const r = await fetch("/api/documents", {
      method: "POST",
      body,
      headers: { "X-Admin-Token": token },
    });
    const data = await r.json().catch(() => ({}));
    setMsg(
      r.ok
        ? data.status === "skipped"
          ? "운영 중인 판과 같은 파일이라 건너뜀"
          : "접수됨. 검사를 통과하면 아래에서 승인할 수 있습니다."
        : `거부됨: ${data.detail ?? r.status}`,
    );
    if (r.ok) setFile(null);
    load();
  }

  async function decide(id: string, decision: "approve" | "reject") {
    const r = await fetch(`/api/documents/${id}/${decision}`, {
      method: "POST",
      headers: { "X-Admin-Token": token },
    });
    const data = await r.json().catch(() => ({}));
    setMsg(r.ok ? "" : `처리 안 됨: ${data.detail ?? r.status}`);
    load();
  }

  const input =
    "w-full rounded-lg border border-border-base bg-surface-base px-3 py-2 text-body-sm outline-none focus:border-brand-primary";

  return (
    <main className="mx-auto min-h-dvh max-w-[720px] space-y-6 bg-surface-base px-5 py-6">
      <header className="flex items-end justify-between">
        <div>
          <p className="text-body-micro text-content-muted">
            HappyNurse 감염관리 지침 도우미
          </p>
          <h1 className="text-title-md font-bold">지침 문서 관리</h1>
        </div>
        <a href="/" className="text-body-xs font-semibold text-brand-primary">
          챗봇으로
        </a>
      </header>

      <form
        onSubmit={submit}
        className="space-y-3 rounded-xl border border-border-subtle bg-surface-card p-4"
      >
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            setFile(e.dataTransfer.files[0] ?? null);
          }}
          className={`block cursor-pointer rounded-lg border-2 border-dashed px-4 py-8 text-center text-body-sm ${
            over
              ? "border-brand-primary bg-brand-surface"
              : "border-border-base"
          }`}
        >
          {file
            ? `${file.name} (${(file.size / 1048576).toFixed(1)}MB)`
            : "PDF를 여기에 끌어다 놓거나 눌러서 선택"}
          <input
            type="file"
            accept="application/pdf"
            className="sr-only"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            required
            list="doc-ids"
            placeholder="문서 ID (개정판이면 기존 ID 선택)"
            value={form.doc_id}
            onChange={(e) => setForm({ ...form, doc_id: e.target.value })}
            className={input}
          />
          <datalist id="doc-ids">
            {Object.keys(docs).map((id) => (
              <option key={id} value={id} />
            ))}
          </datalist>
          <input
            required
            placeholder="판 (예: 2026 개정판)"
            value={form.version}
            onChange={(e) => setForm({ ...form, version: e.target.value })}
            className={input}
          />
          <input
            placeholder="제외할 쪽 (예: 151-160, 271-323)"
            value={form.exclude}
            onChange={(e) => setForm({ ...form, exclude: e.target.value })}
            className={input}
          />
          <input
            type="password"
            required
            placeholder="관리자 토큰"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className={input}
          />
        </div>
        <div className="flex items-center gap-3">
          <button
            disabled={!file}
            className="rounded-lg bg-brand-primary px-4 py-2 text-body-sm font-semibold text-white disabled:opacity-40"
          >
            올리기
          </button>
          <p className="text-body-xs text-content-secondary">{msg}</p>
        </div>
      </form>

      <section className="space-y-3">
        {Object.entries(docs).map(([id, d]) => (
          <article
            key={id}
            className="rounded-xl border border-border-subtle bg-surface-card p-4 text-body-sm"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-bold">{id}</h2>
              <span className="text-body-xs text-content-muted">
                운영 중:{" "}
                {d.live
                  ? `${d.live.version} · 청크 ${d.live.chunks}개`
                  : "없음"}
              </span>
            </div>
            {d.job && (
              <div className="mt-2 space-y-2">
                <p>
                  <b
                    className={
                      d.job.status === "failed" || d.job.status === "rejected"
                        ? "text-status-danger"
                        : "text-brand-primary"
                    }
                  >
                    {STATUS[d.job.status]}
                  </b>{" "}
                  {d.job.version} · {d.job.file}
                  {d.job.step &&
                    d.job.status === "processing" &&
                    ` · ${d.job.step} 단계`}
                  <span className="ml-2 text-body-micro text-content-muted">
                    {d.job.updated_at}
                  </span>
                </p>
                {/* 검사 실패는 아래 항목으로 보이므로, 오류 문구는 파서·Ollama 오류처럼 검사 밖에서 난 경우만 */}
                {d.job.error && d.job.checks.every((c) => c.ok) && (
                  <p className="text-body-xs text-status-danger">
                    {d.job.error}
                  </p>
                )}
                {d.job.status === "pending" && (
                  <div className="flex flex-wrap items-center gap-2 rounded-lg bg-brand-surface px-3 py-2">
                    <p className="flex-1 text-body-xs text-sub-primary">
                      검사를 모두 통과했습니다 (청크 {d.job.chunks}개). 감염관리
                      지침 문서가 맞는지 확인 후 반영하세요.
                    </p>
                    <button
                      type="button"
                      onClick={() => decide(id, "reject")}
                      className="rounded-lg border border-border-base px-3 py-1.5 text-body-xs font-semibold"
                    >
                      반려
                    </button>
                    <button
                      type="button"
                      onClick={() => decide(id, "approve")}
                      className="rounded-lg bg-brand-primary px-3 py-1.5 text-body-xs font-semibold text-white"
                    >
                      반영
                    </button>
                  </div>
                )}
                {/* 통과한 검사 수치는 숨기고, 떨어진 항목만 이유와 함께 (전체 수치는 GET /documents 기록에 남음) */}
                {d.job.checks
                  .filter((c) => !c.ok)
                  .map((c) => (
                    <p key={c.name} className="text-body-xs text-status-danger">
                      • {c.name}: {c.value} (기준 {c.limit})
                    </p>
                  ))}
              </div>
            )}
          </article>
        ))}
      </section>
    </main>
  );
}
