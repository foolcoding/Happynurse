import json
import re
import time
import urllib.request
from collections import defaultdict

from ask import OLLAMA, ask, chat, retrieve

# 사람이 만든 질문 세트(eval_set.json)로 검색·거절·응답 시간을 잰다
# 회사 방식: 질문·답 내용은 출력하지 않고 id와 숫자만 찍는다
# 결과는 eval_result.json에 저장 → 설정을 바꾼 뒤 다시 돌려서 비교

SRC = "eval_set.json"
OUT = "eval_result.json"
REFUSAL = "찾지 못했습니다"
JUDGE_MODEL = "qwen3:4b"    # 채점은 답변 모델(gemma)과 다른 모델로: 자기 답을 자기가 채점하면 후해짐
VERDICTS = ("정확", "부분", "틀림")

JUDGE = """너는 간호 감염관리 지침 답변을 채점하는 사람이다. [모범답안]을 기준으로 [답변]을 채점한다.
- 정확: 모범답안의 핵심 내용을 빠짐없이 담고, 틀린 내용이 없다. 표현이 달라도 뜻이 같으면 정확이다.
- 부분: 맞는 내용이 있지만 핵심 일부가 빠졌거나 덜 구체적이다.
- 틀림: 핵심이 틀렸거나 반대이거나, 질문과 무관하거나, 모범답안에 없는 위험한 내용을 지어냈다.
반드시 JSON 하나만 출력한다: {"verdict": "정확|부분|틀림", "reason": "한 문장"}"""


def unload(model):
  # 8GB GPU에 답변·채점·임베딩 모델과 리랭커가 다 올라가면 서로 밀어내며 수 분씩 멈춤 → 답변 단계 전에 채점 모델을 내림
  body = json.dumps({"model": model, "keep_alive": 0}).encode()
  urllib.request.urlopen(urllib.request.Request(f"{OLLAMA}/api/generate", body, {"Content-Type": "application/json"})).read()


def grade(item, answer):
  # 답 내용 채점. 한글 문장이 거의 없으면(인용 번호만 뱉는 등) LLM에 묻기 전에 '깨짐'
  if len(re.findall(r"[가-힣]", answer)) < 10:
    return "깨짐", "한글 문장이 거의 없음"
  raw = chat(JUDGE, f"[질문]\n{item['q']}\n\n[모범답안]\n{item['answer']}\n\n[답변]\n{answer}", model=JUDGE_MODEL, as_json=True)
  m = re.search(r"\{.*\}", raw, re.S)
  try:
    d = json.loads(m.group()) if m else {}
  except json.JSONDecodeError:
    d = {}
  verdict = d.get("verdict", "")
  return (verdict, d.get("reason", "")) if verdict in VERDICTS else ("채점실패", raw[:200])


def rank_of(hits, gold):
  # 정답 쪽이 처음 나온 순위 (1부터). top-k 안에 없으면 None
  for i, h in enumerate(hits, 1):
    if any(str(p) in h["pages"].split(",") for p in gold):
      return i
  return None


def run(item):
  t = time.perf_counter()
  r = ask(item["q"])
  sec = time.perf_counter() - t
  refused = not r["sources"] or REFUSAL in r["answer"]
  res = {"id": item["id"], "type": item.get("type") or "미분류", "sec": round(sec, 2), "refused": refused}
  if item["pages"]:
    res["rank"] = rank_of(retrieve(item["q"]), item["pages"])
    res["answer"] = r["answer"]    # 채점은 전부 답한 뒤 따로 (모델을 번갈아 올리면 응답 시간이 오염됨)
  return res


def report(results):
  groups = defaultdict(list)
  for r in results:
    groups[r["type"]].append(r)
  groups["전체"] = results

  print(f"\n{'유형':<8}{'개수':>4}{'hit@3':>8}{'MRR':>7}{'잘못 거절':>8}{'근거없이 답':>9}{'거절 정확':>8}{'평균초':>7}")
  for name, rs in groups.items():
    ans = [r for r in rs if "rank" in r]    # 답이 있어야 하는 질문
    neg = [r for r in rs if "rank" not in r]    # 거절해야 하는 질문
    hit = f"{sum(r['rank'] is not None for r in ans) / len(ans):.2f}" if ans else "-"
    mrr = f"{sum(1 / r['rank'] for r in ans if r['rank']) / len(ans):.2f}" if ans else "-"
    # 잘못 거절: 정답 근거가 top-3에 있는데 거절 (LLM 과잉 거절). 근거가 없어서 거절한 건 검색 문제라 여기서 뺌
    wrong = f"{sum(r['refused'] and r['rank'] is not None for r in ans)}/{len(ans)}" if ans else "-"
    # 근거없이 답: 정답 근거가 top-3에 없는데 답함 (지어냈을 위험, 가장 위험)
    blind = f"{sum(not r['refused'] and r['rank'] is None for r in ans)}/{len(ans)}" if ans else "-"
    neg_ok = f"{sum(r['refused'] for r in neg)}/{len(neg)}" if neg else "-"
    # 답 정확: 답이 있어야 하는 질문 중 모범답안과 맞게 답한 비율 (거절·깨짐·틀림은 실패)
    exact = f"{sum(r['grade'] == '정확' for r in ans)}/{len(ans)}" if ans else "-"
    loose = f"{sum(r['grade'] in ('정확', '부분') for r in ans)}/{len(ans)}" if ans else "-"
    sec = sum(r["sec"] for r in rs) / len(rs)
    print(f"{name:<8}{len(rs):>4}{hit:>8}{mrr:>7}{wrong:>8}{blind:>9}{neg_ok:>8}{exact:>8}{loose:>8}{sec:>7.2f}")


if __name__ == "__main__":
  items = [it for it in json.load(open(SRC, encoding="utf-8")) if it["q"].strip()]    # 빈 칸은 건너뜀
  unload(JUDGE_MODEL)
  results = [run(it) for it in items]    # 1단계: 전부 답하기 (응답 시간은 여기서만 잼)
  for it, r in zip(items, results):
    # 답 품질: 거절했으면 '거절', 답했으면 모범답안 대비 채점. 이유는 파일에만 저장 (화면엔 판정만)
    if "answer" in r:
      r["grade"], r["reason"] = ("거절", "") if r["refused"] else grade(it, r.pop("answer"))
    print(f"{r['id']} · 순위 {r.get('rank', '거절 대상')} · 거절 {r['refused']} · 답 {r.get('grade', '-')} · {r['sec']}초")
  report(results)
  json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
  print(f"\n→ {OUT}")
