import streamlit as st
import pdfplumber
import pandas as pd
import google.generativeai as genai
import json  
import re    

# --------------------------------------------------------------------------
# 0. 기본 설정 및 API 키 입력
# --------------------------------------------------------------------------
st.set_page_config(page_title="AI 강의자료 튜터", page_icon="📑")

st.sidebar.title("⚙️ 설정")
api_key = st.sidebar.text_input("Google API Key를 입력하세요", type="password")

# API 키가 입력되었다면 설정 적용
if api_key:
    genai.configure(api_key=api_key)

# --------------------------------------------------------------------------
# 1. 로컬 유틸리티 함수 정의
# --------------------------------------------------------------------------

def count_tokens_gemini(text, model_name="gemini-2.5-flash"):
    """
    Gemini 모델 기준 토큰 수를 계산합니다.
    API 키가 없거나 에러 발생 시 대략적인 글자 수 기반 추산치를 반환합니다.
    """
    # 1. API 키가 없는 경우 (빠른 계산을 위해 단순 추산)
    if not api_key:
        return len(text) // 4
    
    # 2. API 호출을 통한 정확한 계산
    try:
        model = genai.GenerativeModel(model_name)
        response = model.count_tokens(text)
        return response.total_tokens
    except Exception as e:
        # 할당량 초과 등 에러 발생 시 fallback
        return len(text) // 4

def extract_pdf_metadata(file_buffer):
    """
    PDF를 페이지별로 스캔하여 '헤더(상단 텍스트)'와 '토큰 수'를 추출합니다.
    """
    pages_data = []
    
    with pdfplumber.open(file_buffer) as pdf:
        total_pages = len(pdf.pages)
        
        # 진행률 표시줄 (UI)
        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, page in enumerate(pdf.pages):
            # 1. 텍스트 추출
            text = page.extract_text()
            if not text:
                text = ""
            
            # 2. 헤더 추출 전략 (상단 3줄 or 150자)
            lines = text.split('\n')
            header_candidate = " ".join(lines[:3]) if lines else "(내용 없음)"
            if len(header_candidate) > 150:
                header_candidate = header_candidate[:150] + "..."

            # 3. 토큰 수 계산 (Gemini 기준)
            token_count = count_tokens_gemini(text)

            pages_data.append({
                "page_num": i + 1,
                "header_preview": header_candidate,
                "token_count": token_count,
                "full_text_length": len(text)
            })

            # 진행률 업데이트
            progress_bar.progress((i + 1) / total_pages)
            status_text.text(f"페이지 스캔 중... {i + 1}/{total_pages}")
        
        status_text.empty()
        progress_bar.empty()
        
    return pages_data

def clean_json_string(json_str):
    """
    AI가 마크다운(```json ... ```)을 포함해서 줄 경우 순수 JSON만 추출합니다.
    """
    pattern = r"```json\s*(.*?)\s*```"
    match = re.search(pattern, json_str, re.DOTALL)
    if match:
        return match.group(1)
    return json_str

def get_structure_from_ai(pages_data):
    """
    페이지별 헤더 정보를 Gemini에게 보내 챕터 구조를 요청합니다.
    (수정됨: 전송되는 프롬프트 내용을 UI에 출력)
    """
    # 1. 프롬프트 생성 (토큰 절약을 위해 꼭 필요한 정보만 전송)
    simplified_data = [
        f"P{item['page_num']}: {item['header_preview']}" 
        for item in pages_data
    ]
    
    # JSON 덤프 (한글 깨짐 방지 ensure_ascii=False)
    json_input = json.dumps(simplified_data, ensure_ascii=False, indent=2)

    prompt = f"""
    You are a curriculum expert. I will provide a list of page headers from a lecture slide.
    
    [Task]
    Analyze the headers and group consecutive pages into logical 'Chapters'.
    
    [Rules]
    1. Every page from the start to the end must be included in a chapter.
    2. 'context_title' should be a summary of the chapter's topic.
    3. Return ONLY a valid JSON list of objects. Do not add any explanation.
    
    [Input Data]
    {json_input}

    [Output Format Example]
    [
        {{"chapter_num": 1, "title": "Introduction", "start_page": 1, "end_page": 5}},
        {{"chapter_num": 2, "title": "Main Topic A", "start_page": 6, "end_page": 15}}
    ]
    """

    # ------------------------------------------------------------------
    # [DEBUG] 전송 내용 출력 (여기가 추가된 부분입니다)
    # ------------------------------------------------------------------
    with st.expander("🔍 [디버깅] AI에게 전송되는 실제 프롬프트 보기 (클릭)", expanded=True):
        st.info(f"전송되는 글자 수: {len(prompt)} 자")
        st.code(prompt, language="json") # 프롬프트 전체를 코드 블록으로 표시
    # ------------------------------------------------------------------
