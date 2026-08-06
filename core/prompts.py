"""AI에게 보내는 프롬프트를 만드는 함수 모음.

문자열 조립만 담당하고 API 호출은 하지 않는다 (ai_client.py가 담당).
"""

import json


def build_structure_prompt(pages_data: list[dict]) -> str:
    """페이지별 헤더 목록을 보고 과목명과 챕터 구조를 요청하는 프롬프트."""
    simplified_data = [
        f"P{item['page_num']}: {item['header_preview']}"
        for item in pages_data
    ]
    json_input = json.dumps(simplified_data, ensure_ascii=False, indent=2)

    return f"""You are a curriculum expert analyzing a university lecture slide deck.

[Task]
1. Infer the subject name and identify this is which chapter, based on the page headers below (look at the first few pages especially).
2. Group consecutive pages into logical 'Chapters'.

[Rules]
- Every page from the start to the end must be included in exactly one chapter.
- 'title' should summarize the chapter's topic in Korean.
- 'subject_title' should be formatted like "[과목명] N장 : (챕터 이름)" in Korean. If information is insufficient, make your best guess and mark it with "(추정)".
- Return ONLY a valid JSON object. Do not add any explanation, and do not wrap it in markdown code fences.

[Input Data]
{json_input}

[Output Format]
{{
    "subject_title": "[예: 회로이론] 1장 : 라플라스 변환",
    "chapters": [
        {{"chapter_num": 1, "title": "개요", "start_page": 1, "end_page": 5}},
        {{"chapter_num": 2, "title": "주요 개념 A", "start_page": 6, "end_page": 15}}
    ]
}}"""


def build_translation_prompt(
    subject_title: str,
    chapter_title: str,
    full_text: str,
    context_summary: str,
    context_glossary: dict,
) -> str:
    """챕터 원문을 번역+튜터링 스크립트로 변환하는 프롬프트 (강의자료 번역기 v3.0 규칙 반영)."""
    glossary_str = json.dumps(context_glossary, ensure_ascii=False) if context_glossary else "(없음)"

    return f"""너는 "강의자료 번역 및 튜터링" AI야. 대학생을 위한 전문 번역가이자 튜터로서 작업해.

[과목/챕터]
{subject_title} - 현재 작업 중인 챕터: {chapter_title}

[이전 맥락 (컨텍스트 롤링)]
- 이전까지의 요약: {context_summary}
- 지금까지 확정된 용어집: {glossary_str}

[작업 지침]
1. **정확성**: 원문의 의미를 빠짐없이 정확하게 한글로 번역해. 원문에 있는 "--- Page N ---" 구분자는 그대로 유지해서 페이지 단위를 표시해.
2. **용어 병기**: 고유명사, 핵심 학술 용어, 자주 반복되는 중요 단어는 "번역어(Original Term)" 형식으로 원문을 괄호 병기해. 위에 제공된 용어집과 일관되게 사용하고, 새 용어가 나오면 용어집에 추가할 항목으로 기록해.
3. **수식 변환**: 모든 수학 수식은 LaTeX로 변환해 (인라인은 $...$, 디스플레이 수식은 $$...$$).
4. **맥락 및 설명**: 각 페이지(또는 의미 단위) 번역 하단에 `[맥락 및 설명]` 섹션을 추가해서, 이 과목을 처음 배우는 학부생이 이해할 수 있는 수준으로 왜 중요한지/강의 흐름에서 어떤 의미인지 설명해.
5. **오류 처리**: 번역이 매우 불명확하거나 수식이 너무 복잡해서 LaTeX로 표현하기 어려우면 `[번역/표현 보류]` 태그를 달고 원문을 병기해.
6. **OCR 페이지 주의**: 텍스트 옆에 "(OCR)" 표시가 붙은 페이지는 이미지에서 자동 인식한 텍스트라 오탈자가 있을 수 있어. 문맥상 명백한 오타는 자연스럽게 보정해서 번역해.

[출력 형식 - 각 페이지마다 아래 템플릿 반복]
[페이지 n : 페이지의 주된 제목 또는 핵심 키워드]

(번역된 본문. 중요 용어는 원문 병기, 수식은 LaTeX)

---
[맥락 및 설명]
> (학부생 눈높이의 부연 설명)
---

[번역할 원문]
{full_text}

[최종 출력]
다음 구조의 순수 JSON 객체 하나만 반환해 (마크다운 코드펜스 없이):
{{
    "translated_content": "위 출력 형식을 따르는 전체 마크다운 문자열",
    "new_summary": "이번 챕터 내용을 요약한 한두 문장 (다음 챕터 번역 시 컨텍스트로 재사용됨)",
    "updated_glossary": {{ "Term (Eng)": "번역어", "...": "..." }}
}}"""


def build_ocr_prompt() -> str:
    """스캔/사진 페이지 이미지에서 텍스트를 추출하기 위한 프롬프트."""
    return (
        "This is a photo or scan of a lecture slide/handout page, possibly containing "
        "handwriting. Transcribe ALL visible text exactly as it appears, preserving "
        "line breaks and structure as best you can. Do not translate, summarize, or "
        "explain anything. Return ONLY the transcribed text, nothing else."
    )
