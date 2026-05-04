"""
app.py — 가족 자산 관제탑 메인 진입점
역할: 초기화 → 데이터 로드 → UI 렌더링 호출
비즈니스 로직·UI 세부 코드는 각 모듈에 위임합니다.

실행: streamlit run app.py
"""

import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

import config
from data_engine import (
    load_trades, calc_avg_cost, merge_trades_to_portfolio,
    get_now_kst,
    process_portfolio,
    process_history,
    check_and_toast_targets,
    resolve_settings,
)
from mem_cache import (
    init_session_state,
    get_market_status_cached,
    load_sheets_cached,
    get_prices_with_progress,
    clear_data_cache,
)

# ── Rate Limit 방어: 새 캐시 함수 안전 import ────────────────────
# mem_cache.py 가 구버전일 때도 앱이 정상 기동되도록 폴백 처리
try:
    from mem_cache import load_trades_cached
except ImportError:
    load_trades_cached = load_trades  # 구버전 폴백: 캐시 없이 직접 호출
from ui_components import (
    render_dividend_actual_tab,
    render_trades_tab,
    render_market_hud,
    render_summary_tab,
    render_account_tab,
    render_sidebar,
)


# ════════════════════════════════════════════════════════
# 0. 페이지 설정 (반드시 최상단)
# ════════════════════════════════════════════════════════
st.set_page_config(page_title=config.APP_TITLE, layout="wide")
st.markdown(config.APP_CSS, unsafe_allow_html=True)

# session_state 기본값 초기화 (재실행 시 기존 값 유지)
init_session_state()

# ════════════════════════════════════════════════════════
# 1. 시간 및 DB 연결
# ════════════════════════════════════════════════════════
now_kst = get_now_kst()
conn    = st.connection("gsheets", type=GSheetsConnection)
# ※ SheetsWriter 초기화는 버튼 클릭 시점에 지연 생성
#   (앱 시작 시 초기화 시 Sheets API 추가 호출 → Rate Limit 유발)

# ════════════════════════════════════════════════════════
# 2. 데이터 로드 + 정제 (st.status 진행률 표시)
# ════════════════════════════════════════════════════════
with st.status("📡 데이터를 불러오는 중...", expanded=True) as status:

    sell_df   = pd.DataFrame()   # 편매 실적 (초기화)
    trades_df = pd.DataFrame()
    avg_cost_df = pd.DataFrame()

    # STEP 1 — 구글 시트 + 설정 로드
    st.write("📋 구글 시트 연결 중...")
    try:
        full_df, history_df, memo_df = load_sheets_cached(conn)


        # 거래내역 로드 → 평균단가 자동 계산 → 종목현황에 병합
        # [Rate Limit 방어] load_trades → load_trades_cached (TTL=5분)
        trades_df = load_trades_cached(conn)
        avg_cost_df = calc_avg_cost(trades_df)
        sell_df     = avg_cost_df.attrs.get("sell_df", __import__("pandas").DataFrame())
        if not avg_cost_df.empty:
            full_df = merge_trades_to_portfolio(full_df, avg_cost_df)
            st.write(f"📋 거래내역 반영: {len(avg_cost_df)}건 처리 완료")
    except Exception as e:
        st.error(f"⚠️ 구글 시트 연결 오류: {e}")
        st.info("API 할당량 초과일 수 있습니다. 1분 후 새로고침(F5)을 눌러주세요.")
        st.stop()

    # 설정값 병합 (secrets > 시트 snapshot > overrides.toml > 코드 기본값)
    st.write("⚙️ 설정값 로드 중...")
    settings = resolve_settings(conn)

    # STEP 2 — 주가 병렬 수집
    n_stocks = len(full_df["종목명"].unique()) if not full_df.empty else 0
    prog     = st.progress(0, text=f"📈 실시간 주가 수집 중... (0 / {n_stocks})")

    prices = get_prices_with_progress(
        full_df["종목명"].tolist() if not full_df.empty else [],
        progress_widget=prog,
    )
    prog.progress(1.0, text=f"✅ 주가 수집 완료 ({n_stocks}/{n_stocks})")

    # STEP 3 — 지표 계산
    st.write("📊 수익 지표 계산 중...")
    if not full_df.empty:
        full_df = process_portfolio(full_df, prices)

    # STEP 4 — 수익률 추이 정규화
    st.write("📉 수익률 추이 처리 중...")
    if not history_df.empty:
        history_df = process_history(
            history_df,
            kospi_base_date=settings["kospi_base_date"],
        )

    # STEP 5 — 목표가 알림
    st.write("🔔 목표가 도달 여부 확인 중...")
    check_and_toast_targets(full_df)

    status.update(label="✅ 데이터 로드 완료", state="complete", expanded=False)

# ════════════════════════════════════════════════════════
# 3. 헤더
# ════════════════════════════════════════════════════════
st.markdown(
    f"""
    <h2 style='text-align:center; color:#87CEEB; font-size:1.8rem;
               font-weight:600; margin-bottom:25px; letter-spacing:-0.5px;'>
        🌐 AI 금융 통합 관제탑
        <span style='font-size:1.2rem; font-weight:300; opacity:0.7;'>
            {config.APP_VERSION}
        </span>
    </h2>
    """,
    unsafe_allow_html=True,
)

# ════════════════════════════════════════════════════════
# 4. 시장 HUD
# ════════════════════════════════════════════════════════
m_status = get_market_status_cached()
render_market_hud(m_status)

# ════════════════════════════════════════════════════════
# 5. 메인 탭
# ════════════════════════════════════════════════════════
tab_labels = ["📊 총괄 현황"] + [a["label"] for a in config.ACCOUNTS] + ["💸 배당 실적", "📋 편매 실적"]
tabs = st.tabs(tab_labels)

with tabs[0]:
    render_summary_tab(full_df, history_df)

for idx, acc in enumerate(config.ACCOUNTS):
    render_account_tab(
        acc_name   = acc["name"],
        tab_obj    = tabs[idx + 1],
        full_df    = full_df,
        history_df = history_df,
        memo_df    = memo_df,
        conn       = conn,
        now_kst    = now_kst,
    )

# 배당 실적 탭
# [Rate Limit 방어] load_dividend_actual → load_dividend_cached (TTL=5분)
# render_dividend_actual_tab 내부에서 캐시 버전을 사용하도록 ui_components.py 수정됨
with tabs[-2]:
    render_dividend_actual_tab(full_df, conn, now_kst)

# 거래내역 탭
with tabs[-1]:
    render_trades_tab(trades_df, avg_cost_df, full_df, sell_df)

# ════════════════════════════════════════════════════════
# 6. 사이드바
# ════════════════════════════════════════════════════════
render_sidebar(full_df, history_df, now_kst, m_status, conn,
               snapshot=settings["snapshot"])

# ════════════════════════════════════════════════════════
# 7. 푸터
# ════════════════════════════════════════════════════════
st.caption(
    f"{config.APP_VERSION} 가디언 레질리언스 | "
    f"{now_kst.strftime('%Y-%m-%d %H:%M:%S')}"
)