def extract_text_by_range(file_buffer, start_p, end_p):
    """
    PDF 파일에서 특정 페이지 범위(start_p ~ end_p)의 텍스트를 추출합니다.
    """
    text_content = ""
    with pdfplumber.open(file_buffer) as pdf:
        # 페이지 번호는 1부터 시작하므로 인덱스는 -1 해줘야 함
        for i in range(start_p - 1, end_p):
            if i < len(pdf.pages):
                page_text = pdf.pages[i].extract_text()
                if page_text:
                    text_content += f"\n--- Page {i+1} ---\n{page_text}\n"
    return text_content

def translate_chapter_with_ai(chapter_data, full_text, context_summary, context_glossary):
    """
    [Phase 2 핵심]
    현재 챕터 텍스트 + 이전 요약 + 용어집을 AI에게 보내 번역 및 학습 자료를 생성합니다.
    """
    
    # 이전 용어집을 텍스트로 변환 (AI가 읽기 좋게)
    glossary_str = json.dumps(context_glossary, ensure_ascii=False) if context_glossary else "(없음)"

    prompt = f"""
    You are a professional professor and translator for undergraduate students.
    
    [Current Mission]
    Translate and explain the provided lecture material (Chapter: {chapter_data['title']}).
    
    [Context Info]
    - Previous Story (Summary): {context_summary}
    - Terminology Glossary: {glossary_str}
    
    [Input Text]
    {full_text}
    
    [Requirements]
    1. **Translation**: Translate all text to Korean naturally.
    2. **Terminology**: Use the provided glossary. If new terms appear, define them consistently.
    3. **Math**: Convert all equations to LaTeX format (e.g., $E=mc^2$).
    4. **Tutoring**: Add a `[맥락 및 설명]` section at the end of each logical section to help students understand.
    
    [Output Format]
    You must return a valid JSON object with the following structure:
    {{
        "translated_content": "The full markdown content (Translation + Explanation)...",
        "new_summary": "A concise summary of THIS chapter (to be passed to the next step)",
        "updated_glossary": {{ "Term (Eng)": "Term (Kor)", ... }} 
    }}
    """
    
    # 모델 설정 (안정적인 2.5 사용)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # 토큰 제한 설정 (입력이 많으므로 출력도 넉넉하게)
    config = genai.GenerationConfig(
        max_output_tokens=8000, 
        temperature=0.2
    )

    try:
        response = model.generate_content(prompt, generation_config=config)
        cleaned_json = clean_json_string(response.text)
        return json.loads(cleaned_json)
    except Exception as e:
        st.error(f"번역 중 오류 발생: {e}")
        return None
        
    # 2. API 호출
    # (주의: 모델명은 2.5-flash 또는 1.5-flash 등 현재 작동하는 것으로 설정)
    model = genai.GenerativeModel('gemini-2.5-flash') 
    
    try:
        # generation_config로 토큰 제한을 걸어두는 것도 좋습니다.
        response = model.generate_content(prompt)
        
        # 3. JSON 파싱
        cleaned_text = clean_json_string(response.text)
        structure_json = json.loads(cleaned_text)
        return structure_json
    except Exception as e:
        st.error(f"AI 응답 해석 실패 또는 API 오류: {e}")
        # 오류가 났을 때도 응답 본문을 볼 수 있게
        if 'response' in locals() and hasattr(response, 'text'):
            st.warning("AI가 반환한 원본 텍스트:")
            st.text(response.text)
        return []

# --------------------------------------------------------------------------
# 2. 메인 UI (Streamlit)
# --------------------------------------------------------------------------

