import json
import re

SRC = "pages.json"
OUT = "chunks.json"
DOC_ID = "kdca-standard-precautions"    # 문서 ID: 새 판이 들어오면 같은 ID의 옛 청크를 교체
VERSION = "2017 (2019 웹 수정판)"
MAX_CHARS = 1000    # 처음 값. 질문 세트로 비교해서 조정

# 답변 근거 범위: 문서 담당자가 toc.py 출력(장 목록)을 보고 정한다
EXCLUDE_PAGES = [(151, 160), (271, 323)]    # 뺄 장의 쪽 범위: Ch11 참고문헌, Ch13 지침 개발 과정·문헌 검토
# 이 제목 아래 내용은 버림: 장 안에 섞인 문헌 목록, 지침 개발 과정 (test_noise의 noise_report.json 제목으로 확인)
EXCLUDE_TITLES = re.compile(
  r"참고\s?문헌|참고지침서|개발위원회|개발팀|AGREE|가이드라인 (검색|선별)|개발 방법의 결정|^(\d\.\s*)?국[내외]$"
)

# PDF 파서가 권고 문장을 제목(#)으로 잘못 잡는 경우 → 본문으로 되돌림
MAX_TITLE = 60
GRADE = re.compile(r"\((I[ABC]?|II|III)\)\.?\s*$")    # 권고 등급 (IB) 등으로 끝나면 제목이 아니라 권고 문장


def heading_title(line):
  # 진짜 제목이면 제목 글자, 아니면 None
  if not line.startswith("#"):
    return None
  title = line.strip("# ").strip()
  return title if len(title) <= MAX_TITLE and not GRADE.search(title) else None


def pack(pieces, sep, max_chars):
  # 조각들을 순서대로 max_chars 안에서 최대한 묶음
  parts, cur = [], ""
  for piece in pieces:
    if cur and len(cur) + len(sep) + len(piece) > max_chars:
      parts.append(cur); cur = ""
    cur = f"{cur}{sep}{piece}" if cur else piece
  if cur.strip():
    parts.append(cur)
  return parts


def split_long(text, max_chars=MAX_CHARS):
  # 긴 절은 문단(빈 줄) → 줄(표라면 행) → 글자 수 순서로, 필요한 만큼만 잘게 자름
  pieces = []
  for para in text.split("\n\n"):
    if len(para) <= max_chars:
      pieces.append(para); continue
    for line in pack(para.split("\n"), "\n", max_chars):    # 표·목록은 줄 단위로
      while len(line) > max_chars:    # 줄 하나가 너무 길 때만 글자 수로
        pieces.append(line[:max_chars]); line = line[max_chars:]
      pieces.append(line)
  return pack(pieces, "\n\n", max_chars)


def merge_short(chunks, min_chars=100, max_chars=MAX_CHARS + 100):
  # 100자 미만 청크는 버리지 않고 앞 청크에, 앞이 꽉 찼으면 뒤 청크에 붙임 (제목을 같이 넣어 소속이 보이게)
  # 짧은 청크를 붙일 때만 MAX_CHARS를 100자까지 넘겨도 됨: 혼자 남아 검색에 안 걸리는 것보다 낫다
  def labeled(short, other):
    title = short["path"].split(" > ")[-1] if short["path"] != other["path"] else ""
    return f"{title}\n{short['text']}" if title else short["text"]

  def absorb(target, short, text):
    target["text"] = text
    target["pages"] = sorted(set(target["pages"]) | set(short["pages"]))

  out, carry = [], None    # carry = 앞에 못 붙어서 다음 청크 앞에 붙일 짧은 청크
  for c in chunks:
    if carry:
      add = labeled(carry, c)
      if len(add) + 2 + len(c["text"]) <= max_chars:
        absorb(c, carry, f"{add}\n\n{c['text']}")
      else:
        out.append(carry)    # 앞뒤 다 꽉 차면 그대로 둠
      carry = None
    prev = out[-1] if out else None
    if len(c["text"]) < min_chars and prev:
      add = labeled(c, prev)
      if len(prev["text"]) + 2 + len(add) <= max_chars:
        absorb(prev, c, f"{prev['text']}\n\n{add}")
        continue
      carry = c
      continue
    out.append(c)
  if carry:
    out.append(carry)
  for i, c in enumerate(out):    # 합친 뒤 ID 다시 매김
    c["id"] = f"{DOC_ID}-{i:04d}"
  return out


def make_chunks(pages, exclude_pages=EXCLUDE_PAGES):
  chunks, path, body, body_pages = [], [], [], set()

  def flush():
    text = "\n".join(body).strip()
    excluded = any(EXCLUDE_TITLES.search(t) for _, t in path)
    if text and not excluded:
      for part in split_long(text):
        chunks.append({
          "id": f"{DOC_ID}-{len(chunks):04d}",
          "doc_id": DOC_ID,
          "version": VERSION,
          "pages": sorted(body_pages),    # 출처 표시용
          "path": " > ".join(t for _, t in path),    # 예: 3 손위생 > 3.2 권고
          "text": part.strip(),
        })
    body.clear(); body_pages.clear()

  for p in pages:
    if any(a <= p["page"] <= b for a, b in exclude_pages):    # 범위 밖 장은 통째로 건너뜀
      flush(); path.clear()
      continue
    for line in p["text"].splitlines():
      title = heading_title(line)
      if title:    # 제목 줄 = 절 경계
        flush()
        level = len(line) - len(line.lstrip("#"))
        while path and path[-1][0] >= level:    # 같은·하위 단계 제목은 교체
          path.pop()
        path.append((level, title))
      else:
        if line.startswith("#"):    # 제목으로 잘못 잡힌 권고 문장 → 본문으로 내리되 청크는 여기서 끊음 (권고문 + 뒤따르는 설명이 한 청크)
          flush(); line = line.strip("# ")
        body.append(line)    # 빈 줄도 유지해야 문단 경계(\n\n)가 살아서 split_long이 문단 단위로 자름
        if line.strip():
          body_pages.add(p["page"])
  flush()
  return merge_short(chunks)


if __name__ == "__main__":
  pages = json.load(open(SRC, encoding="utf-8"))
  chunks = make_chunks(pages)
  with open(OUT, "w", encoding="utf-8") as f:
    json.dump(chunks, f, ensure_ascii=False, indent=1)
  print("청크 수:", len(chunks), "→", OUT)
