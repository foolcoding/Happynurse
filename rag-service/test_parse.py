from collections import Counter

import pymupdf
import pymupdf4llm
import pytest

from parse import OPTS, PDF, parse_pages

TABLE_PAGE = 15    # 표가 있는 쪽 (PDF 기준, 1부터)
ALLOWED = {"부록 1"}    # 옆 탭이면서 진짜 제목·본문에도 쓰임 → 확인 후 허용


@pytest.fixture(scope="module")
def parsed():
  return parse_pages(PDF)    # 느림: 이 파일에서 한 번만 파싱


def table_rows(md):
  return [l.strip() for l in md.splitlines() if l.strip().startswith("|")]


def test_table():
  md = pymupdf4llm.to_markdown(PDF, pages=[TABLE_PAGE - 1], **OPTS)
  with open(f"page{TABLE_PAGE}.md", "w", encoding="utf-8") as f:    # 원문과 눈으로 비교할 파일
    f.write(md)
  rows = table_rows(md)
  assert rows, "표가 마크다운으로 안 나옴"
  seps = [r for r in rows if set(r) <= set("|-: ")]
  assert seps, "표 구분선(|---|)이 없음"
  cols = [r.count("|") - 1 for r in rows]
  assert len(set(cols)) == 1, f"줄마다 칸 수가 다름 → 셀이 밀림: {sorted(set(cols))}"
  cells = [c.strip() for r in rows if r not in seps for c in r.strip("|").split("|")]
  empty = sum(not c for c in cells)
  print(f"\n표 줄 {len(rows)} · 칸 {cols[0]} · 빈 셀 {empty}/{len(cells)} (page{TABLE_PAGE}.md 저장)")
  assert empty / len(cells) < 0.5, "빈 셀이 절반 이상 → 병합 셀이 깨졌을 가능성"


def test_page_count(parsed):
  assert len(parsed) == pymupdf.open(PDF).page_count, "쪽 수가 PDF와 다름"


def test_headings(parsed):
  heads = [l for p in parsed for l in p["text"].splitlines() if l.startswith("#")]
  print(f"\n제목(#) {len(heads)}개")
  assert heads, "제목이 하나도 없음 → 구조가 안 잡힘"


def test_page_noise(parsed):
  # 쪽 번호·머리말·옆 탭이 본문에 남았는지: 개수만 본다
  digit_only, seen = 0, Counter()
  for p in parsed:
    lines = {l.strip().strip("*#_ ") for l in p["text"].splitlines()}
    lines = {l for l in lines if l and not set(l) <= set("|-: ")}
    digit_only += sum(l.isdigit() for l in lines)
    seen.update(lines)    # 쪽마다 한 번씩만 셈
  repeated = [l for l, n in seen.items() if n >= len(parsed) * 0.1 and l not in ALLOWED]
  print(f"\n숫자만 있는 줄 {digit_only}개 · 10% 넘는 쪽에서 반복되는 줄 {len(repeated)}종")
  assert digit_only < len(parsed) * 0.2, "숫자만 있는 줄이 많음 → 쪽 번호가 본문에 섞임"
  assert not repeated, "여러 쪽에서 반복되는 줄 있음 → 머리말·옆 탭이 섞였을 가능성"


def test_pages_json_fresh(parsed, pages):
  # 저장된 pages.json이 지금 파서 결과와 같은지 (옛 결과로 청킹하는 실수 방지)
  assert parsed == pages, "pages.json이 현재 파서 결과와 다름 → python parse.py 다시 실행"
