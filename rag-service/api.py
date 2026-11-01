import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ask import NOT_FOUND, SYSTEM, ask, chat_stream, keyword_index, prepare, reranker, strip_lead

# 실행: uvicorn api:app --port 8000
# POST /ask         → 답 전체를 JSON으로 한 번에
# POST /ask/stream  → SSE: sources(출처) → token(답 조각)… → done


@asynccontextmanager
async def lifespan(app):
  # 서버 켤 때 리랭커·키워드 색인을 미리 올림 → 첫 질문이 수십 초 걸리지 않게
  reranker()
  keyword_index()
  yield


app = FastAPI(title="HappyNurse 지침 RAG", lifespan=lifespan)


class Question(BaseModel):
  question: str = Field(min_length=1, max_length=500)    # 입력 검증: 빈 질문·과도한 길이 차단


def check(q):
  if not q.question.strip():
    raise HTTPException(422, "질문이 비어 있습니다")
  return q.question.strip()


@app.get("/health")
def health():
  return {"ok": True}


@app.post("/ask")
def ask_once(q: Question):
  return ask(check(q))


def sse(event, data):
  # SSE 한 건: 'event: 이름' + 'data: JSON' + 빈 줄. JSON으로 감싸야 답 안의 줄바꿈이 안 깨짐
  return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_events(question):
  prompt, sources, scores = prepare(question)
  if prompt is None:    # 근거 없음 → LLM 안 부르고 바로 거절
    yield sse("refused", {"answer": NOT_FOUND, "scores": scores})
  else:
    yield sse("sources", {"sources": sources, "scores": scores})    # 출처를 먼저 보내 화면에 바로 표시
    try:
      for piece in strip_lead(chat_stream(SYSTEM, prompt), question):
        yield sse("token", {"t": piece})
    except Exception:    # Ollama가 죽는 등 생성 중 오류: 연결을 그냥 끊지 않고 알림
      yield sse("error", {"message": "답변 생성 중 오류가 발생했습니다"})
  yield sse("done", {})


@app.post("/ask/stream")
def ask_stream(q: Question):
  return StreamingResponse(
    stream_events(check(q)),
    media_type="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},    # 프록시가 모아서 보내지 않게
  )
