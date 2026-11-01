import random

import pytest

from index import embed, embed_text, get_collection

# Ollama(bge-m3)가 켜져 있어야 함


@pytest.fixture(scope="module")
def col():
  return get_collection()


def test_store(saved_chunks, col):
  db = col.get(include=[])["ids"]
  print(f"\n청크 {len(saved_chunks)}개 · DB {len(db)}개")
  assert set(db) == {c["id"] for c in saved_chunks}, "DB와 chunks.json의 청크가 다름 → python index.py 다시 실행"

  sample = col.get(ids=[saved_chunks[0]["id"]], include=["embeddings", "metadatas"])
  assert len(sample["embeddings"][0]) == 1024, "bge-m3 차원(1024)과 다름 → 다른 모델로 임베딩됨"
  assert sample["metadatas"][0]["pages"], "쪽 번호 메타데이터 없음"


def test_self_retrieval(saved_chunks, col, n=50):
  # 청크 자신으로 검색하면 1등에 자기가 나와야 함
  random.seed(0)
  picks = random.sample(saved_chunks, n)
  res = col.query(query_embeddings=embed([embed_text(c) for c in picks]), n_results=1)
  hit = sum(ids[0] == c["id"] for c, ids in zip(picks, res["ids"]))
  print(f"\n자기 검색 1등 {hit}/{n}")
  assert hit >= n * 0.9, "자기 자신을 못 찾는 청크가 많음 → 임베딩이나 저장이 꼬임"
