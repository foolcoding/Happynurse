import hashlib
import json
import random
import re
import threading
import time
from collections import Counter
from pathlib import Path

from chunk import MAX_CHARS, make_chunks, noise_signals
from index import embed, embed_text, get_collection, index
from parse import parse_pages

# 업로드된 PDF를 검사를 통과할 때만 검색에 넣는다
# parse → 검사 → chunk → 검사 → 임시 컬렉션에 색인 → 검사 → 승인 대기 → 관리자 승인 → 운영 컬렉션으로 옮김
# 검사는 문서가 기술적으로 멀쩡한지만 본다. 지침 문서가 맞는지는 관리자가 승인으로 판단
# 하나라도 떨어지거나 반려되면 운영 컬렉션은 그대로 (옛 판으로 계속 답함)

DOCS = Path("docs")
REGISTRY = DOCS / "registry.json"    # 문서별 운영 중인 판과 마지막 작업 기록
STAGING = "guides_staging"    # 검사 전 임시 컬렉션
MAX_BYTES = 50 * 1024 * 1024
DOC_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,49}$")

_job = threading.Lock()    # 한 번에 문서 하나 (GPU 한 장)
_reg = threading.RLock()    # 기록 파일 읽기·쓰기를 한 줄로: 윈도우는 누가 읽는 중인 파일을 교체하지 못함


class Rejected(Exception):
  pass


# ── 기록 ──

def load_registry():
  with _reg:
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}


def replace(tmp, target, tries=20):
  # 백신·검색 색인 같은 다른 프로그램이 잠깐 파일을 열고 있으면 교체가 거부됨 → 잠깐 기다렸다 다시
  for i in range(tries):
    try:
      return tmp.replace(target)
    except PermissionError:
      if i == tries - 1:
        raise
      time.sleep(0.05)


