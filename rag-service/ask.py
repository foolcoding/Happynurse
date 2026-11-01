import json
import math
import os
import re
import sys
import urllib.request
from collections import Counter
from functools import cache

os.environ.setdefault("USE_TF", "0")    # transformers가 사용자 폴더의 tensorflow까지 불러오지 않게 (느리고 로그가 지저분함)

from index import OLLAMA, embed, get_collection

CHAT_MODEL = "gemma3:4b"
TOP_K = 3    # LLM에 넘길 청크 수. 질문 세트로 3 vs 5 비교해서 조정
CANDIDATES = 20    # 임베딩 검색으로 추린 뒤 리랭커가 다시 채점할 후보 수
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
HF_CACHE = r"F:\hf-cache"    # 모델 파일 위치 (C: 공간 부족으로 F:에 둠)
MIN_SCORE = 0.2    # 리랭커 1등 점수(0~1)가 이보다 낮으면 근거 없음으로 보고 LLM을 부르지 않음 (질문 세트로 조정)
NOT_FOUND = "관련 지침을 찾지 못했습니다."

# 예시는 평가 세트(eval_set.json)와 겹치지 않는 주제로: 겹치면 점수가 부풀려짐
SYSTEM = """너는 병동 간호사를 돕는 감염관리 지침 도우미다. 업무 메모처럼 개조식으로 짧게 답한다.

[답하는 법]
1. 첫 문장에서 질문에 바로 결론을 말한다.
   - "~해야 돼?", "~맞아?", "~면 돼?"처럼 예·아니요로 묻는 질문만 "네" 또는 "아니요"로 시작한다. 질문이 틀린 생각이면 "아니요"다. "~만 하면 돼?"에 근거가 더 할 일을 말하면 "아니요"다.
   - "언제", "어떻게", "무엇"을 묻는 질문은 "네/아니요" 없이 결론 문장으로 시작한다.
2. 이어서 해야 할 일을 근거에서 골라 짧게 정리한다. 순서가 있으면 순서대로 쓴다.
3. 문서 문장을 그대로 베끼지 말고 쉬운 말로 바꿔 쓴다. 단, 뜻이 바뀌게 줄이지 않는다. 숫자·농도·시간·물품 이름·대상(누구, 어느 부위)은 근거에 적힌 그대로 쓴다.
4. 조항 번호(예: 6.2.2.3), 권고등급(예: (IB)), 참고문헌 번호(예: [38, 58])는 쓰지 않는다.
5. 근거 번호는 문장 중간에 넣지 않는다. 문장을 마침표로 끝낸 뒤 그 뒤에 실제로 쓴 번호만 [1]처럼 붙인다.
6. 모든 문장을 "~함", "~해야 함", "~하지 않음"처럼 명사형으로 끝낸다. "~요", 반말, "음", 느낌표는 쓰지 않는다.

[지켜야 할 것]
- [근거]에 있는 내용으로만 답한다. 근거에 없는 내용은 지어내지 않는다.
- 질문과 근거의 표현이 달라도 같은 내용이면 답한다.
- 근거 어디에도 질문과 관련된 내용이 없을 때만 정확히 "관련 지침을 찾지 못했습니다."라고만 답한다.
- 근거에 없는 약 용량·처치 여부 같은 의학적 판단은 하지 않는다.

[예시]
근거: [1] 4.2.1 주사 준비 - 4.2.1.3 주사 준비 전 손위생을 하고, 주사 준비 구역은 매일 70% 알코올로 닦는다. (IB)
질문: 주사 준비대 매일 닦아야 돼?
답: 네, 매일 닦아야 함. [1]
• 주사 준비 구역은 매일 70% 알코올로 닦음. [1]
• 주사 준비 전에는 손위생부터 해야 함. [1]

근거: [1] 4.3 다회용 바이알 - 다회용 바이알은 개봉 후 날짜를 적고, 개봉 후 28일이 지나면 폐기한다. 오염이 의심되면 즉시 폐기한다.
질문: 다회용 바이알 언제 버려?
답: 개봉하고 28일이 지나면 폐기함. [1]
• 개봉할 때 날짜를 적어 둠. [1]
• 오염이 의심되면 28일 전이라도 바로 폐기함. [1]

근거: [1] 5.1 소변 배양 검체 - 검체는 배액 주머니에서 받지 않는다. 채취 포트를 소독한 뒤 멸균 주사기로 뽑는다.
질문: 소변 검체 주머니에서 받으면 돼?
답: 아니요, 주머니에서 받으면 안 됨. [1]
• 채취 포트를 소독함. [1]
• 멸균 주사기로 뽑음. [1]"""


