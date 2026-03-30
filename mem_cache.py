"""
mem_cache.py — 가족 자산 관제탑 인메모리 캐시 레이어
======================================================

Streamlit 의 두 캐시 메커니즘을 역할에 맞게 분리합니다.

┌─────────────────────────────────────────────────────────────┐
│  st.cache_data    — 주가·시장지표 DataFrame 캐시 (TTL 기반)  │
│  session_state    — UI 상태·선택값·플래그 (탭 수명)          │
│  st.cache_resource— conn 등 연결 객체 (앱 수명)              │
└─────────────────────────────────────────────────────────────┘

Rate Limit 방어 원칙
─────────────────────────────────────────────────────────────
• Google Sheets API 호출은 load_sheets() 1회로 제한
• 주가 수집은 cache_data TTL 안에서 재실행 차단
• session_state 는 API 호출 없이 순수 메모리만 사용

사용법 요약
─────────────────────────────────────────────────────────────
app.py 상단에 한 줄:
    from mem_cache import get_market_status_cached, get_prices_cached, init_session_state

data_engine.get_market_status() 대신:
    m_status = get_market_status_cached()

data_engine.get_stock_data_parallel() 대신:
    prices = get_prices_cached(names)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# ════════════════════════════════════════════════════════
# TTL 설정 (초 단위)
# ════════════════════════════════════════════════════════

TTL_MARKET   = 300    # 시장 지표: 5분 (장중 충분히 빠름)
TTL_PRICES   = 240    # 종목 주가: 4분
TTL_SHEETS   = 60     # Google Sheets 읽기: 1분 (기존 ttl="1m" 유지)
TTL_NEWS     = 600    # 뉴스: 10분 (자주 변하지 않음)


# ════════════════════════════════════════════════════════
# 1. st.cache_data — 시장 지표
# ════════════════════════════════════════════════════════

@st.cache_data(ttl=TTL_MARKET, show_spinner=False)
def get_market_status_cached() -> dict:
    """
    시장 지표 (KOSPI·KOSDAQ·환율·US10Y) 인메모리 캐시.
    TTL=5분 — 같은 5분 안에 몇 번을 호출해도 API는 1회만 실행.

    app.py 교체:
        # 기존
        m_status = get_market_status()
        # 변경
        from mem_cache import get_market_status_cached
        m_status = get_market_status_cached()
    """
    from data_engine import get_market_status
    logger.info("시장 지표 실제 수집 (캐시 미스)")
    return get_market_status()


@st.cache_data(ttl=TTL_PRICES, show_spinner=False)
def get_prices_cached(
    names: tuple[str, ...],          # list 는 해시 불가 → tuple 로 변환해서 전달
) -> list[tuple[int, int]]:
    """
    종목 주가 병렬 수집 캐시. TTL=4분.

    app.py 교체:
        # 기존
        prices = get_stock_data_parallel(full_df["종목명"].tolist(), on_progress=_on_progress)
        # 변경
        from mem_cache import get_prices_cached
        prices = get_prices_cached(tuple(full_df["종목명"].tolist()))
        # ※ on_progress 콜백은 캐시 히트 시 호출 안 됨 — 프로그레스바는 아래 참고
    """
    from data_engine import get_stock_data_parallel
    logger.info(f"주가 실제 수집 (캐시 미스): {len(names)}종목")
    return get_stock_data_parallel(list(names))


@st.cache_data(ttl=TTL_NEWS, show_spinner=False)
def get_news_cached(stock_name: str) -> list[dict]:
    """
    종목 뉴스 캐시. TTL=10분.
    종목 탭을 여러 번 전환해도 동일 종목은 10분 안에 1회만 크롤링.
    """
    from data_engine import get_stock_news
    return get_stock_news(stock_name)


# ════════════════════════════════════════════════════════
# 2. st.cache_data — Google Sheets 데이터
# ════════════════════════════════════════════════════════

@st.cache_data(ttl=TTL_SHEETS, show_spinner=False)
def load_sheets_cached(_conn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Google Sheets 워크시트 로드 캐시. TTL=1분.
    _conn 앞의 언더스코어: Streamlit 이 이 인자를 해시하지 않도록 처리.
    (연결 객체는 해시 불가 → 언더스코어 prefix 로 무시)

    app.py 교체:
        # 기존
        full_df, history_df, memo_df = load_sheets(conn)
        # 변경
        from mem_cache import load_sheets_cached
        full_df, history_df, memo_df = load_sheets_cached(conn)
    """
    from data_engine import load_sheets
    logger.info("Google Sheets 실제 읽기 (캐시 미스)")
    return load_sheets(_conn)


