import random

from ask import ask, retrieve

# Ollama(bge-m3, gemma3:4b)가 켜져 있어야 함
# 배선 검사만 한다. 품질은 eval.py + eval_set.json으로 따로 잰다


def test_off_topic():
  # 무관한 질문은 리랭커 점수 기준(1차) 또는 LLM(2차)에서 거절돼야 함
  qs = ["오늘 서울 날씨 어때?", "비트코인 시세 알려줘", "파스타 맛있게 만드는 법"]
  refused = 0
  print()
  for q in qs:
    r = ask(q)
    by_distance = not r["sources"]
    by_llm = not by_distance and "찾지 못했습니다" in r["answer"]
    refused += by_distance or by_llm
    print(f"리랭커 1등 {r['scores'][0]:.3f} · 점수로 거절 {by_distance} · LLM이 거절 {by_llm}")
  assert refused == len(qs), f"무관한 질문 {len(qs) - refused}개에 답을 지어냄"


def test_strip_lead():
  # 문서·모델 없이: '언제' 질문은 앞의 "네,"를 지우고, 예·아니요 질문은 그대로. 조각으로 나뉘어 와도 동작
  from ask import strip_lead
  join = lambda pieces, q: "".join(strip_lead(pieces, q))
  assert join(["네", ", 손", "위생은 환자 접촉 전후에 해요"], "손 소독은 언제 해?") == "손위생은 환자 접촉 전후에 해요"
  assert join(["아니요. 이렇게 해요"], "어떻게 닦아?") == "이렇게 해요"
  assert join(["네, 해야 해요"], "장갑 꼭 해야 돼?") == "네, 해야 해요"
  assert join(["네"], "언제 해?") == ""
  assert join(["음, 해", "야 해요"], "장갑 꼭 해야 돼?") == "해야 해요"
  assert join(["네트워크 장비는 매일 닦아요"], "언제 닦아?") == "네트워크 장비는 매일 닦아요", "'네'로 시작하는 단어까지 지움"


def test_reranker():
  # 문서 없이 리랭커만: 관련 문장이 무관한 문장보다 점수가 높아야 함
  from ask import reranker
  s = reranker().predict([("손은 얼마나 씻어야 해?", "손위생은 물과 비누로 40~60초 동안 시행한다."),
                          ("손은 얼마나 씻어야 해?", "주차장은 지하 2층부터 이용할 수 있다.")])
  print(f"\n리랭커 점수 관련 {s[0]:.3f} · 무관 {s[1]:.3f}")
  assert s[0] > s[1], "리랭커가 관련 문장을 더 낮게 채점함"


def test_title_retrieval(saved_chunks, n=30):
  # 절 제목만으로 검색해도 그 절의 쪽이 top-3에 나오는지
  random.seed(1)
  picks = random.sample([c for c in saved_chunks if " > " in c["path"]], n)
  hit, scores = 0, []
  for c in picks:
    hits = retrieve(c["path"].split(" > ")[-1])
    scores.append(hits[0]["score"])
    found = {p for h in hits for p in h["pages"].split(",")}
    hit += any(str(p) in found for p in c["pages"])
  print(f"\n제목 검색 top-3 적중 {hit}/{n} · 리랭커 1등 점수 평균 {sum(scores) / n:.3f} · 최저 {min(scores):.3f}")
  assert hit >= n * 0.6, "제목으로도 해당 절을 못 찾음"
