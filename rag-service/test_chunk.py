import json
import re
from statistics import median

from chunk import EXCLUDE_PAGES, EXCLUDE_TITLES, MAX_CHARS, make_chunks, merge_short, split_long

NOISE_REPORT = "noise_report.json"    # 잡음 의심 청크 id 목록: 사람이 이 id만 열어 확인
NOISE_MAX = 0.02    # 잡음 의심 청크가 전체의 2%를 넘으면 실패
REF = re.compile(r"et al|\b(?:19|20)\d{2}\s*[;:]|doi|https?://", re.I)


# ── 단위 검사: 문서 없이 가짜 데이터로 로직만 본다 ──

def test_split_long():
  text = "\n\n".join(["가" * 300] * 10 + ["나" * 2500])
  parts = split_long(text)
  assert all(len(p) <= MAX_CHARS for p in parts), "MAX_CHARS 넘는 조각"
  assert sum(p.count("가") for p in parts) == 3000 and sum(p.count("나") for p in parts) == 2500, "자르다 글자 손실"

  table = "\n".join(f"| 항목{i} | 내용{i} |" for i in range(200))
  parts = split_long(table)
  assert all(l.startswith("|") and l.endswith("|") for p in parts for l in p.split("\n")), "표 행이 중간에서 잘림"


def test_merge_short():
  c = lambda t, path, page: {"id": "", "path": path, "pages": [page], "text": t}
  out = merge_short([c("가" * 500, "1 > 1.1", 1), c("짧음", "1 > 1.2", 2), c("나" * 500, "1 > 1.3", 3)])
  assert len(out) == 2 and "1.2" in out[0]["text"] and out[0]["pages"] == [1, 2], "짧은 청크가 앞에 안 붙음"
  # 1095 + 2 + "2.2\n짧음"(7) > 1100 → 뒤에 붙어야 함
  out = merge_short([c("가" * 1095, "2 > 2.1", 1), c("짧음", "2 > 2.2", 2), c("나" * 500, "2 > 2.3", 3)])
  assert len(out) == 2 and out[1]["text"].startswith("2.2") and out[1]["pages"] == [2, 3], "앞이 꽉 찼을 때 뒤에 안 붙음"


def test_make_chunks_scope():
  pages = [
    {"page": 1, "text": "# 1 장\n" + "일장본문" * 50 + "\n# 1.1 일부 환자는 수술 전후 연고 도포를 고려할 수 있다 (IB)\n" + "권고본문" * 50},
    {"page": 2, "text": "## 참고문헌\n" + "문헌목록" * 50},
    {"page": 3, "text": "# 2 장\n" + "제외본문" * 50},
    {"page": 4, "text": "# 3 장\n" + "삼장본문" * 50},
  ]
  out = make_chunks(pages, exclude_pages=[(3, 3)])
  text = "".join(c["text"] for c in out)
  assert all("(IB)" not in c["path"] for c in out), "권고 문장이 제목으로 남음"
  assert "권고본문" in text and "(IB)" in text, "제목에서 내린 권고 문장이 본문에서 사라짐"
  assert "문헌목록" not in text, "참고문헌 아래 내용이 남음"
  assert "제외본문" not in text and all(3 not in c["pages"] for c in out), "제외한 쪽이 남음"
  assert "삼장본문" in text and out[-1]["path"] == "3 장", "제외 범위 다음 장이 사라지거나 경로가 꼬임"


# ── 문서 검사: 실제 청크의 숫자만 본다 ──

def test_stats(chunks, pages):
  lens = [len(c["text"]) for c in chunks]
  covered = {p for c in chunks for p in c["pages"]}
  hard_cut = sum(l == MAX_CHARS for l in lens)    # 정확히 MAX = 글자 수로 강제 절단
  print(f"\n청크 {len(chunks)}개 · 길이 최소 {min(lens)} / 중앙 {median(lens):.0f} / 최대 {max(lens)}")
  print(f"100자 미만 {sum(l < 100 for l in lens)}개 · 경로 없음 {sum(not c['path'] for c in chunks)}개 · 강제 절단 {hard_cut}개")
  print(f"포함된 쪽 {len(covered)} / 전체 {len(pages)} (제외 범위 {EXCLUDE_PAGES})")
  assert max(lens) <= MAX_CHARS + 100, "MAX_CHARS+100 넘는 청크"
  assert all(c["pages"] for c in chunks), "쪽 번호 없는 청크 → 출처 표시 불가"
  assert len({c["id"] for c in chunks}) == len(chunks), "청크 ID 중복"


def test_scope(chunks):
  # 답변 근거 범위 밖 내용이 남았는지
  bad_title = sum(any(EXCLUDE_TITLES.search(t) for t in c["path"].split(" > ")) for c in chunks)
  bad_page = sum(any(a <= p <= b for p in c["pages"] for a, b in EXCLUDE_PAGES) for c in chunks)
  print(f"\n제외 제목 남음 {bad_title}개 · 제외 쪽 남음 {bad_page}개")
  assert bad_title == 0 and bad_page == 0, "제외한 범위가 청크에 남음"


def noise_signals(c):
  t = c["text"]
  latin, hangul = len(re.findall(r"[A-Za-z]", t)), len(re.findall(r"[가-힣]", t))
  signals = []
  if len(REF.findall(t)) >= 3:
    signals.append("인용 목록")
  if latin > hangul:
    signals.append("영문 위주")
  if t.count("<br>") >= 20:
    signals.append("표 조각")
  if c["pages"][-1] - c["pages"][0] >= 4:
    signals.append("5쪽 이상")    # 제목 인식 실패로 여러 쪽이 한 절로 뭉친 것
  return signals


def test_noise(chunks):
  # 범위 설정으로 못 거른 잡음: 개수만 출력, 의심 id는 파일로 → 사람이 몇 개만 열어 확인
  report = [{"id": c["id"], "signals": s} for c in chunks if (s := noise_signals(c))]
  json.dump(report, open(NOISE_REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
  counts = {}
  for r in report:
    for s in r["signals"]:
      counts[s] = counts.get(s, 0) + 1
  print(f"\n잡음 의심 {len(report)}/{len(chunks)}개 {counts} → {NOISE_REPORT}")
  # 영문·표·여러 쪽은 격리 기간 표·약어표 같은 진짜 내용도 걸려서 참고용. 실패 조건은 정확한 신호(인용 목록)만
  refs = counts.get("인용 목록", 0)
  assert refs <= len(chunks) * NOISE_MAX, "문헌 목록 청크가 많음 → noise_report.json 제목 보고 EXCLUDE_TITLES 추가"


def test_chunks_json_fresh(chunks, saved_chunks):
  # 인덱스에 들어간 chunks.json이 지금 코드 결과와 같은지
  assert chunks == saved_chunks, "chunks.json이 현재 청킹 결과와 다름 → python chunk.py, python index.py 다시 실행"
