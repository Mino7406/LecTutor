"""Gemini API와 통신하는 부분만 모아둔 모듈.

Streamlit 관련 코드는 두지 않는다 (app.py가 UI를 담당).
google-generativeai는 지원 종료(deprecated)되어, 최신 google-genai SDK를 사용한다.
"""

import json
import re

from google import genai
from google.genai import types

from core.prompts import build_structure_prompt, build_translation_prompt, build_ocr_prompt

MODEL_NAME = "gemini-2.5-flash"

_client: genai.Client | None = None


def configure(api_key: str) -> None:
    global _client
    _client = genai.Client(api_key=api_key)


def clean_json_string(raw: str) -> str:
    """AI가 ```json ... ``` 로 감싸서 응답할 경우 순수 JSON만 추출."""
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        return match.group(1)
    return raw


def count_tokens(text: str, api_key: str | None) -> int:
    """토큰 수를 계산. API 키가 없거나 오류가 나면 글자수 기반 추산치를 반환."""
    if not api_key or _client is None:
        return len(text) // 4
    try:
        return _client.models.count_tokens(model=MODEL_NAME, contents=text).total_tokens
    except Exception:
        return len(text) // 4


def get_chapter_structure(pages_data: list[dict]) -> dict | None:
    """페이지별 헤더 정보를 보고 과목명 + 챕터 구조(JSON)를 요청.

    반환값: {"subject_title": str, "chapters": [...]} 또는 실패 시 {"error": ...}.
    """
    prompt = build_structure_prompt(pages_data)
    response = None
    try:
        response = _client.models.generate_content(model=MODEL_NAME, contents=prompt)
        cleaned = clean_json_string(response.text)
        return json.loads(cleaned)
    except Exception as e:
        return {"error": str(e), "raw_response": getattr(response, "text", None)}


def translate_chapter(
    subject_title: str,
    chapter_title: str,
    full_text: str,
    context_summary: str,
    context_glossary: dict,
) -> dict | None:
    """챕터 원문을 번역+튜터링 스크립트(JSON)로 변환."""
    prompt = build_translation_prompt(
        subject_title, chapter_title, full_text, context_summary, context_glossary
    )
    config = types.GenerateContentConfig(max_output_tokens=8000, temperature=0.2)

    try:
        response = _client.models.generate_content(
            model=MODEL_NAME, contents=prompt, config=config
        )
        cleaned = clean_json_string(response.text)
        return json.loads(cleaned)
    except Exception as e:
        return {"error": str(e)}


def ocr_image(image) -> str:
    """스캔/사진 페이지 이미지(PIL.Image)에서 텍스트를 추출."""
    try:
        response = _client.models.generate_content(
            model=MODEL_NAME, contents=[build_ocr_prompt(), image]
        )
        return response.text.strip()
    except Exception as e:
        return f"[OCR 실패: {e}]"
