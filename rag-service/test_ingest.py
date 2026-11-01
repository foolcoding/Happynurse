import pymupdf
import pytest
from fastapi.testclient import TestClient

import index
import ingest
from parse import PDF

# 업로드 자동 반영 검사. 앞 4개는 GPU 없이, test_end_to_end만 Ollama(bge-m3) 필요
# 운영 DB(chroma/)와 기록 파일은 건드리지 않고 임시 폴더에서 돈다


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
  monkeypatch.setattr(ingest, "DOCS", tmp_path)
  monkeypatch.setattr(ingest, "REGISTRY", tmp_path / "registry.json")
  monkeypatch.setattr(index, "DB_DIR", str(tmp_path / "chroma"))
  return tmp_path


def blank_pdf(pages=12):
  doc = pymupdf.open()
  for _ in range(pages):
    doc.new_page()
  return doc.tobytes()


def test_parse_ranges():
  assert ingest.parse_ranges("151-160, 271 - 323,5") == [(151, 160), (271, 323), (5, 5)]
  assert ingest.parse_ranges("") == []
  with pytest.raises(ingest.Rejected):
    ingest.parse_ranges("151~160")


def test_accept(sandbox):
  pdf = blank_pdf()
  for args in [(b"hello", "doc-a", "v1", ""), (pdf, "Doc A", "v1", ""), (pdf, "doc-a", " ", "")]:
    with pytest.raises(ingest.Rejected):
      ingest.accept(*args)
  path, digest = ingest.accept(pdf, "doc-a", "v1", "")
  assert path.exists() and path.read_bytes() == pdf, "원본 보관 안 됨"
  ingest.update("doc-a", "live", version="v1", hash=digest)
  assert ingest.accept(pdf, "doc-a", "v1", "") is None, "운영 중인 같은 파일을 다시 처리함"


def test_registry_concurrent(sandbox):
  # 화면이 2초마다 상태를 읽는 동안 기록이 써져도 실패하지 않아야 함 (윈도우는 읽는 중인 파일을 교체 못 함)
  import threading
  stop, errors = threading.Event(), []

  def reader():
    while not stop.is_set():
      try:
        ingest.load_registry()
      except Exception as e:
        errors.append(e)

  threads = [threading.Thread(target=reader) for _ in range(4)]
  for t in threads:
    t.start()
  try:
    for i in range(300):
      ingest.update("doc-a", "job", step=str(i))
  finally:
    stop.set()
    for t in threads:
      t.join()
  assert not errors and ingest.load_registry()["doc-a"]["job"]["step"] == "299"


def test_checks_catch_bad_input():
  scanned = [{"page": i, "text": ""} for i in range(1, 21)]    # 글자 없는 스캔 PDF
  assert not all(c["ok"] for c in ingest.check_pages(scanned)), "스캔 PDF를 통과시킴"
  refs = [{"id": f"x-{i}", "path": "참고", "pages": [1], "text": "Kim et al. 2019; Lee et al. 2020; doi 10.1/x"}
          for i in range(10)]
  assert not all(c["ok"] for c in ingest.check_chunks(refs)), "문헌 목록뿐인 문서를 통과시킴"


def test_upload_api(sandbox, monkeypatch):
  client = TestClient(__import__("api").app)    # with 없이: 모델 미리 올리기(lifespan) 생략
  files = {"file": ("a.pdf", blank_pdf(), "application/pdf")}
  form = {"doc_id": "doc-a", "version": "v1"}
  monkeypatch.delenv("RAG_ADMIN_TOKEN", raising=False)
  assert client.post("/documents", files=files, data=form).status_code == 403, "토큰 설정 없이 업로드됨"
  monkeypatch.setenv("RAG_ADMIN_TOKEN", "t")
  assert client.post("/documents", files=files, data=form, headers={"X-Admin-Token": "x"}).status_code == 403
  bad = {"file": ("a.pdf", b"not a pdf", "application/pdf")}
  assert client.post("/documents", files=bad, data=form, headers={"X-Admin-Token": "t"}).status_code == 422


def test_end_to_end(sandbox):
  # 실제 지침서로 업로드 → 검사 → 운영 반영, 이어서 스캔 PDF 개정판은 떨어지고 운영 판은 유지되는지
  live = index.get_collection("live")
  staging = index.get_collection("staging")
  data = open(PDF, "rb").read()
  path, digest = ingest.accept(data, "kdca", "2017", "151-160, 271-323")
  ingest.run("kdca", "2017", path, digest, "151-160, 271-323", collection=live, staging=staging)
  entry = ingest.load_registry()["kdca"]
  print(f"\n지침서: {entry['job']['status']} · 청크 {live.count()} · 검사 {sum(c['ok'] for c in entry['job']['checks'])}/{len(entry['job']['checks'])}")
  assert entry["job"]["status"] == "pending", entry["job"].get("error")
  assert live.count() == 0 and entry["live"] is None, "승인 전에 운영에 들어감"
  ingest.decide("kdca", True, collection=live, staging=staging)
  entry = ingest.load_registry()["kdca"]
  print(f"승인 후: {entry['job']['status']} · 운영 청크 {live.count()}")
  assert entry["job"]["status"] == "live"
  assert entry["live"]["hash"] == digest and live.count() == entry["live"]["chunks"] and staging.count() == 0

  before = live.count()
  path, digest = ingest.accept(blank_pdf(), "kdca", "2026", "")
  ingest.run("kdca", "2026", path, digest, collection=live, staging=staging)
  entry = ingest.load_registry()["kdca"]
  print(f"스캔 PDF 개정판: {entry['job']['status']} · 운영 청크 {live.count()} · 운영 판 {entry['live']['version']}")
  assert entry["job"]["status"] == "failed" and entry["job"]["step"] == "parse"
  assert live.count() == before and entry["live"]["version"] == "2017", "실패한 판이 운영에 영향을 줌"
  with pytest.raises(ingest.Rejected):
    ingest.decide("kdca", True, collection=live, staging=staging)    # 실패한 판은 승인 불가
