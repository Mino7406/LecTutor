# LecTutor

영어로 된 대학 강의자료(PDF)를 업로드하면 **과목/챕터 구조를 자동으로 파악**하고, 챕터 단위로 **한글 번역 + 학부생 눈높이 튜터링 설명**을 생성해주는 Streamlit 앱입니다. [Gemini API](https://ai.google.dev/) 기반이며, 스캔/사진/손글씨로 된 페이지는 자동으로 OCR을 거쳐 번역 파이프라인에 투입됩니다.

## 주요 기능

- **Step 1. 파일 구조 분석** — PDF를 페이지별로 로컬 스캔해서 헤더 미리보기, 토큰 수(추산 또는 API 기준), 스캔/사진 페이지 여부(OCR 필요 여부)를 표로 보여주고, 예상 API 비용을 미리 계산
- **Step 2. 과목/목차 확정 (Human-in-the-loop)** — 페이지 헤더 데이터를 AI에게 보내 과목명과 챕터 구조(JSON)를 추천받고, 표에서 직접 수정/추가/삭제 가능
- **Step 3. 실시간 번역 및 튜터링** — 챕터를 순회하며 원문을 추출 → 번역 + `[맥락 및 설명]` 섹션 생성 → 이전 챕터의 요약/용어집을 다음 챕터 프롬프트에 이어붙이는 **컨텍스트 롤링**으로 문서 전체의 용어/맥락 일관성 유지, 완료 후 마크다운으로 다운로드
- **스캔/사진/손글씨 페이지 자동 OCR** — pdfplumber로 텍스트가 거의 안 나오는 페이지를 감지해 PyMuPDF로 이미지 렌더링 후 Gemini Vision으로 텍스트 추출, 번역 원문에 자동 병합
- **모델 자동 감지** — 모델명을 하드코딩하지 않고, 입력한 API 키로 실제 사용 가능한 모델 목록을 조회해 적합한 모델을 자동 추천 (사이드바에서 수동으로 변경도 가능). Google이 특정 모델을 은퇴시켜도 코드 수정 없이 대응됨
- **용어 병기 / LaTeX 수식 변환 / 오류 태그** — 핵심 용어는 "번역어(Original)" 형식으로 원문 병기, 수식은 LaTeX로 변환, 번역이 애매한 부분은 `[번역/표현 보류]` 태그로 표시

## 기술 스택

- [Streamlit](https://streamlit.io/) — 웹 UI
- [google-genai](https://pypi.org/project/google-genai/) — Gemini API 클라이언트 (구지원 종료된 `google-generativeai` 대체)
- [pdfplumber](https://github.com/jsvine/pdfplumber) — PDF 텍스트 추출
- [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/) — 스캔 페이지를 이미지로 렌더링 (OCR용)
- [pandas](https://pandas.pydata.org/) — 페이지/챕터 표 데이터 처리

## 설치 및 실행

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
streamlit run app.py
```

브라우저(`http://localhost:8501`)가 열리면 왼쪽 사이드바에 [Google API Key](#google-api-key-발급-방법)를 입력합니다. 키를 입력하면 사용 가능한 모델 목록을 자동 조회해 사이드바에 드롭다운으로 보여줍니다.

## 폴더 구조

```
LecTutor/
├─ app.py                  # Streamlit UI: Step1(스캔) → Step2(목차 확정) → Step3(번역 루프)
├─ core/
│  ├─ ai_client.py         # Gemini API 통신 전담 (모델 조회, 토큰 계산, 구조화/번역/OCR 요청)
│  ├─ pdf_utils.py         # PDF 로컬 처리 (텍스트 추출, 스캔 페이지 감지, 이미지 렌더링)
│  └─ prompts.py           # AI에게 보내는 프롬프트 문자열 조립
├─ prompt_v3.0.txt         # 번역 프롬프트 설계 원본 (수작업 프롬프트 엔지니어링 문서)
├─ 0_structure.md          # 손글씨로 설계했던 전체 파이프라인 순서도 텍스트화
├─ 0_PIP.txt               # 초기 의존성 메모
└─ requirements.txt
```

## 기능 상세

### Step 1. 파일 구조 분석 (`app.py`, `core/pdf_utils.py`)

1. PDF 업로드 시 `pdf_utils.scan_pdf()`가 페이지를 순회하며 `pdfplumber`로 텍스트를 추출
2. 추출된 텍스트가 15자 미만이면 스캔/사진/손글씨 페이지로 간주(`needs_ocr=True`)하고, 헤더 미리보기 대신 안내 문구를 표시 — 이 단계에서는 비용 절감을 위해 OCR을 실제로 호출하지 않고 **플래그만** 남김
3. 텍스트 페이지는 상단 3줄(또는 150자)을 헤더 미리보기로 추출하고, `ai_client.count_tokens()`로 토큰 수 계산(API 키 없으면 글자수 // 4로 추산)
4. 총 페이지/총 토큰/예상 비용(Gemini Flash 입력 단가 기준 추산치)을 지표로 표시

### Step 2. 과목/목차 확정 (`app.py`, `core/ai_client.py::get_chapter_structure`)

1. "구조화 요청하기" 버튼 클릭 시, 페이지별 헤더 목록을 `prompts.build_structure_prompt()`로 프롬프트화해서 전송
2. 응답은 `response_schema`로 스키마를 강제해 `{"subject_title": ..., "chapters": [...]}` 형태의 유효한 JSON만 받도록 함
3. 결과를 `st.data_editor`로 표시해 사용자가 챕터 제목/시작·종료 페이지를 직접 수정, 행 추가/삭제도 가능 (AI가 잘못 나눈 경우 보정하는 용도)

### Step 3. 실시간 번역 및 튜터링 (`app.py`, `core/ai_client.py::translate_chapter`)

1. 확정된 챕터를 순서대로 순회하며 `pdf_utils.extract_text_by_range()`로 해당 페이지 범위의 원문을 추출
   - 이 시점에 스캔 페이지(Step 1에서 플래그된)를 만나면 `pdf_utils.render_page_as_image()`로 페이지를 이미지로 렌더링하고, `ai_client.ocr_image()`(Gemini Vision)로 텍스트를 추출해 `--- Page N (OCR) ---` 마커와 함께 원문에 병합
2. `prompts.build_translation_prompt()`가 과목/챕터명, 이전 챕터 요약, 지금까지의 용어집을 함께 넣어 프롬프트를 구성 — 이 **컨텍스트 롤링** 덕분에 챕터가 바뀌어도 같은 용어는 같은 번역어로, 이전 내용과 이어지는 설명이 나옴
3. 번역 결과는 `{translated_content, new_summary, updated_glossary}` 스키마로 강제 — `updated_glossary`는 Gemini Developer API가 임의 키 dict 스키마(`additionalProperties`)를 지원하지 않아 `[{term, translation}]` 배열로 받은 뒤 내부에서 dict로 변환
4. 챕터별 결과를 세션에 누적하고, 전체 완료 시 하나의 마크다운 파일로 합쳐 다운로드 버튼 제공

## 주요 함수

### `core/ai_client.py` — Gemini API 통신

| 함수 | 설명 |
|---|---|
| `configure(api_key)` | API 키로 `genai.Client` 초기화 |
| `list_available_models()` | 현재 키로 `generateContent`가 가능한 모델 이름 목록 조회 |
| `pick_default_model(model_names)` | 목록 중 "flash" 계열, 최신 버전, 경량/특수 목적 모델 제외 등의 기준으로 기본값 추천 |
| `count_tokens(text, api_key, model)` | 토큰 수 계산, 키/모델 없거나 실패 시 글자수 // 4로 추산 |
| `_generate_json(model, prompt, schema, max_output_tokens)` *(내부)* | `response_schema`로 JSON 출력을 강제하고, `thinking_budget=0`으로 먼저 시도(생각 토큰이 출력 예산을 다 먹어 빈 응답이 나오는 문제 방지) 후 실패 시 기본값으로 재시도 |
| `_get_output_token_limit(model)` *(내부)* | 모델의 실제 최대 출력 토큰 한도를 조회해 캐싱, `max_output_tokens`를 이 한도 내로 자동 클램프 |
| `get_chapter_structure(pages_data, model)` | 페이지 헤더 → 과목명 + 챕터 구조 JSON 요청 |
| `translate_chapter(subject_title, chapter_title, full_text, context_summary, context_glossary, model)` | 챕터 원문 → 번역+튜터링 JSON 요청, 용어집을 배열→dict로 변환해 반환 |
| `ocr_image(image, model)` | 스캔 페이지 이미지(PIL.Image) → 텍스트 추출 (Gemini Vision) |

### `core/pdf_utils.py` — PDF 로컬 처리

| 함수 | 설명 |
|---|---|
| `extract_page_text(page)` | `pdfplumber` 페이지 객체에서 텍스트 추출 |
| `needs_ocr(text)` | 추출된 텍스트가 15자 미만이면 스캔/사진 페이지로 판단 |
| `render_page_as_image(file_buffer, page_index, dpi)` | PyMuPDF로 특정 페이지를 이미지로 렌더링 |
| `scan_pdf(file_buffer, count_tokens_fn, progress_callback)` | 전체 페이지를 스캔해 헤더/토큰수/OCR 필요 여부 목록 생성 |
| `extract_text_by_range(file_buffer, start_p, end_p, ocr_fn)` | 페이지 범위의 텍스트 추출, OCR 필요 페이지는 `ocr_fn` 콜백으로 대체 |

### `core/prompts.py` — 프롬프트 조립

| 함수 | 설명 |
|---|---|
| `build_structure_prompt(pages_data)` | 과목명 추론 + 챕터 구조화 프롬프트 생성 |
| `build_translation_prompt(subject_title, chapter_title, full_text, context_summary, context_glossary)` | 용어 병기/LaTeX/맥락 설명/오류 태그 규칙이 반영된 번역 프롬프트 생성 |
| `build_ocr_prompt()` | 스캔 페이지 이미지 전사(transcribe)용 프롬프트 생성 |

## Google API Key 발급 방법

1. [Google AI Studio](https://aistudio.google.com/apikey) 접속 (구글 계정 로그인)
2. **"Create API key"** → 기존 Cloud 프로젝트 선택 또는 새로 생성
3. 발급된 키(`AIza...`)를 복사해 앱 사이드바에 입력

기본적으로 **무료 등급**으로 동작하며, 별도로 결제 계정을 연결하지 않는 한 과금되지 않습니다. 무료 등급은 분당/일당 요청 횟수 제한이 있어 초과 시 요청이 실패(429)할 뿐 비용이 청구되지 않습니다.

## 주의사항

- 비용/토큰 추산치는 대략적인 값이며 실제 청구 금액과 다를 수 있습니다.
- OCR은 Gemini Vision 기반이라 손글씨 인식 품질이 필체에 따라 달라질 수 있습니다.
- Google이 모델을 은퇴시키는 경우가 있어(예: `gemini-2.5-flash`가 신규 사용자에게 막힌 사례) 모델을 하드코딩하지 않고 동적으로 조회하지만, API 응답 스키마나 파라미터 자체가 바뀌는 경우는 별도 대응이 필요합니다.
- API 키는 코드/저장소에 커밋하지 말고 매번 직접 입력하세요.
