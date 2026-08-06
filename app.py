import time

import pandas as pd
import streamlit as st

from core import ai_client, pdf_utils, prompts

# --------------------------------------------------------------------------
# 0. 기본 설정 및 API 키 입력
# --------------------------------------------------------------------------
st.set_page_config(page_title="AI 강의자료 튜터", page_icon="📑")

st.sidebar.title("⚙️ 설정")
api_key = st.sidebar.text_input("Google API Key를 입력하세요", type="password")

if api_key:
    if st.session_state.get("_configured_key") != api_key:
        ai_client.configure(api_key)
        st.session_state._configured_key = api_key
        st.session_state.available_models = ai_client.list_available_models()
        st.session_state.selected_model = ai_client.pick_default_model(
            st.session_state.available_models
        )

    if st.session_state.get("available_models"):
        models = st.session_state.available_models
        current = st.session_state.get("selected_model")
        index = models.index(current) if current in models else 0
        st.session_state.selected_model = st.sidebar.selectbox(
            "사용할 모델", models, index=index
        )
    else:
        st.sidebar.error(
            "이 키로 쓸 수 있는 모델 목록을 가져오지 못했어요. 키가 올바른지, "
            "또는 프로젝트에 Generative Language API가 활성화되어 있는지 확인해주세요."
        )

# --------------------------------------------------------------------------
# 1. 메인 UI
# --------------------------------------------------------------------------
st.title("📑 AI 강의자료 튜터")
st.subheader("Step 1. 파일 구조 분석")

if not api_key:
    st.warning(
        "⚠️ 왼쪽 사이드바에 Google API Key를 입력하면 정확한 토큰 수 계산과 "
        "번역이 가능합니다. (미입력 시 토큰 수는 추산치만 표시되고, 목차 구조화 "
        "및 번역은 진행할 수 없어요)"
    )

uploaded_file = st.file_uploader("강의자료 PDF를 업로드하세요", type="pdf")

