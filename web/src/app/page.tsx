"use client";

import { useEffect, useRef, useState } from "react";

import { moveCites } from "@/lib/cite";
import { askStream, type Source } from "@/lib/sse";

type Status =
  | "searching"
  | "streaming"
  | "done"
  | "refused"
  | "error"
  | "stopped"
  | "cut";

type Turn = {
  id: number;
  question: string;
  sources: Source[];
  answer: string;
  status: Status;
};

const EXAMPLES = [
  "손 소독제로 손위생할 때 얼마나 문질러야 해?",
  "혈액이 바닥에 쏟아졌는데 어떻게 닦아?",
  "중심정맥관 삽입할 때 장갑만 끼면 돼?",
];

export default function Page() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const inflight = useRef(false); // 상태 반영 전 Enter 연타로 같은 질문이 두 번 가는 것 방지
  const endRef = useRef<HTMLDivElement>(null);
  const busy =
    turns.at(-1)?.status === "searching" ||
    turns.at(-1)?.status === "streaming";

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  const update = (id: number, patch: (t: Turn) => Partial<Turn>) =>
    setTurns((prev) =>
      prev.map((t) => (t.id === id ? { ...t, ...patch(t) } : t)),
    );

  async function send(question: string) {
    const q = question.trim();
    if (!q || inflight.current) return;
    inflight.current = true;
    const id = Date.now();
    setTurns((prev) => [
      ...prev,
      { id, question: q, sources: [], answer: "", status: "searching" },
    ]);
    setInput("");
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const finished = await askStream(
        q,
        {
          onSources: (sources) =>
            update(id, () => ({ sources, status: "streaming" })),
          onToken: (text) => update(id, (t) => ({ answer: t.answer + text })),
          onRefused: (answer) =>
            update(id, () => ({ answer, status: "refused" })),
          onError: (message) =>
            update(id, () => ({ answer: message, status: "error" })),
        },
        ctrl.signal,
      );
      // done 없이 끝났으면 서버가 중간에 끊긴 것 → 완료로 보이지 않게
      update(id, (t) =>
        t.status === "streaming" ? { status: finished ? "done" : "cut" } : {},
      );
    } catch {
      update(id, (t) =>
        ctrl.signal.aborted
          ? { status: "stopped" }
          : {
              answer: "서버에 연결하지 못했습니다.",
              status: "error",
            },
      );
    } finally {
      inflight.current = false;
    }
  }

  return (
    <main className="mx-auto flex h-dvh max-w-[430px] flex-col bg-surface-base shadow-xl">
      <header className="bg-brand-primary px-5 pt-5 pb-4 text-brand-text">
        <div className="flex justify-between text-body-micro opacity-80">
          <p>HappyNurse</p>
          <a href="/admin">문서 관리</a>
        </div>
        <h1 className="text-title-md font-bold">감염관리 지침 도우미</h1>
        <p className="mt-1 text-body-micro opacity-80">
          질병관리청 의료관련감염 표준예방지침 · 2017 (2019 웹 수정판)
        </p>
      </header>

      <section
        className="flex-1 space-y-5 overflow-y-auto px-4 py-5"
        aria-live="polite"
      >
        {turns.length === 0 && <Empty onPick={send} />}
        {turns.map((t) => (
          <div key={t.id} className="space-y-2">
            <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-action-blue px-4 py-2.5 text-body-sm text-white">
              {t.question}
            </p>
            <Answer turn={t} onRetry={() => send(t.question)} />
          </div>
        ))}
        <div ref={endRef} />
      </section>

      <form
        className="border-t border-border-subtle bg-surface-card px-4 pt-3 pb-4"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <div className="flex gap-2">
          <label htmlFor="q" className="sr-only">
            질문
          </label>
          <input
            id="q"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            maxLength={500}
            placeholder="궁금한 점에 대해 물어보세요"
            className="min-w-0 flex-1 rounded-lg border border-border-base bg-surface-base px-3 py-2.5 text-body-base outline-none focus:border-brand-primary"
          />
          {busy ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="rounded-lg bg-sub-primary px-4 text-body-sm font-semibold text-white"
            >
              중지
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="rounded-lg bg-brand-primary px-4 text-body-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-40"
            >
              질문
            </button>
          )}
        </div>
        <p className="mt-2 text-body-micro text-content-muted">
          지침에 없는 의학적 판단은 의료진과 확인하세요.
        </p>
      </form>
    </main>
  );
}

