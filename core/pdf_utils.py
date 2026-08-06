"""PDF 파일을 다루는 로컬 처리 (텍스트 추출, 페이지 이미지 렌더링).

AI 호출은 하지 않는다 - OCR이 필요한 페이지를 감지만 하고, 실제 OCR 호출은
호출부에서 넘겨준 콜백(ocr_fn)에 위임한다.
"""

import io

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image

SPARSE_TEXT_THRESHOLD = 15  # 이 글자수 미만이면 스캔/사진 페이지로 간주


def extract_page_text(page) -> str:
    text = page.extract_text()
    return text or ""


def needs_ocr(text: str) -> bool:
    return len(text.strip()) < SPARSE_TEXT_THRESHOLD


def render_page_as_image(file_buffer, page_index: int, dpi: int = 200) -> Image.Image:
    """PyMuPDF로 특정 페이지를 이미지로 렌더링 (0-based index)."""
    file_buffer.seek(0)
    doc = fitz.open(stream=file_buffer.read(), filetype="pdf")
    page = doc[page_index]
    zoom = dpi / 72
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    doc.close()
    return image


def scan_pdf(file_buffer, count_tokens_fn, progress_callback=None) -> list[dict]:
    """PDF를 페이지별로 스캔해서 헤더/토큰수/OCR 필요 여부를 추출.

    count_tokens_fn(text) -> int
    progress_callback(done, total) -> None (선택, UI 진행률 표시용)
    """
    pages_data = []
    file_buffer.seek(0)

    with pdfplumber.open(file_buffer) as pdf:
        total_pages = len(pdf.pages)

        for i, page in enumerate(pdf.pages):
            text = extract_page_text(page)
            ocr_flag = needs_ocr(text)

            if ocr_flag:
                header_candidate = "(스캔/사진 페이지로 추정 - 번역 시 자동 OCR 적용)"
                token_count = 0  # 실제 텍스트는 번역 단계에서 OCR로 얻으므로 사전 추산 불가
            else:
                lines = text.split("\n")
                header_candidate = " ".join(lines[:3]) if lines else "(내용 없음)"
                if len(header_candidate) > 150:
                    header_candidate = header_candidate[:150] + "..."
                token_count = count_tokens_fn(text)

            pages_data.append({
                "page_num": i + 1,
                "header_preview": header_candidate,
                "token_count": token_count,
                "needs_ocr": ocr_flag,
            })

            if progress_callback:
                progress_callback(i + 1, total_pages)

    return pages_data


def extract_text_by_range(file_buffer, start_p: int, end_p: int, ocr_fn=None) -> str:
    """start_p~end_p(1-based, 포함) 범위의 텍스트를 추출.

    OCR이 필요한 페이지는 ocr_fn(PIL.Image) -> str 콜백으로 텍스트를 얻는다.
    ocr_fn이 없으면 스캔 페이지는 빈 텍스트로 남는다.
    """
    text_content = ""
    file_buffer.seek(0)

    with pdfplumber.open(file_buffer) as pdf:
        for i in range(start_p - 1, end_p):
            if i >= len(pdf.pages):
                continue

            page_text = extract_page_text(pdf.pages[i])

            if needs_ocr(page_text) and ocr_fn is not None:
                image = render_page_as_image(file_buffer, i)
                page_text = ocr_fn(image)
                text_content += f"\n--- Page {i + 1} (OCR) ---\n{page_text}\n"
            else:
                text_content += f"\n--- Page {i + 1} ---\n{page_text}\n"

    return text_content
