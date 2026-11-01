import pymupdf

from parse import PDF

# 문서 담당자용: PDF 책갈피(장 목록)와 쪽 범위만 출력 → 답변 근거에서 뺄 장을 정해 chunk.py EXCLUDE_PAGES에 적는다

doc = pymupdf.open(PDF)
toc = doc.get_toc()
for i, (level, title, page) in enumerate(toc):
  end = toc[i + 1][2] - 1 if i + 1 < len(toc) else doc.page_count
  print(f"{page:>3}–{end:<3} {'  ' * (level - 1)}{title}")
