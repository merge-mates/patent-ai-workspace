"""폴더 안 통지서 PDF마다 쪽 글자가 뽑히는지 손으로 확인한다.

파일마다 `이름 쪽수 글자수 상태` 한 줄. 원문 글자는 출력하지 않는다.
읽기 실패 파일은 이유 줄을 찍고 계속하며, 하나라도 실패하거나 PDF가 없으면 종료 코드 1.

실행: uv run python scripts/check_pages.py <PDF 폴더>
"""

import sys
from pathlib import Path

from patent_ai.core.f1_oa_reader.pages import PdfReadError, extract_pages


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("사용법: check_pages.py <PDF 폴더>", file=sys.stderr)
        return 1
    folder = Path(argv[1])
    if not folder.is_dir():
        print(f"폴더가 없음: {folder}", file=sys.stderr)
        return 1
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"경고: PDF가 하나도 없음: {folder}", file=sys.stderr)
        return 1
    failed = 0
    for pdf in pdfs:
        try:
            result = extract_pages(pdf, pdf.stem)
        except PdfReadError as e:
            print(f"{pdf.name} 읽기 실패: {e}")
            failed += 1
            continue
        chars = sum(len(p.text) for p in result.pages)
        status = result.status.value.value
        if result.status.reason is not None:  # unverified면 이유도
            status += f"({result.status.reason.value})"
        print(f"{pdf.name} {len(result.pages)}쪽 {chars}자 {status}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