st.title("📑 AI 강의자료 튜터 (Local Phase)")
st.subheader("Step 1. 파일 구조 분석")

# API 키 안내 메시지
if not api_key:
    st.warning("⚠️ 왼쪽 사이드바에 Google API Key를 입력하면 정확한 토큰 수 계산이 가능합니다. (미입력 시 추산치 사용)")

uploaded_file = st.file_uploader("강의자료 PDF를 업로드하세요", type="pdf")

if uploaded_file is not None:
    st.success("파일 업로드 완료! 분석을 시작합니다.")
    
    # 1. 로컬 분석 실행
    with st.spinner("텍스트 추출 및 구조 분석 중..."):
        uploaded_file.seek(0)
        pages_summary = extract_pdf_metadata(uploaded_file)
    
    # 2. 결과 리포트 생성
    df = pd.DataFrame(pages_summary)
    total_tokens = df['token_count'].sum()
    
    # 비용 계산 (Gemini 1.5 Flash 기준: 입력 100만 토큰당 약 $0.075)
    # 환율 1400원 가정
    price_per_million = 0.075
    estimated_cost_usd = total_tokens * price_per_million / 1_000_000
    estimated_cost_krw = estimated_cost_usd * 1400

    # 상단 요약 지표
    col1, col2, col3 = st.columns(3)
    col1.metric("총 페이지", f"{len(df)} 쪽")
    col2.metric("총 토큰 (Gemini)", f"{total_tokens:,}")
    
    # API 키 유무에 따라 비용 라벨 다르게 표시
    cost_label = "예상 API 비용 (Flash)"
    if not api_key:
        cost_label += " (추산)"
        
    col3.metric(cost_label, f"${estimated_cost_usd:.5f} (약 {estimated_cost_krw:.1f}원)")

    st.markdown("---")
    
    # 3. 데이터 미리보기
    st.write("### 🤖 AI에게 전송될 페이지별 헤더 데이터")
    st.caption("AI는 이 데이터만 보고 목차를 나눕니다.")
    
    st.dataframe(
        df[['page_num', 'header_preview', 'token_count']],
        use_container_width=True,
        hide_index=True
    )

    # ... (위쪽 코드는 그대로 유지) ...
    
    st.markdown("---")

    # ----------------------------------------------------------------------
    # [Step 2] AI 구조화 요청 및 승인 (Human-in-the-loop)
    # ----------------------------------------------------------------------
    
    st.subheader("Step 2. AI 목차 제안 및 확정")

    # 세션 상태 초기화 (AI가 만든 구조를 저장할 공간)
    if "chapter_structure" not in st.session_state:
        st.session_state.chapter_structure = None

    # 버튼: AI 분석 실행
    if st.button("🤖 이 데이터로 목차 구조화 요청하기"):
        if not api_key:
            st.error("API Key를 먼저 입력해주세요.")
        else:
            with st.spinner("AI가 강의자료의 구조를 분석 중입니다..."):
                # AI 함수 호출
                structure_data = get_structure_from_ai(pages_summary)
                
                if structure_data:
                    st.session_state.chapter_structure = structure_data
                    st.success("구조 분석 완료! 아래 표에서 내용을 확인하고 수정하세요.")
                else:
                    st.error("구조 분석에 실패했습니다. 다시 시도해주세요.")

    # 분석 결과가 있으면 화면에 표시 (Editable Dataframe)
    if st.session_state.chapter_structure is not None:
        st.info("💡 팁: AI가 나눈 범위가 정확하지 않다면, 표를 클릭해서 직접 수정할 수 있습니다.")
        
        # 데이터프레임으로 변환하여 수정 가능하게 표시
        structure_df = pd.DataFrame(st.session_state.chapter_structure)
        
        # Streamlit 데이터 에디터 (사용자가 직접 수정 가능)
        edited_df = st.data_editor(
            structure_df,
            column_config={
                "chapter_num": "챕터 번호",
                "title": "챕터 주제 (Context)",
                "start_page": "시작 페이지",
                "end_page": "종료 페이지"
            },
            use_container_width=True,
            num_rows="dynamic" # 행 추가/삭제 가능
        )

        st.markdown("#### 🔍 검토 체크리스트")
        st.markdown("""
        1. **주제 확인:** 챕터 제목이 해당 내용을 잘 대표하나요?
        2. **범위 확인:** 시작 페이지와 종료 페이지가 끊김 없이 이어지나요?
        """)