# ════════════════════════════════════════════════════════
# 3. session_state 초기화 — 앱 시작 시 1회
# ════════════════════════════════════════════════════════

# session_state 키 목록 (타입·기본값 명시)
_SESSION_DEFAULTS: dict = {
    # ── UI 상태 ──────────────────────────────────────
    "toasted_targets":  set(),       # 이미 알림 보낸 종목 집합
    "editor_active":    False,       # 스냅샷 편집 모드 여부
    "edit_kospi":       0.0,         # 편집 중 KOSPI 값
    "edit_prices":      {},          # 편집 중 종목가 {이름: 가격}
    "sheets_last_save": None,        # 마지막 Sheets 저장 시각 문자열

    # ── 캐시 메타 ────────────────────────────────────
    "prices_fetched_at":  None,      # 주가 마지막 수집 시각 (datetime)
    "market_fetched_at":  None,      # 시장 지표 마지막 수집 시각

    # ── 페이지 선택 상태 ─────────────────────────────
    # 계좌별 셀렉터는 키 패턴 "sel_{acc_name}_unified" 로 자동 생성됨
    # 메모 상태는 키 패턴 "memo_text_{acc}_{stock}" 으로 자동 생성됨
}


def init_session_state() -> None:
    """
    앱 시작 시 session_state 기본값을 한 번에 초기화.
    이미 존재하는 키는 건드리지 않음 (재실행 안전).

    app.py 최상단 (set_page_config 바로 다음)에 추가:
        from mem_cache import init_session_state
        init_session_state()
    """
    for key, default in _SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


# ════════════════════════════════════════════════════════
# 4. session_state 헬퍼 — 타입 안전 get/set
# ════════════════════════════════════════════════════════

def ss_get(key: str, default=None):
    """session_state 에서 값 읽기. 키 없으면 default 반환."""
    return st.session_state.get(key, default)


def ss_set(key: str, value) -> None:
    """session_state 에 값 저장."""
    st.session_state[key] = value


def ss_delete(key: str) -> None:
    """session_state 에서 키 삭제 (없어도 오류 없음)."""
    st.session_state.pop(key, None)


def ss_set_fetch_time(data_type: str) -> None:
    """주가/시장지표 수집 시각을 session_state 에 기록."""
    ss_set(f"{data_type}_fetched_at", datetime.now(KST))


def ss_get_fetch_age(data_type: str) -> Optional[int]:
    """마지막 수집 후 경과 시간(초) 반환. 미수집 시 None."""
    fetched_at = ss_get(f"{data_type}_fetched_at")
    if fetched_at is None:
        return None
    return int((datetime.now(KST) - fetched_at).total_seconds())


# ════════════════════════════════════════════════════════
# 5. 캐시 무효화 — 갱신 버튼 전용
# ════════════════════════════════════════════════════════

def clear_data_cache() -> None:
    """
    '실시간 데이터 전체 갱신' 버튼 클릭 시 호출.
    cache_data 전체 + 수집 시각 초기화.

    ui_components.py render_sidebar 의 갱신 버튼:
        if st.button("🔄 실시간 데이터 전체 갱신"):
            from mem_cache import clear_data_cache
            clear_data_cache()
            st.rerun()
    """
    st.cache_data.clear()
    ss_delete("toasted_targets")
    ss_set("prices_fetched_at",  None)
    ss_set("market_fetched_at",  None)
    logger.info("캐시 전체 초기화")


def clear_market_cache() -> None:
    """시장 지표만 선택 초기화 (주가는 유지)."""
    get_market_status_cached.clear()
    ss_set("market_fetched_at", None)