if uploaded_file is not None:
    st.success("파일 업로드 완료! 분석을 시작합니다.")

    with st.spinner("텍스트 추출 및 구조 분석 중..."):
        progress_bar = st.progress(0)
        status_text = st.empty()

        def _report_progress(done, total):
            progress_bar.progress(done / total)
            status_text.text(f"페이지 스캔 중... {done}/{total}")

        pages_summary = pdf_utils.scan_pdf(
            uploaded_file,
            count_tokens_fn=lambda t: ai_client.count_tokens(
                t, api_key, st.session_state.get("selected_model")
            ),
            progress_callback=_report_progress,
        )
        status_text.empty()
        progress_bar.empty()

    df = pd.DataFrame(pages_summary)
    total_tokens = int(df["token_count"].sum())
    ocr_page_count = int(df["needs_ocr"].sum())

    # 비용 계산 (Gemini 2.5 Flash 입력 기준 대략적인 추산치, 실제 청구 금액과 다를 수 있음)
    price_per_million = 0.075
    estimated_cost_usd = total_tokens * price_per_million / 1_000_000
    estimated_cost_krw = estimated_cost_usd * 1400

    col1, col2, col3 = st.columns(3)
    col1.metric("총 페이지", f"{len(df)} 쪽")
    col2.metric("총 토큰 (텍스트 페이지 기준)", f"{total_tokens:,}")
    cost_label = "예상 API 비용 (Flash)"
    if not api_key:
        cost_label += " (추산)"
    col3.metric(cost_label, f"${estimated_cost_usd:.5f} (약 {estimated_cost_krw:.1f}원)")

    if ocr_page_count:
        st.info(
            f"📷 {ocr_page_count}개 페이지가 스캔/사진(또는 손글씨)으로 추정됩니다. "
            "번역 단계(Step 3)에서 자동으로 OCR이 적용되며, 위 토큰/비용 추산에는 "
            "포함되어 있지 않습니다."
        )

    st.markdown("---")
    st.write("### 🤖 AI에게 전송될 페이지별 헤더 데이터")
    st.caption("AI는 이 데이터만 보고 과목명과 목차를 나눕니다.")
    st.dataframe(
        df[["page_num", "header_preview", "token_count", "needs_ocr"]],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")

    # ------------------------------------------------------------------
    # Step 2. AI 구조화 요청 및 승인 (Human-in-the-loop)
    # ------------------------------------------------------------------
    st.subheader("Step 2. 과목/목차 확정")

    if "chapter_structure" not in st.session_state:
        st.session_state.chapter_structure = None
    if "subject_title" not in st.session_state:
        st.session_state.subject_title = None

    if st.button("🤖 이 데이터로 과목/목차 구조화 요청하기"):
        if not api_key or not st.session_state.get("selected_model"):
            st.error("API Key와 사용 가능한 모델이 먼저 필요해요 (왼쪽 사이드바 확인).")
        else:
            with st.expander("🔍 [디버깅] AI에게 전송되는 프롬프트 보기", expanded=False):
                st.code(prompts.build_structure_prompt(pages_summary), language="json")

            with st.spinner("AI가 강의자료의 구조를 분석 중입니다..."):
                result = ai_client.get_chapter_structure(
                    pages_summary, st.session_state.selected_model
                )

            if result and "chapters" in result:
                st.session_state.chapter_structure = result["chapters"]
                st.session_state.subject_title = result.get("subject_title", uploaded_file.name)
                st.success("구조 분석 완료! 아래 표에서 내용을 확인하고 수정하세요.")
            else:
                st.error("구조 분석에 실패했습니다. 다시 시도해주세요.")
                if result and result.get("error"):
                    st.caption(f"오류 내용: {result['error']}")

    if st.session_state.chapter_structure is not None:
        st.info(f"💡 확정된 과목/챕터: **{st.session_state.subject_title}**")
        st.caption("AI가 나눈 범위가 정확하지 않다면, 표를 클릭해서 직접 수정할 수 있습니다.")

        structure_df = pd.DataFrame(st.session_state.chapter_structure)
        edited_df = st.data_editor(
            structure_df,
            column_config={
                "chapter_num": "챕터 번호",
                "title": "챕터 주제 (Context)",
                "start_page": "시작 페이지",
                "end_page": "종료 페이지",
            },
            use_container_width=True,
            num_rows="dynamic",
        )
        st.session_state.chapter_structure = edited_df.to_dict("records")

        st.markdown("#### 🔍 검토 체크리스트")
        st.markdown(
            "1. **주제 확인:** 챕터 제목이 해당 내용을 잘 대표하나요?\n"
            "2. **범위 확인:** 시작 페이지와 종료 페이지가 끊김 없이 이어지나요?"
        )

    st.markdown("---")

    # ------------------------------------------------------------------
    # Step 3. 실시간 번역 및 튜터링 (컨텍스트 롤링 루프)
    # ------------------------------------------------------------------
    st.subheader("Step 3. 실시간 번역 및 튜터링")

    if "final_results" not in st.session_state:
        st.session_state.final_results = []
    if "context_summary" not in st.session_state:
        st.session_state.context_summary = "이것은 강의의 시작입니다."
    if "context_glossary" not in st.session_state:
        st.session_state.context_glossary = {}

    if st.session_state.chapter_structure:
        chapters = st.session_state.chapter_structure

        if st.button("🚀 전체 챕터 번역 시작"):
            if not api_key or not st.session_state.get("selected_model"):
                st.error("API Key와 사용 가능한 모델이 먼저 필요해요 (왼쪽 사이드바 확인).")
            else:
                # 재실행 시 이전 결과를 덮어쓰지 않도록 초기화
                st.session_state.final_results = []
                st.session_state.context_summary = "이것은 강의의 시작입니다."
                st.session_state.context_glossary = {}

                progress_bar = st.progress(0)
                status_box = st.empty()
                result_area = st.container()

                for idx, chapter in enumerate(chapters):
                    chapter_title = chapter.get("title", f"Chapter {idx + 1}")
                    status_box.markdown(f"### ▶️ 처리 중: {chapter_title} ...")

                    chapter_text = pdf_utils.extract_text_by_range(
                        uploaded_file,
                        int(chapter["start_page"]),
                        int(chapter["end_page"]),
                        ocr_fn=lambda img: ai_client.ocr_image(img, st.session_state.selected_model),
                    )

                    time.sleep(2)  # 429(요청 과다) 에러 방지용 대기

                    ai_result = ai_client.translate_chapter(
                        st.session_state.subject_title,
                        chapter_title,
                        chapter_text,
                        st.session_state.context_summary,
                        st.session_state.context_glossary,
                        st.session_state.selected_model,
                    )

                    if ai_result and "translated_content" in ai_result:
                        st.session_state.final_results.append({
                            "chapter": chapter_title,
                            "content": ai_result["translated_content"],
                        })
                        st.session_state.context_summary = ai_result["new_summary"]
                        st.session_state.context_glossary.update(ai_result.get("updated_glossary", {}))

                        with result_area:
                            with st.expander(f"✅ 완료: {chapter_title}", expanded=False):
                                st.markdown(ai_result["translated_content"])
                                st.markdown("---")
                                st.caption(f"Update Summary: {ai_result['new_summary'][:50]}...")
                                st.json(st.session_state.context_glossary)
                    else:
                        error_msg = ai_result.get("error") if ai_result else "알 수 없는 오류"
                        st.error(f"❌ {chapter_title} 처리 실패: {error_msg}")
                        break

                    progress_bar.progress((idx + 1) / len(chapters))
                else:
                    status_box.success("🎉 모든 챕터의 번역 및 튜터링이 완료되었습니다!")

                    full_markdown = f"# {st.session_state.subject_title}\n\n"
                    for item in st.session_state.final_results:
                        full_markdown += f"## {item['chapter']}\n\n{item['content']}\n\n---\n\n"

                    st.download_button(
                        label="📥 최종 결과물 다운로드 (Markdown)",
                        data=full_markdown,
                        file_name="translated_lecture.md",
                        mime="text/markdown",
                    )
    else:
        st.caption("Step 2에서 목차를 먼저 확정해주세요.")
