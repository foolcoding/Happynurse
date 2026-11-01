import json

import pytest

# 회사 방식: 테스트는 숫자·통과 여부만 출력한다. 문서 내용은 출력하지 않는다
# 실행: pytest -s 파일명  (-s 가 있어야 숫자가 보임)


@pytest.fixture(scope="session")
def pages():
  return json.load(open("pages.json", encoding="utf-8"))


@pytest.fixture(scope="session")
def chunks(pages):
  # 지금 코드로 다시 만든 청크 (저장된 파일이 아니라 현재 로직을 검사)
  from chunk import make_chunks
  return make_chunks(pages)


@pytest.fixture(scope="session")
def saved_chunks():
  # 인덱스에 실제로 들어간 청크
  return json.load(open("chunks.json", encoding="utf-8"))