@cache
def reranker():
  # 프로세스당 한 번 GPU에 올림. 질문과 청크를 한 쌍씩 같이 읽고 관련도를 채점하는 모델(cross-encoder)
  import torch
  from sentence_transformers import CrossEncoder
  return CrossEncoder(RERANK_MODEL, cache_folder=HF_CACHE, model_kwargs={"torch_dtype": torch.float16})


def bigrams(text):
  # 형태소 분석기 없이 쓰는 키워드 단위: 두 글자씩 (세탁물 → 세탁, 탁물)
  return [w[i:i + 2] for w in re.findall(r"[가-힣a-z0-9]+", text.lower()) for i in range(max(1, len(w) - 1))]


@cache
def keyword_index():
  # 프로세스당 한 번 DB에서 읽어 BM25 통계를 만든다
  res = get_collection().get(include=["documents", "metadatas"])
  docs = [Counter(bigrams(f"{m['path']} {d}")) for d, m in zip(res["documents"], res["metadatas"])]
  df = Counter(t for d in docs for t in d)
  avg_len = sum(sum(d.values()) for d in docs) / len(docs)
  return res, docs, df, avg_len


def keyword_search(question, n, k1=1.5, b=0.75):
  # BM25: 드문 단어(세탁물)가 겹치면 점수가 크고, 흔한 단어(보호구)는 작다
  res, docs, df, avg_len = keyword_index()
  terms, total = set(bigrams(question)), len(docs)
  scored = []
  for i, d in enumerate(docs):
    length = sum(d.values())
    s = sum(math.log(1 + (total - df[t] + 0.5) / (df[t] + 0.5)) * d[t] * (k1 + 1) / (d[t] + k1 * (1 - b + b * length / avg_len))
            for t in terms if t in d)
    if s > 0:
      scored.append((s, i))
  return [(res["ids"][i], res["documents"][i], res["metadatas"][i]) for _, i in sorted(scored, reverse=True)[:n]]


def retrieve(question, k=TOP_K):
  # 1단계 후보: 임베딩 검색 20개(뜻이 비슷한 것) + 키워드 검색 20개(드문 단어가 겹치는 것)
  # 2단계: 리랭커가 질문과 후보를 한 쌍씩 같이 읽고 다시 순위 → 상위 k개
  col = get_collection()
  res = col.query(query_embeddings=embed([question]), n_results=CANDIDATES)
  pool = {
    i: {"text": doc, "distance": dist, **meta}
    for i, doc, dist, meta in zip(res["ids"][0], res["documents"][0], res["distances"][0], res["metadatas"][0])
  }
  for i, doc, meta in keyword_search(question, CANDIDATES):
    pool.setdefault(i, {"text": doc, "distance": None, **meta})    # 키워드로만 들어온 후보는 임베딩 거리 없음
  hits = list(pool.values())
  scores = reranker().predict([(question, f"{h['path']}\n{h['text']}") for h in hits])
  for h, s in zip(hits, scores):
    h["score"] = float(s)
  return sorted(hits, key=lambda h: h["score"], reverse=True)[:k]


