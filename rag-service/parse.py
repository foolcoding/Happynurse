import json
import pymupdf4llm

PDF = "docs/의료관련감염 표준예방지침서(웹용-수정-20190712).pdf"
OUT = "pages.json"

# 2.0 레이아웃 모드는 margins를 조용히 무시함 → 레이아웃 모델이 찾은 머리말·꼬리말을 빼는 옵션 사용
OPTS = dict(header=False, footer=False)


def parse_pages(pdf=PDF):
  # 쪽 단위 마크다운. page = PDF 쪽 번호 (이 문서는 인쇄 쪽 번호와 같음, 71쪽에서 확인)
  chunks = pymupdf4llm.to_markdown(pdf, page_chunks=True, **OPTS)
  return [{"page": i + 1, "text": c["text"]} for i, c in enumerate(chunks)]


if __name__ == "__main__":
  pages = parse_pages()
  with open(OUT, "w", encoding="utf-8") as f:
    json.dump(pages, f, ensure_ascii=False, indent=1)    # 한글 그대로 저장
  print("쪽 수:", len(pages), "→", OUT)
