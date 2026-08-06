"""Gemini API와 통신하는 부분만 모아둔 모듈.

Streamlit 관련 코드는 두지 않는다 (app.py가 UI를 담당).
google-generativeai는 지원 종료(deprecated)되어, 최신 google-genai SDK를 사용한다.

모델명은 하드코딩하지 않는다 - Google이 수시로 모델을 은퇴시키므로(예: gemini-2.5-flash가
"no longer available to new users"로 막힌 사례), 키가 실제로 쓸 수 있는 모델 목록을
list_available_models()로 동적으로 조회해서 사용한다.
"""

import json
import re

from google import genai
from google.genai import types

from core.prompts import build_structure_prompt, build_translation_prompt, build_ocr_prompt

_client: genai.Client | None = None

# 자동 추천 시 이름에 이 단어가 들어간 모델은 감점 (경량/특수 목적 모델 등)
_DEPRIORITIZED_KEYWORDS = ["lite", "8b", "image", "tts", "embedding", "vision", "live", "thinking", "exp", "preview"]

_STRUCTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "subject_title": {"type": "string"},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chapter_num": {"type": "integer"},
                    "title": {"type": "string"},
                    "start_page": {"type": "integer"},
                    "end_page": {"type": "integer"},
                },
                "required": ["chapter_num", "title", "start_page", "end_page"],
            },
        },
    },
    "required": ["subject_title", "chapters"],
}

_TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "translated_content": {"type": "string"},
        "new_summary": {"type": "string"},
        # Gemini Developer API의 response_schema는 additionalProperties(임의 키 dict)를
        # 지원하지 않아서, {용어: 번역} 대신 [{term, translation}] 배열로 받는다.
        "updated_glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "translation": {"type": "string"},
                },
                "required": ["term", "translation"],
            },
        },
    },
    "required": ["translated_content", "new_summary", "updated_glossary"],
}


def configure(api_key: str) -> None:
    global _client
    _client = genai.Client(api_key=api_key)


def clean_json_string(raw: str) -> str:
    """AI가 ```json ... ``` 로 감싸서 응답할 경우 순수 JSON만 추출."""
    match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        return match.group(1)
    return raw


def list_available_models() -> list[str]:
    """현재 키로 generateContent가 가능한 모델 이름 목록을 조회."""
    if _client is None:
        return []
    names = []
    try:
        for m in _client.models.list():
            actions = m.supported_actions or []
            if "generateContent" in actions and m.name:
                names.append(m.name.removeprefix("models/"))
    except Exception:
        return []
    return names


def pick_default_model(model_names: list[str]) -> str | None:
    """모델 목록 중 번역 작업에 쓸만한 기본값을 하나 추천."""
    if not model_names:
        return None

    def score(name: str):
        penalty = sum(1 for kw in _DEPRIORITIZED_KEYWORDS if kw in name)
        version_match = re.search(r"(\d+(?:\.\d+)?)", name)
        version = float(version_match.group(1)) if version_match else 0.0
        is_flash = 1 if "flash" in name else 0
        return (is_flash, -penalty, version)

    return sorted(model_names, key=score, reverse=True)[0]


def count_tokens(text: str, api_key: str | None, model: str | None) -> int:
    """토큰 수를 계산. API 키/모델이 없거나 오류가 나면 글자수 기반 추산치를 반환."""
    if not api_key or not model or _client is None:
        return len(text) // 4
    try:
        return _client.models.count_tokens(model=model, contents=text).total_tokens
    except Exception:
        return len(text) // 4


_model_output_limits: dict[str, int] = {}


def _get_output_token_limit(model: str) -> int | None:
    """모델별 최대 출력 토큰 한도를 조회 (캐시해서 매 호출마다 API를 부르지 않도록 함)."""
    if model in _model_output_limits:
        return _model_output_limits[model]
    try:
        info = _client.models.get(model=model)
        limit = info.output_token_limit
        if limit:
            _model_output_limits[model] = limit
        return limit
    except Exception:
        return None


def _generate_json(model: str, prompt: str, schema: dict, max_output_tokens: int) -> dict:
    """스키마를 강제해서 유효한 JSON 응답을 받아온다.

    최신 Gemini 모델은 내부적으로 'thinking' 토큰을 먼저 소모하는데, max_output_tokens
    한도 안에서 thinking만 하다가 실제 답변을 못 내는 경우(빈 응답)가 있어서
    thinking을 꺼서 재시도하는 폴백을 둔다.
    """
    last_error = None
    limit = _get_output_token_limit(model)
    if limit:
        max_output_tokens = min(max_output_tokens, limit)

    for thinking_budget in (0, None):
        config_kwargs = dict(
            max_output_tokens=max_output_tokens,
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=schema,
        )
        if thinking_budget is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)

        try:
            response = _client.models.generate_content(
                model=model, contents=prompt, config=types.GenerateContentConfig(**config_kwargs)
            )
        except Exception as e:
            last_error = e
            continue  # 이 모델이 thinking_budget=0을 지원 안 할 수 있으니 다음 옵션으로 재시도

        text = (response.text or "").strip()
        if not text:
            finish_reason = None
            try:
                finish_reason = response.candidates[0].finish_reason
            except Exception:
                pass
            last_error = ValueError(
                f"AI가 빈 응답을 반환했습니다 (finish_reason={finish_reason}). "
                "출력 토큰 한도를 늘리거나 다시 시도해보세요."
            )
            continue

        return json.loads(clean_json_string(text))

    raise last_error or RuntimeError("응답 생성에 실패했습니다.")


def get_chapter_structure(pages_data: list[dict], model: str) -> dict | None:
    """페이지별 헤더 정보를 보고 과목명 + 챕터 구조(JSON)를 요청.

    반환값: {"subject_title": str, "chapters": [...]} 또는 실패 시 {"error": ...}.
    """
    prompt = build_structure_prompt(pages_data)
    try:
        return _generate_json(model, prompt, _STRUCTURE_SCHEMA, max_output_tokens=4000)
    except Exception as e:
        return {"error": str(e)}


def translate_chapter(
    subject_title: str,
    chapter_title: str,
    full_text: str,
    context_summary: str,
    context_glossary: dict,
    model: str,
) -> dict | None:
    """챕터 원문을 번역+튜터링 스크립트(JSON)로 변환."""
    prompt = build_translation_prompt(
        subject_title, chapter_title, full_text, context_summary, context_glossary
    )
    try:
        result = _generate_json(model, prompt, _TRANSLATION_SCHEMA, max_output_tokens=32000)
    except Exception as e:
        return {"error": str(e)}

    # 스키마 상 배열([{term, translation}])로 받은 용어집을 dict로 변환해서 반환
    glossary_list = result.get("updated_glossary") or []
    result["updated_glossary"] = {
        item["term"]: item["translation"]
        for item in glossary_list
        if isinstance(item, dict) and item.get("term")
    }
    return result


def ocr_image(image, model: str) -> str:
    """스캔/사진 페이지 이미지(PIL.Image)에서 텍스트를 추출."""
    try:
        response = _client.models.generate_content(
            model=model, contents=[build_ocr_prompt(), image]
        )
        return response.text.strip()
    except Exception as e:
        return f"[OCR 실패: {e}]"