def chat_body(system, user, model, stream, as_json=False):
  return json.dumps({
    "model": model,
    **({"format": "json"} if as_json else {}),    # JSON만 출력하도록 강제 (채점기용)
    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    "stream": stream,
    "options": {"temperature": 0, "num_predict": 800},    # 같은 질문엔 같은 답 · 목록을 끝없이 늘어놓는 경우를 대비해 길이 상한
    **({"think": False} if model.startswith("qwen3") else {}),    # qwen3는 추론 모드를 꺼야 빠름 (gemma는 이 옵션 없음)
  }).encode()


def chat(system, user, model=None, as_json=False):
  body = chat_body(system, user, model or CHAT_MODEL, False, as_json)
  req = urllib.request.Request(f"{OLLAMA}/api/chat", body, {"Content-Type": "application/json"})
  content = json.load(urllib.request.urlopen(req))["message"]["content"]
  return content.split("</think>")[-1].strip()    # 추론 과정이 섞여 나오는 모델 대비


def chat_stream(system, user):
  # Ollama 스트리밍: 한 줄에 JSON 하나씩, 토큰 조각이 도착하는 대로 내보냄
  body = chat_body(system, user, CHAT_MODEL, True)
  req = urllib.request.Request(f"{OLLAMA}/api/chat", body, {"Content-Type": "application/json"})
  with urllib.request.urlopen(req) as resp:
    for line in resp:
      d = json.loads(line)
      if d["message"]["content"]:
        yield d["message"]["content"]
      if d.get("done"):
        break


WH = re.compile(r"언제|어떻게|어떡|어떤|무엇|뭐|뭘|무슨|어디|왜|얼마|몇|누가|누구")    # 예·아니요가 아닌 질문


LEAD = re.compile(r"^\s*(네|아니요|아뇨|음|흠)(?:\s*[,.!]\s*|\s+|$)")    # 뒤에 문장부호·공백이 와야 지움 ('네트워크'는 그대로)
FILLER = re.compile(r"^\s*(음|흠)(?:\s*[,.!]\s*|\s+|$)")    # 어떤 질문이든 지우는 군말


def strip_lead(pieces, question):
  # 프롬프트로 시켜도 4B 모델이 '언제' 질문에 "네,"를 붙임 → 모델에 맡기지 않고 코드로 지움
  # 스트리밍 조각을 앞부분 몇 글자만 모았다가 정리하고, 그 뒤로는 그대로 흘려보냄
  lead = LEAD if WH.search(question) else FILLER
  head = ""
  for piece in pieces:
    if head is None:
      yield piece
      continue
    head += piece
    if len(head) >= 6:
      yield lead.sub("", head)
      head = None
  if head:
    yield lead.sub("", head)


def prepare(question):
  # 검색 + 거절 판단 + LLM 입력 만들기. ask()와 스트리밍 API가 같이 씀
  hits = retrieve(question)
  sources = [{"n": i, "path": h["path"], "pages": h["pages"], "version": h["version"]} for i, h in enumerate(hits, 1)]
  scores = [h["score"] for h in hits]
  if not hits or hits[0]["score"] < MIN_SCORE:    # 리랭커가 보기에 답이 될 청크가 없으면 LLM을 부르지 않음 (지어내기 방지)
    return None, [], scores
  context = "\n\n".join(f"[{i}] {h['path']} (p.{h['pages']})\n{h['text']}" for i, h in enumerate(hits, 1))
  return f"[근거]\n{context}\n\n[질문]\n{question}", sources, scores


def ask(question):
  prompt, sources, scores = prepare(question)
  if prompt is None:
    return {"answer": NOT_FOUND, "sources": [], "scores": scores}
  answer = "".join(strip_lead([chat(SYSTEM, prompt)], question))
  return {"answer": answer, "sources": sources, "scores": scores}


if __name__ == "__main__":
  r = ask(" ".join(sys.argv[1:]))
  print(r["answer"], "\n")
  for s in r["sources"]:
    print(f"[{s['n']}] {s['path']} · p.{s['pages']} · {s['version']}")
  print("리랭커 점수:", [round(d, 3) for d in r["scores"]])
