import json
import time

import pytest
from fastapi.testclient import TestClient

from api import app

# API 배선 검사 (Ollama 필요). 답 내용은 출력하지 않고 이벤트 순서·개수·시간만 본다


@pytest.fixture(scope="module")
def client():
  with TestClient(app) as c:    # with: 서버 시작 시 모델 미리 올리는 lifespan까지 실행
    yield c


def events(resp):
  # SSE 응답을 (이벤트 이름, 데이터) 목록으로
  out = []
  for block in resp.text.strip().split("\n\n"):
    lines = dict(l.split(": ", 1) for l in block.split("\n"))
    out.append((lines["event"], json.loads(lines["data"])))
  return out


def test_validation(client):
  assert client.post("/ask", json={"question": ""}).status_code == 422, "빈 질문을 막지 못함"
  assert client.post("/ask", json={"question": "가" * 501}).status_code == 422, "너무 긴 질문을 막지 못함"
  assert client.post("/ask", json={"question": "   "}).status_code == 422, "공백 질문을 막지 못함"


def test_ask_refuses_off_topic(client):
  r = client.post("/ask", json={"question": "비트코인 시세 알려줘"}).json()
  assert r["sources"] == [] and "찾지 못했습니다" in r["answer"], "무관한 질문에 답함"


def test_stream_off_topic(client):
  ev = [e for e, _ in events(client.post("/ask/stream", json={"question": "파스타 맛있게 만드는 법"}))]
  assert ev == ["refused", "done"], f"거절 이벤트 순서가 다름: {ev}"


def test_stream_answer(client):
  # 출처 → 토큰 여러 개 → done 순서만 본다
  # TestClient는 응답을 다 모은 뒤 넘겨줘서 첫 토큰 시간을 못 잰다 → 시간은 실제 서버(uvicorn)로 잴 것
  t = time.perf_counter()
  names = []
  with client.stream("POST", "/ask/stream", json={"question": "손 소독제로 손위생할 때 얼마나 문질러야 해?"}) as resp:
    assert resp.headers["content-type"].startswith("text/event-stream")
    for line in resp.iter_lines():
      if line.startswith("event: "):
        names.append(line[7:])
  total = time.perf_counter() - t
  tokens = names.count("token")
  print(f"\n이벤트 {names[0]} → token {tokens}개 → {names[-1]} · 전체 {total:.2f}초")
  assert names[0] == "sources" and names[-1] == "done" and tokens > 1, f"스트리밍 순서가 다름: {names[:3]}…"