def update(doc_id, part, **fields):
  # part: "live"(운영 중인 판) 또는 "job"(마지막 업로드 작업)
  with _reg:
    reg = load_registry()
    entry = reg.setdefault(doc_id, {"live": None, "job": None})
    entry[part] = {**(entry[part] or {}), **fields, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    replace(tmp, REGISTRY)    # 임시 파일에 다 쓴 뒤 교체: 쓰다 죽어도 기록 파일이 반쯤 깨지지 않게


# ── 업로드 받기 ──

def parse_ranges(spec):
  # "151-160, 271-323" → [(151, 160), (271, 323)]
  out = []
  for part in filter(None, (p.strip() for p in (spec or "").split(","))):
    m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
    if not m:
      raise Rejected(f"제외 쪽 형식이 잘못됨: {part}")
    a, b = int(m[1]), int(m[2] or m[1])
    out.append((min(a, b), max(a, b)))
  return out


def accept(data, doc_id, version, exclude):
  # 받기 전 검사. 통과하면 (저장 경로, 해시), 이미 운영 중인 같은 파일이면 None
  if not DOC_ID.match(doc_id):
    raise Rejected("문서 ID는 영문 소문자·숫자·하이픈 3~50자")
  if not version.strip():
    raise Rejected("판 정보가 비어 있음")
  if len(data) > MAX_BYTES:
    raise Rejected("50MB 초과")
  if not data.startswith(b"%PDF-"):    # 확장자가 아니라 내용으로 확인
    raise Rejected("PDF 파일이 아님")
  parse_ranges(exclude)
  digest = hashlib.sha256(data).hexdigest()
  live = load_registry().get(doc_id, {}).get("live")
  if live and live["hash"] == digest:
    return None
  path = DOCS / "archive" / doc_id / f"{digest[:12]}.pdf"    # 판마다 원본 보관 (감사·되돌리기용)
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(data)
  return path, digest


# ── 검사: 기존 test_parse·test_chunk·test_index 기준을 그대로 옮김 ──

def check(name, value, limit, ok):
  return {"name": name, "value": value, "limit": limit, "ok": bool(ok)}


def check_pages(pages):
  n = len(pages)
  texty = sum(len(re.findall(r"[가-힣A-Za-z]", p["text"])) >= 50 for p in pages)
  digit_only, seen = 0, Counter()
  for p in pages:
    lines = {l.strip().strip("*#_ ") for l in p["text"].splitlines()}
    lines = {l for l in lines if l and not set(l) <= set("|-: ")}
    digit_only += sum(l.isdigit() for l in lines)
    seen.update(lines)
  repeated = sum(c >= n * 0.1 for c in seen.values()) if n >= 10 else 0
  heads = sum(l.startswith("#") for p in pages for l in p["text"].splitlines())
  return [
    check("글자가 있는 쪽 비율", round(texty / max(n, 1), 2), ">= 0.7 (낮으면 스캔 PDF)", n and texty >= n * 0.7),
    check("숫자만 있는 줄", digit_only, f"< {n * 0.2:.0f} (쪽 번호 잔여)", digit_only < n * 0.2),
    check("여러 쪽에 반복되는 줄", repeated, "<= 3 (머리말 잔여)", repeated <= 3),
    check("제목 수", heads, ">= 1 (구조 인식)", heads >= 1),
  ]


def check_chunks(chunks):
  n = len(chunks)
  refs = sum("인용 목록" in noise_signals(c) for c in chunks)
  return [
    check("청크 수", n, ">= 1", n >= 1),
    check("최대 길이", max((len(c["text"]) for c in chunks), default=0), f"<= {MAX_CHARS + 100}",
          all(len(c["text"]) <= MAX_CHARS + 100 for c in chunks)),
    check("쪽 번호 없는 청크", sum(not c["pages"] for c in chunks), "0", all(c["pages"] for c in chunks)),
    check("문헌 목록 청크", refs, f"<= {n * 0.02:.0f} (2%)", refs <= n * 0.02),
  ]


def check_index(col, chunks, seed=0):
  random.seed(seed)
  stored = col.get(where={"doc_id": chunks[0]["doc_id"]}, include=["embeddings"])
  picks = random.sample(chunks, min(50, len(chunks)))
  res = col.query(query_embeddings=embed([embed_text(c) for c in picks]), n_results=1)
  self_hit = sum(ids[0] == c["id"] for c, ids in zip(picks, res["ids"]))
  titled = [c for c in chunks if " > " in c["path"]]
  tpicks = random.sample(titled, min(30, len(titled)))
  title_hit = 0
  if tpicks:
    res = col.query(query_embeddings=embed([c["path"].split(" > ")[-1] for c in tpicks]), n_results=3,
                    include=["metadatas"])
    for c, metas in zip(tpicks, res["metadatas"]):
      found = {p for m in metas for p in m["pages"].split(",")}
      title_hit += any(str(p) in found for p in c["pages"])
  return [
    check("저장된 청크", len(stored["ids"]), f"= {len(chunks)}", len(stored["ids"]) == len(chunks)),
    check("임베딩 차원", len(stored["embeddings"][0]), "= 1024 (bge-m3)", len(stored["embeddings"][0]) == 1024),
    check("자기 검색 1등", f"{self_hit}/{len(picks)}", ">= 90%", self_hit >= len(picks) * 0.9),
    check("제목 검색 top-3", f"{title_hit}/{len(tpicks)}", ">= 60%", not tpicks or title_hit >= len(tpicks) * 0.6),
  ]


# ── 실행 ──

def promote(doc_id, staging, live):
  # 검사를 통과한 청크를 임베딩 다시 하지 않고 운영 컬렉션으로 복사, 같은 문서의 옛 판은 삭제
  data = staging.get(where={"doc_id": doc_id}, include=["embeddings", "documents", "metadatas"])
  live.delete(where={"doc_id": doc_id})    # ponytail: 지우고 넣는 사이 수 ms 공백, 무중단이 필요하면 컬렉션 별칭 교체로
  for i in range(0, len(data["ids"]), 256):
    s = slice(i, i + 256)
    live.add(ids=data["ids"][s], embeddings=data["embeddings"][s], documents=data["documents"][s],
             metadatas=data["metadatas"][s])
  staging.delete(where={"doc_id": doc_id})


def run(doc_id, version, path, digest, exclude="", collection=None, staging=None):
  checks = []

  def gate(step, results):
    checks.extend(results)
    update(doc_id, "job", step=step, checks=checks)
    failed = [c["name"] for c in results if not c["ok"]]
    if failed:
      raise Rejected(f"{step} 검사 실패: {', '.join(failed)}")

  with _job:
    try:
      update(doc_id, "job", status="processing", step="parse", error=None)
      pages = parse_pages(str(path))
      gate("parse", check_pages(pages))
      chunks = make_chunks(pages, parse_ranges(exclude), doc_id, version)
      gate("chunk", check_chunks(chunks))
      staging = staging or get_collection(STAGING)
      staging.delete(where={"doc_id": doc_id})
      index(chunks, staging)
      gate("index", check_index(staging, chunks))
      update(doc_id, "job", status="pending", step="approve", hash=digest, path=str(path), chunks=len(chunks))
    except Rejected as e:
      update(doc_id, "job", status="failed", error=str(e))
    except Exception as e:    # 파서·Ollama 오류 등: 운영 컬렉션은 건드리지 않은 상태
      update(doc_id, "job", status="failed", error=f"{type(e).__name__}: {e}")


def decide(doc_id, approve, collection=None, staging=None):
  # 관리자 결정: 승인이면 임시 컬렉션 → 운영, 반려면 임시 컬렉션만 비움
  with _job:
    job = (load_registry().get(doc_id) or {}).get("job") or {}
    if job.get("status") != "pending":
      raise Rejected("승인 대기 중인 판이 없음")
    staging = staging or get_collection(STAGING)
    if not approve:
      staging.delete(where={"doc_id": doc_id})
      update(doc_id, "job", status="rejected", step="done")
      return
    promote(doc_id, staging, collection or get_collection())
    # 해시는 운영 반영이 끝난 뒤에 기록: 중간에 실패한 판을 '이미 처리됨'으로 건너뛰지 않게
    update(doc_id, "live", version=job["version"], hash=job["hash"], file=job["path"], chunks=job["chunks"])
    update(doc_id, "job", status="live", step="done")
    from ask import keyword_index
    keyword_index.cache_clear()    # 키워드 검색 통계를 새 청크로 다시 만들게
