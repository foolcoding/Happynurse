from eval import grade

# 채점기 검증: 채점기가 틀리면 '답 정확' 숫자도 믿을 수 없다
# 문서와 무관한 일반 상식 문제로 정답·부분·오답·깨짐을 제대로 가르는지만 본다 (Ollama qwen3:4b 필요)

ITEM = {"q": "손 소독제로 손위생할 때 얼마나 문질러야 해?", "answer": "손 소독제를 손 전체에 바르고 마를 때까지 20~30초 문지른다."}
CASES = [
  ("손 소독제를 손 전체에 골고루 바른 뒤 완전히 마를 때까지 20~30초간 문지르면 됩니다.", {"정확"}),
  ("손 소독제를 손에 바르고 문지르면 됩니다.", {"부분"}),
  ("손 소독제는 3초만 문지르고 바로 물로 헹궈야 합니다.", {"틀림"}),
  ("[1, 2, 5~7]", {"깨짐"}),
]


def test_grade():
  got = [grade(ITEM, a)[0] for a, _ in CASES]
  ok = sum(g in want for g, (_, want) in zip(got, CASES))
  print(f"\n채점기 판정 {ok}/{len(CASES)} 일치 {got}")
  assert ok == len(CASES), "채점기가 정답·부분·오답을 못 가름 → JUDGE 프롬프트나 모델 확인"
