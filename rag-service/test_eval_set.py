import json

import pytest

# 질문 세트 자체가 맞는지 검사: 세트가 틀리면 eval.py 점수도 틀린다
# 질문·답 내용은 출력하지 않고 id와 개수만 본다

TYPES = {"", "사실", "표·숫자", "현장 말투", "여러 절", "문서에 없음", "모호"}


@pytest.fixture(scope="module")
def items():
  return json.load(open("eval_set.json", encoding="utf-8"))


def test_format(items):
  ids = [it["id"] for it in items]
  assert len(set(ids)) == len(ids), "id 중복"
  assert all(it["q"].strip() for it in items), "빈 질문"
  bad = [it["id"] for it in items if it["type"] not in TYPES]
  assert not bad, f"정해진 유형이 아님: {bad}"


def test_balance(items):
  neg = [it for it in items if not it["pages"]]
  untyped = sum(not it["type"] for it in items)
  print(f"\n전체 {len(items)} · 답 있는 질문 {len(items) - len(neg)} · 거절 질문 {len(neg)} · 유형 미기입 {untyped}")
  assert all(it["type"] == "문서에 없음" for it in neg), "pages가 비었는데 유형이 '문서에 없음'이 아님"
  assert len(neg) >= 3, "거절 질문이 3개 미만"
  assert len(items) - len(neg) >= 10, "답 있는 질문이 10개 미만 → 점수가 한두 문제에 크게 흔들림"


def test_gold_reachable(items, saved_chunks):
  # 정답 쪽이 인덱스에 하나도 없으면 맞힐 수 없는 문제 (제외 범위·빈 쪽을 정답으로 적은 것)
  indexed = {p for c in saved_chunks for p in c["pages"]}
  bad = [it["id"] for it in items if it["pages"] and not set(it["pages"]) & indexed]
  print(f"\n정답 쪽이 인덱스에 없는 질문 {len(bad)}개 {bad}")
  assert not bad, "정답 쪽이 인덱스 범위 밖 → 질문을 빼거나 정답 쪽을 고침"