# ... (위쪽 Phase 1 코드는 그대로) ...

    # ----------------------------------------------------------------------
    # [Step 3] Phase 2: 실행 루프 (Context Rolling)
    # ----------------------------------------------------------------------
    
    # 세션 상태에 결과 저장소 초기화
    if "final_results" not in st.session_state:
        st.session_state.final_results = [] # 번역된 챕터들이 쌓일 곳
    if "context_summary" not in st.session_state:
        st.session_state.context_summary = "이것은 강의의 시작입니다."
    if "context_glossary" not in st.session_state:
        st.session_state.context_glossary = {}

    st.markdown("---")
    st.subheader("Step 3. 실시간 번역 및 튜터링 (Phase 2)")

    # 구조화가 완료된 상태에서만 Phase 2 버튼 활성화
    if st.session_state.chapter_structure:
        
        # 수정된 데이터프레임이 있다면 그것을 사용 (사용자가 표를 수정했을 수 있으므로)
        # (st.data_editor의 리턴값을 활용해야 하는데, 여기선 간단히 session_state 사용)
        chapters = st.session_state.chapter_structure 
        
        if st.button("🚀 전체 챕터 번역 시작 (Phase 2 Loop)"):
            if not api_key:
                st.error("API Key가 필요합니다.")
            else:
                progress_bar = st.progress(0)
                status_box = st.empty()
                result_area = st.container()

                # --- [루프 시작] ---
                for idx, chapter in enumerate(chapters):
                    import time
                    
                    chapter_title = chapter.get('title', f"Chapter {idx+1}")
                    status_box.markdown(f"### ▶️ 처리 중: {chapter_title} ...")
                    
                    # 1. 텍스트 추출 (Local)
                    uploaded_file.seek(0) # 파일 포인터 초기화
                    chapter_text = extract_text_by_range(
                        uploaded_file, 
                        int(chapter['start_page']), 
                        int(chapter['end_page'])
                    )
                    
                    # 2. AI 번역 요청 (API) with Context
                    # (429 에러 방지를 위해 2초 대기)
                    time.sleep(2) 
                    
                    ai_result = translate_chapter_with_ai(
                        chapter,
                        chapter_text,
                        st.session_state.context_summary,
                        st.session_state.context_glossary
                    )
                    
                    if ai_result:
                        # 3. 결과 저장 및 컨텍스트 업데이트 (Rolling)
                        st.session_state.final_results.append({
                            "chapter": chapter_title,
                            "content": ai_result['translated_content']
                        })
                        
                        # 요약과 용어집을 최신본으로 교체 (바통 터치!)
                        st.session_state.context_summary = ai_result['new_summary']
                        # 용어집은 병합(Merge)하는 것이 좋음
                        st.session_state.context_glossary.update(ai_result.get('updated_glossary', {}))
                        
                        # 4. 화면에 실시간 결과 출력
                        with result_area:
                            with st.expander(f"✅ 완료: {chapter_title}", expanded=False):
                                st.markdown(ai_result['translated_content'])
                                st.markdown("---")
                                st.caption(f"Update Summary: {ai_result['new_summary'][:50]}...")
                                st.json(st.session_state.context_glossary)

                    else:
                        st.error(f"❌ {chapter_title} 처리 실패")
                        break # 오류 나면 멈춤
                    
                    # 진행률 업데이트
                    progress_bar.progress((idx + 1) / len(chapters))
                
                # --- [루프 종료] ---
                status_box.success("🎉 모든 챕터의 번역 및 튜터링이 완료되었습니다!")
                
                # 최종 결과 다운로드 버튼 생성
                full_markdown = f"# {uploaded_file.name} 번역 노트\n\n"
                for item in st.session_state.final_results:
                    full_markdown += f"## {item['chapter']}\n\n{item['content']}\n\n---\n\n"
                
                st.download_button(
                    label="📥 최종 결과물 다운로드 (Markdown)",
                    data=full_markdown,
                    file_name="translated_lecture.md",
                    mime="text/markdown"
                )