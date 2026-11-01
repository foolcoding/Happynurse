import json
import urllib.request

import chromadb

SRC = "chunks.json"
DB_DIR = "chroma"    # 벡터DB 저장 폴더
COLLECTION = "guides"
EMBED_MODEL = "bge-m3"
OLLAMA = "http://127.0.0.1:11434"    # localhost로 쓰면 윈도우가 IPv6(::1)부터 시도해 요청마다 약 2초 지연
BATCH = 32    # 한 번에 임베딩할 청크 수


def embed(texts):
  # Ollama 임베딩 API: 여러 문장을 한 번에 벡터로
  body = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
  req = urllib.request.Request(f"{OLLAMA}/api/embed", body, {"Content-Type": "application/json"})
  return json.load(urllib.request.urlopen(req))["embeddings"]


def embed_text(c):
  # 제목 경로를 본문 앞에 붙여 임베딩: 짧은 청크도 어느 절 내용인지 문맥이 생김
  return f"{c['path']}\n{c['text']}" if c["path"] else c["text"]


def get_collection(name=COLLECTION):
  client = chromadb.PersistentClient(path=DB_DIR)
  return client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})


def index(chunks, col):
  # 같은 문서의 옛 청크를 지우고 새로 넣음 → 판이 바뀌어도 옛 판과 섞이지 않음
  for doc_id in {c["doc_id"] for c in chunks}:
    col.delete(where={"doc_id": doc_id})
  for i in range(0, len(chunks), BATCH):
    batch = chunks[i:i + BATCH]
    col.add(
      ids=[c["id"] for c in batch],
      embeddings=embed([embed_text(c) for c in batch]),
      documents=[c["text"] for c in batch],    # LLM에 넘길 원문 (제목 경로 없이)
      metadatas=[{
        "doc_id": c["doc_id"],
        "version": c["version"],
        "path": c["path"],
        "pages": ",".join(map(str, c["pages"])),    # Chroma 메타데이터는 리스트 불가 → 문자열
      } for c in batch],
    )
    print(f"{min(i + BATCH, len(chunks))}/{len(chunks)}", end="\r")
  print()


if __name__ == "__main__":
  chunks = json.load(open(SRC, encoding="utf-8"))
  col = get_collection()
  index(chunks, col)
  print("저장된 청크:", col.count(), "→", DB_DIR)