def clear_prices_cache() -> None:
    """주가만 선택 초기화 (시장 지표는 유지)."""
    get_prices_cached.clear()
    ss_set("prices_fetched_at", None)


# ════════════════════════════════════════════════════════
# 6. 프로그레스바 포함 주가 수집 래퍼
# ════════════════════════════════════════════════════════

def get_prices_with_progress(
    names: list[str],
    progress_widget,          # st.progress() 반환 객체
) -> list[tuple[int, int]]:
    """
    cache_data 캐시를 활용하되 캐시 미스 시 프로그레스바 표시.

    캐시 히트면 즉시 반환 (프로그레스바 스킵).
    캐시 미스면 실제 수집하면서 progress_widget 업데이트.

    app.py 에서:
        prog = st.progress(0, text="주가 수집 중...")
        prices = get_prices_with_progress(names, prog)
        prog.progress(1.0, text="완료")
    """
    name_tuple = tuple(names)

    # ── 캐시 히트 여부 사전 확인 ──
    # cache_data 내부에 직접 접근할 수 없으므로
    # session_state 의 수집 시각으로 간접 판단
    age = ss_get_fetch_age("prices")
    if age is not None and age < TTL_PRICES:
        # 캐시 히트 — 프로그레스바 즉시 완료 표시
        progress_widget.progress(1.0, text=f"✅ 캐시 사용 중 (갱신까지 {TTL_PRICES - age}초)")
        return get_prices_cached(name_tuple)

    # ── 캐시 미스 — 실제 수집 (프로그레스바 포함) ──
    from data_engine import get_stock_data_parallel

    results_ordered: list[tuple[int, int]] = [(0, 0)] * len(names)
    name_to_idx = {n: i for i, n in enumerate(names)}
    collected = {}
    total = len(names)
    done  = 0

    def _on_progress(d, t, name):
        nonlocal done
        done = d
        short = name[:10] + ".." if len(name) > 10 else name
        pct = d / t if t > 0 else 1.0
        progress_widget.progress(pct, text=f"📈 주가 수집 중... ({d}/{t}) · {short} ✓")

    raw = get_stock_data_parallel(names, on_progress=_on_progress)

    # cache_data 에도 저장 (다음 호출부터 캐시 히트)
    # → get_prices_cached 를 같은 tuple 인자로 호출해 캐시 채움
    # (단, cache_data 는 함수 반환값을 자동 캐싱하므로 직접 저장 불가
    #  → 대신 session_state 에 수집 시각 기록으로 간접 제어)
    ss_set_fetch_time("prices")

    return raw


# ════════════════════════════════════════════════════════
# 7. 캐시 현황 — 사이드바 디버그 위젯
# ════════════════════════════════════════════════════════

def render_cache_debug(expanded: bool = False) -> None:
    """
    사이드바에 캐시 상태를 표시하는 디버그 위젯.
    render_sidebar() 내부에서 선택적으로 호출.

    사용 예:
        from mem_cache import render_cache_debug
        render_cache_debug()
    """
    with st.expander("🧠 인메모리 캐시 현황", expanded=expanded):
        now = datetime.now(KST)

        def _age_str(key: str) -> str:
            age = ss_get_fetch_age(key)
            if age is None:
                return "미수집"
            remaining = {"market": TTL_MARKET, "prices": TTL_PRICES}.get(key, 0) - age
            if remaining > 0:
                return f"유효 ({remaining}초 남음)"
            return "만료됨"

        c1, c2 = st.columns(2)
        c1.metric("시장 지표", _age_str("market"))
        c2.metric("종목 주가", _age_str("prices"))

        last_save = ss_get("sheets_last_save")
        if last_save:
            st.caption(f"마지막 Sheets 저장: {last_save}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("시장만 갱신", key="btn_clear_market", use_container_width=True):
                clear_market_cache()
                st.rerun()
        with col2:
            if st.button("주가만 갱신", key="btn_clear_prices", use_container_width=True):
                clear_prices_cache()
                st.rerun()
