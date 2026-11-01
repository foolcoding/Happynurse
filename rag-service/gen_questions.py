import json
import random
import re
import sys

from ask import chat

# 로컬 LLM(gemma3)으로 평가 질문 초안을 만든다. 문서가 밖으로 나가지 않음
# 결과는 초안일 뿐: 사람이 eval_draft.json을 열어 보고 쓸 것만 eval_set.json으로 옮긴다
# 회사 방식: 화면에는 개수만 찍고 내용은 출력하지 않는다

OUT = "eval_draft.json"
MIN_CHARS = 300    # 너무 짧은 청크는 질문거리가 부족함

SYSTEM = """너는 병동 간호사다. 아래 [지침] 내용을 보고, 근무 중에 동료에게 물어볼 법한 질문 하나와 그 답을 만든다.
- 질문은 지침 문장을 그대로 베끼지 말고, 현장에서 쓰는 짧은 말투로 바꾼다.
- 답은 [지침]에 있는 내용으로만 한두 문장으로 쓴다.
- 반드시 JSON 하나만 출력한다: {"q": "질문", "answer": "답"}"""


def overlap(q, text):
  # 질문 단어 중 청크에 그대로 나오는 비율. 높으면 문서 베끼기 질문이라 점수가 부풀려짐
  words = re.findall(r"[가-힣A-Za-z0-9]{2,}", q)
  return sum(w in text for w in words) / len(words) if words else 1.0


def parse(raw):
  m = re.search(r"\{.*\}", raw, re.S)    # 앞뒤에 설명이 붙어 나와도 JSON 부분만
  try:
    d = json.loads(m.group()) if m else None
  except json.JSONDecodeError:
    return None
  return d if d and d.get("q") and d.get("answer") else None


def generate(chunks, n):
  random.seed(2)
  picks = random.sample([c for c in chunks if len(c["text"]) >= MIN_CHARS], n)
  drafts, failed = [], 0
  for i, c in enumerate(picks, 1):
    d = parse(chat(SYSTEM, f"[지침]\n{c['path']}\n{c['text']}"))
    if not d:
      failed += 1
    else:
      drafts.append({
        "id": f"d{len(drafts) + 1:02d}",
        "q": d["q"],
        "type": "",    # 사람이 고르면서 채움
        "pages": c["pages"],
        "answer": d["answer"],
        "note": f"초안 · 청크 {c['id']} · 겹침 {overlap(d['q'], c['text']):.2f}",
      })
    print(f"{i}/{n} · 실패 {failed}", end="\r")
  print()
  return drafts


if __name__ == "__main__":
  n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
  chunks = json.load(open("chunks.json", encoding="utf-8"))
  drafts = generate(chunks, n)
  json.dump(drafts, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
  high = sum(float(d["note"].rsplit(" ", 1)[-1]) >= 0.7 for d in drafts)
  print(f"초안 {len(drafts)}/{n}개 → {OUT} · 겹침 0.7 이상 {high}개")