function Empty({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="pt-6 text-center">
      <p className="text-body-sm text-content-tertiary">
        손위생, 격리, 소독, 삽입기구 관리 등<br />
        표준예방지침 내용을 근거와 함께 알려드려요.
      </p>
      <div className="mt-5 space-y-2">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="block w-full rounded-lg border border-border-subtle bg-surface-card px-4 py-3 text-left text-body-sm text-content-secondary hover:bg-surface-hover"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function Answer({ turn, onRetry }: { turn: Turn; onRetry: () => void }) {
  const { status, sources, answer } = turn;
  if (status === "searching") {
    return (
      <Bubble>
        <span className="text-content-muted">지침에서 찾는 중…</span>
      </Bubble>
    );
  }
  if (status === "refused") {
    return (
      <Bubble tone="warning">
        {answer}
        <p className="mt-1 text-body-micro text-content-quaternary">
          이 지침서에 관련 내용이 없거나, 질문을 더 구체적으로 써 주세요.
        </p>
      </Bubble>
    );
  }
  if (status === "error") {
    return (
      <Bubble tone="danger">
        {answer}
        <button
          onClick={onRetry}
          className="mt-2 block text-body-xs font-semibold text-status-danger underline"
        >
          다시 시도
        </button>
      </Bubble>
    );
  }
  return (
    <div className="space-y-2">
      {sources.length > 0 && (
        <ul className="space-y-1">
          {sources.map((s) => (
            <li
              key={s.n}
              className="flex items-baseline gap-2 rounded-md bg-brand-surface px-3 py-1.5 text-body-xs text-sub-primary"
            >
              <span className="font-bold text-brand-primary">[{s.n}]</span>
              <span className="min-w-0 flex-1 truncate">{title(s.path)}</span>
              <span className="shrink-0 text-content-quaternary">
                {pages(s.pages)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Bubble>
        <Cited text={answer} count={sources.length} />
        {status === "streaming" && (
          <span className="ml-0.5 animate-[blink_1s_step-end_infinite]">▍</span>
        )}
        {status === "stopped" && (
          <span className="ml-1 text-body-micro text-content-muted">
            (중지됨)
          </span>
        )}
        {status === "cut" && (
          <span className="ml-1 text-body-micro text-status-danger">
            (답변이 중간에 끊겼습니다)
          </span>
        )}
      </Bubble>
    </div>
  );
}

function Bubble({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: "warning" | "danger";
}) {
  const color =
    tone === "warning"
      ? "bg-status-warning-surface border-status-warning/30"
      : tone === "danger"
        ? "bg-status-danger-surface border-status-danger/30"
        : "bg-surface-card border-border-subtle";
  return (
    <div
      className={`w-fit max-w-[92%] whitespace-pre-wrap break-words rounded-2xl rounded-bl-sm border px-4 py-3 text-body-sm leading-relaxed text-content-primary ${color}`}
    >
      {children}
    </div>
  );
}

// 답 속 [1], [1, 3] 을 출처 번호 뱃지로
// 지침서 본문의 참고문헌 번호([38, 58, 59])를 LLM이 그대로 옮겨 쓰는 경우가 있어, 출처 범위 밖 번호는 지운다
function Cited({ text, count }: { text: string; count: number }) {
  // LLM이 쓰는 마크다운 목록(*, -)은 글머리표로, 굵게(**)는 기호만 제거
  const plain = text.replace(/^(\s*)[*-]\s+/gm, "$1• ").replace(/\*\*/g, "");
  const parts = moveCites(plain, count).split(/(\[\d+(?:\s*,\s*\d+)*\])/g);
  return (
    <>
      {parts.map((p, i) => {
        if (!/^\[\d/.test(p)) return p;
        const ns = p.slice(1, -1).split(/\s*,\s*/);
        if (!ns.every((n) => /^\d+$/.test(n) && +n >= 1 && +n <= count))
          return null;
        return (
          <sup
            key={i}
            className="mx-0.5 rounded bg-brand-surface px-1 text-body-micro font-bold text-brand-primary"
          >
            {ns.join(", ")}
          </sup>
        );
      })}
    </>
  );
}

// '의료관련감염 표준예방지침 > 무균술 > 2.2.3 무균술 수행 시 장갑 착용' → 마지막 제목만, 태그 제거
function title(path: string) {
  return (
    path
      .split(" > ")
      .at(-1)
      ?.replace(/<[^>]+>/g, "")
      .replace(/^\|\s*/, "") || "본문"
  );
}

// '261,262,263,264' → 'p.261–264'
function pages(p: string) {
  const ps = p.split(",");
  return ps.length > 1 ? `p.${ps[0]}–${ps.at(-1)}` : `p.${ps[0]}`;
}
