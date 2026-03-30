"""
sheets_pipeline.py — 가족 자산 관제탑 Google Sheets 자동 저장 파이프라인
==========================================================================

저장 대상 시트 5개
──────────────────────────────────────────────────────────────────────────
│ 시트명          │ 저장 주기     │ 내용
│ snapshot        │ 장 마감 1회   │ 종목별 현재가 + 시장 지표 날짜별 누적
│ trend           │ 장 마감 1회   │ 계좌별 수익률 시계열 (성장 추이 차트용)
│ ohlcv_log       │ 장 마감 1회   │ 종목별 일봉 OHLCV 전체 이력
│ market_log      │ 장중 30분마다 │ KOSPI·KOSDAQ·환율·US10Y 시계열
│ collection_log  │ 수집 시마다   │ 수집 성공/실패 운영 로그
──────────────────────────────────────────────────────────────────────────

설계 원칙
──────────────────────────────────────────────────────────────────────────
• 멱등성(Idempotent): 같은 날 여러 번 실행해도 중복 행 없음
  → 날짜(또는 날짜+종목코드) 기준 upsert 방식
• 기존 시트 호환: snapshot / trend 는 기존 data_engine.py 포맷 유지
• 실패 격리: 시트별 독립 try/except → 한 시트 실패가 전체 중단 안 함
• 인증 방법 2가지 지원:
    A) Streamlit Cloud — st.connection("gsheets") 사용 (기존 방식 유지)
    B) 로컬/서버 독립 실행 — gspread + 서비스 계정 JSON 사용

외부 의존성
──────────────────────────────────────────────────────────────────────────
  pip install gspread>=6.0.0 google-auth>=2.28.0   ← 독립 실행 시만 필요
  (Streamlit Cloud 에서는 st-gsheets-connection 으로 충분)

수정 이력
──────────────────────────────────────────────────────────────────────────
[BUG-1] SheetsWriter.from_service_account() 미구현 → 추가
        _GspreadConnCompat 호환 래퍼 클래스 추가 (gspread ↔ conn 인터페이스)
[BUG-2] save_market_log / save_collection_log cutoff 타임존 오류 수정
        tz_localize(None) 이중 적용 제거 → notna() + 단순 비교로 변경
[BUG-3] save_trend ImportError fallback 블록 TypeError 수정
        문자열 리스트를 dict 리스트로 올바르게 생성
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


# ════════════════════════════════════════════════════════
# 시트명 상수
# ════════════════════════════════════════════════════════

WS_SNAPSHOT       = "snapshot"        # 기존 시트 — 포맷 유지
WS_TREND          = "trend"           # 기존 시트 — 포맷 유지
WS_OHLCV_LOG      = "ohlcv_log"       # 신규
WS_MARKET_LOG     = "market_log"      # 신규
WS_COLLECTION_LOG = "collection_log"  # 신규


# ════════════════════════════════════════════════════════
# [BUG-1 수정] gspread 호환 래퍼 — conn 인터페이스 모방
# ════════════════════════════════════════════════════════

class _GspreadConnCompat:
    """
    gspread Spreadsheet 객체를 st-gsheets-connection 과 동일한
    read()/update() 인터페이스로 래핑합니다.
    SheetsWriter 가 Streamlit / 독립 실행 양쪽에서 동일 코드로 동작하게 합니다.
    """

    def __init__(self, spreadsheet):
        self._ss = spreadsheet

    def read(self, worksheet: str, ttl: int = 0) -> pd.DataFrame:
        try:
            ws = self._ss.worksheet(worksheet)
            data = ws.get_all_records()
            return pd.DataFrame(data) if data else pd.DataFrame()
        except Exception as e:
            logger.warning(f"gspread read '{worksheet}' 실패: {e}")
            return pd.DataFrame()

    def update(self, worksheet: str, data: pd.DataFrame) -> None:
        ws = self._ss.worksheet(worksheet)
        # 헤더 + 데이터 행으로 변환
        values = [data.columns.tolist()] + data.astype(str).values.tolist()
        ws.clear()
        ws.update(values)


# ════════════════════════════════════════════════════════
# 1. 연결 헬퍼 — Streamlit / gspread 이중 지원
# ════════════════════════════════════════════════════════

class SheetsWriter:
    """
    Google Sheets 쓰기 전용 클라이언트.

    Streamlit Cloud:
        writer = SheetsWriter.from_streamlit(conn)

    로컬 / 독립 실행:
        writer = SheetsWriter.from_service_account(spreadsheet_id, credential_path)
    """

    def __init__(self, conn):
        self._conn = conn   # st-gsheets-connection 또는 _GspreadConnCompat

    # ── 팩토리 메서드 ────────────────────────────────────

    @classmethod
    def from_streamlit(cls, conn) -> "SheetsWriter":
        """
        st-gsheets-connection conn 객체로 SheetsWriter 생성.
        conn.read() / conn.update() 를 직접 사용하므로
        gspread 클라이언트 추출이 필요 없습니다.
        """
        return cls(conn)

    @classmethod
    def from_service_account(
        cls,
        spreadsheet_id: str,
        credential_path: str,
    ) -> "SheetsWriter":
        """
        [BUG-1 수정] 서비스 계정 JSON 으로 SheetsWriter 생성.
        로컬 실행 / GitHub Actions 스케줄러 등 Streamlit 외부에서 사용합니다.

        필수 패키지:
            pip install gspread>=6.0.0 google-auth>=2.28.0
        """
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as e:
            raise ImportError(
                "gspread 또는 google-auth 가 설치되어 있지 않습니다.\n"
                "pip install gspread>=6.0.0 google-auth>=2.28.0"
            ) from e

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(
            str(credential_path), scopes=scopes
        )
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(spreadsheet_id)
        return cls(_GspreadConnCompat(spreadsheet))

    # ── 내부 헬퍼 ──────────────────────────────────────

    def _read_worksheet_df(self, title: str) -> pd.DataFrame:
        """워크시트 전체를 DataFrame으로 읽기"""
        try:
            df = self._conn.read(worksheet=title, ttl=0)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.warning(f"'{title}' 읽기 실패: {e}")
            return pd.DataFrame()

    def _write_df_to_worksheet(self, title: str, df: pd.DataFrame) -> bool:
        """DataFrame 을 워크시트에 전체 덮어쓰기 (conn.update 사용)"""
        try:
            self._conn.update(worksheet=title, data=df)
            logger.info(f"'{title}' 저장 완료 ({len(df)}행)")
            return True
        except Exception as e:
            logger.error(f"'{title}' 저장 실패: {e}")
            return False


# ════════════════════════════════════════════════════════
# 2. snapshot 시트 — 종목 현재가 + 시장 지표 (날짜별 upsert)
# ════════════════════════════════════════════════════════

def save_snapshot(
    writer: SheetsWriter,
    full_df: pd.DataFrame,
    market_status: dict,
    now_kst: Optional[datetime] = None,
) -> bool:
    """
    종목 현재가 + 시장 지표를 snapshot 시트에 upsert.
    기존 data_engine.load_snapshot() 포맷 완전 호환.

    시트 구조: 날짜 | 항목 | 값
    ────────────────────────────────────────
    2026-03-30 | KOSPI       | 2650.00
    2026-03-30 | 삼성전자    | 72400
    2026-03-30 | USD/KRW     | 1385.50
    """
    if now_kst is None:
        now_kst = datetime.now(KST)
    today = now_kst.strftime("%Y-%m-%d")

    rows: list[dict] = []

    # 시장 지표
    for label, data in market_status.items():
        val_str = data.get("val", "-")
        if val_str == "-":
            continue
        try:
            clean = val_str.replace(",", "").replace("%p", "").replace("%", "")
            rows.append({"날짜": today, "항목": label, "값": float(clean)})
        except ValueError:
            pass

    # 종목 현재가 (계좌별 중복 제거 — 종목명 기준 첫 번째)
    if not full_df.empty and {"종목명", "현재가"}.issubset(full_df.columns):
        for name, grp in full_df.groupby("종목명"):
            price = float(grp["현재가"].iloc[0])
            if price > 0:
                rows.append({"날짜": today, "항목": str(name), "값": price})

    if not rows:
        logger.warning("snapshot: 저장할 데이터 없음")
        return False

    new_df = pd.DataFrame(rows)

    try:
        existing = writer._read_worksheet_df(WS_SNAPSHOT)
        if not existing.empty and "날짜" in existing.columns:
            existing = existing[existing["날짜"].astype(str) != today]
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df

        combined = combined.sort_values(["날짜", "항목"]).reset_index(drop=True)
        return writer._write_df_to_worksheet(WS_SNAPSHOT, combined)

    except Exception as e:
        logger.error(f"snapshot upsert 실패: {e}")
        return False


# ════════════════════════════════════════════════════════
# 3. trend 시트 — 계좌별 수익률 시계열 (날짜별 upsert)
# ════════════════════════════════════════════════════════

def save_trend(
    writer: SheetsWriter,
    full_df: pd.DataFrame,
    market_status: dict,
    now_kst: Optional[datetime] = None,
) -> bool:
    """
    계좌별 누적수익률 + KOSPI 지수를 trend 시트에 upsert.
    기존 process_history() 가 읽는 포맷 완전 호환.

    시트 구조: Date | KOSPI | 서은수익률 | 서희수익률 | 큰스님수익률
    """
    if now_kst is None:
        now_kst = datetime.now(KST)
    today = now_kst.strftime("%Y-%m-%d")

    if full_df.empty or "계좌명" not in full_df.columns:
        logger.warning("trend: full_df 없음")
        return False

    # KOSPI 현재값 추출
    kospi_str = market_status.get("KOSPI", {}).get("val", "0")
    try:
        kospi_val = float(kospi_str.replace(",", ""))
    except ValueError:
        kospi_val = 0.0

    # 계좌별 누적수익률 계산
    row: dict = {"Date": today, "KOSPI": kospi_val}
    try:
        from config import ACCOUNTS
        account_list = ACCOUNTS
    except ImportError:
        # [BUG-3 수정] 문자열 리스트 → dict 리스트로 올바르게 생성
        # 기존: acc["name"] 호출 시 TypeError (문자열 인덱싱)
        account_list = [
            {"name": acc, "yield_col": f"{acc}수익률"}
            for acc in full_df["계좌명"].unique()
        ]

    for acc in account_list:
        acc_name  = acc["name"]
        yield_col = acc.get("yield_col", f"{acc_name}수익률")
        sub = full_df[full_df["계좌명"] == acc_name]
        if sub.empty:
            row[yield_col] = 0.0
            continue
        buy  = sub["매입금액"].sum()
        pnl  = sub["손익"].sum()
        row[yield_col] = round((pnl / buy * 100) if buy > 0 else 0.0, 4)

    new_df = pd.DataFrame([row])

    try:
        existing = writer._read_worksheet_df(WS_TREND)
        if not existing.empty and "Date" in existing.columns:
            existing = existing[existing["Date"].astype(str) != today]
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df

        # 날짜 정렬
        combined["Date"] = pd.to_datetime(combined["Date"], errors="coerce")
        combined = combined.dropna(subset=["Date"]).sort_values("Date")
        combined["Date"] = combined["Date"].dt.strftime("%Y-%m-%d")
        combined = combined.reset_index(drop=True)

        return writer._write_df_to_worksheet(WS_TREND, combined)

    except Exception as e:
        logger.error(f"trend upsert 실패: {e}")
        return False


# ════════════════════════════════════════════════════════
# 4. ohlcv_log 시트 — 종목별 일봉 이력 (날짜+종목 upsert)
# ════════════════════════════════════════════════════════

def save_ohlcv_log(
    writer: SheetsWriter,
    ohlcv_map: dict[str, pd.DataFrame],
    now_kst: Optional[datetime] = None,
) -> bool:
    """
    종목별 OHLCV 일봉을 ohlcv_log 시트에 upsert.

    ohlcv_map: {종목명: DataFrame}
      DataFrame 컬럼: Date | 시가 | 고가 | 저가 | 종가 | 거래량

    시트 구조: 날짜 | 종목코드 | 종목명 | 시가 | 고가 | 저가 | 종가 | 거래량

    사용 예:
        from market_collector import get_krx_ohlcv
        from config import STOCK_CODES

        ohlcv_map = {}
        for name, code in STOCK_CODES.items():
            df = get_krx_ohlcv(code, from_date="20260101")
            if not df.empty:
                ohlcv_map[name] = df

        save_ohlcv_log(writer, ohlcv_map)
    """
    if now_kst is None:
        now_kst = datetime.now(KST)
    today = now_kst.strftime("%Y-%m-%d")

    try:
        from config import STOCK_CODES
    except ImportError:
        STOCK_CODES = {}

    all_rows: list[dict] = []
    for name, df in ohlcv_map.items():
        if df.empty:
            continue
        code = STOCK_CODES.get(name, "")
        for _, row in df.iterrows():
            try:
                date_str = str(row.get("Date", ""))[:10]
                all_rows.append({
                    "날짜":   date_str,
                    "종목코드": code,
                    "종목명": name,
                    "시가":   int(row.get("시가", 0)),
                    "고가":   int(row.get("고가", 0)),
                    "저가":   int(row.get("저가", 0)),
                    "종가":   int(row.get("종가", 0)),
                    "거래량": int(row.get("거래량", 0)),
                })
            except Exception:
                continue

    if not all_rows:
        logger.warning("ohlcv_log: 저장할 데이터 없음")
        return False

    new_df = pd.DataFrame(all_rows)

    try:
        existing = writer._read_worksheet_df(WS_OHLCV_LOG)
        if not existing.empty and {"날짜", "종목코드"}.issubset(existing.columns):
            # 오늘 날짜 + 같은 종목코드 행 제거 후 upsert
            today_codes = new_df["종목코드"].unique().tolist()
            mask_remove = (
                (existing["날짜"].astype(str) == today) &
                (existing["종목코드"].astype(str).isin(today_codes))
            )
            existing = existing[~mask_remove]
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df

        combined = combined.sort_values(["날짜", "종목코드"]).reset_index(drop=True)
        return writer._write_df_to_worksheet(WS_OHLCV_LOG, combined)

    except Exception as e:
        logger.error(f"ohlcv_log upsert 실패: {e}")
        return False


# ════════════════════════════════════════════════════════
# 5. market_log 시트 — 시장 지표 시계열 (타임스탬프 append)
# ════════════════════════════════════════════════════════

def save_market_log(
    writer: SheetsWriter,
    market_status: dict,
    now_kst: Optional[datetime] = None,
) -> bool:
    """
    KOSPI·KOSDAQ·USD/KRW·US10Y 를 market_log 시트에 타임스탬프와 함께 append.
    장중 30분마다 호출하면 일중 변동 이력을 보존할 수 있습니다.

    시트 구조: 타임스탬프 | KOSPI | KOSDAQ | USD/KRW | US10Y
    """
    if now_kst is None:
        now_kst = datetime.now(KST)
    ts = now_kst.strftime("%Y-%m-%d %H:%M")

    def _parse(key: str) -> float:
        val = market_status.get(key, {}).get("val", "0")
        try:
            return float(val.replace(",", "").replace("%p", "").replace("%", ""))
        except (ValueError, AttributeError):
            return 0.0

    new_row = pd.DataFrame([{
        "타임스탬프": ts,
        "KOSPI":   _parse("KOSPI"),
        "KOSDAQ":  _parse("KOSDAQ"),
        "USD/KRW": _parse("USD/KRW"),
        "US10Y":   _parse("US10Y"),
    }])

    try:
        existing = writer._read_worksheet_df(WS_MARKET_LOG)
        if not existing.empty:
            combined = pd.concat([existing, new_row], ignore_index=True)
        else:
            combined = new_row

        # [BUG-2 수정] 최근 90일치만 보존 — tz_localize(None) 이중 적용 제거
        # 기존: combined["_dt"].dt.tz_localize(None) → tz-naive 에 재적용 시 TypeError
        if "타임스탬프" in combined.columns:
            combined["_dt"] = pd.to_datetime(combined["타임스탬프"], errors="coerce")
            cutoff = datetime.now() - timedelta(days=90)   # tz-naive 기준
            combined = combined[combined["_dt"].notna() & (combined["_dt"] >= cutoff)]
            combined = combined.drop(columns=["_dt"])

        combined = combined.reset_index(drop=True)
        return writer._write_df_to_worksheet(WS_MARKET_LOG, combined)

    except Exception as e:
        logger.error(f"market_log append 실패: {e}")
        return False


# ════════════════════════════════════════════════════════
# 6. collection_log 시트 — 수집 운영 로그
# ════════════════════════════════════════════════════════

def save_collection_log(
    writer: SheetsWriter,
    results: dict[str, bool],
    source: str = "scheduler",
    now_kst: Optional[datetime] = None,
) -> bool:
    """
    각 저장 작업의 성공·실패 이력을 collection_log 시트에 기록.

    results 예시:
        {
            "snapshot":   True,
            "trend":      True,
            "ohlcv_log":  False,
            "market_log": True,
        }

    시트 구조: 타임스탬프 | 소스 | 항목 | 성공여부 | 비고
    """
    if now_kst is None:
        now_kst = datetime.now(KST)
    ts = now_kst.strftime("%Y-%m-%d %H:%M:%S")

    rows = [
        {
            "타임스탬프": ts,
            "소스":       source,
            "항목":       item,
            "성공여부":   "✅" if ok else "❌",
            "비고":       "",
        }
        for item, ok in results.items()
    ]
    new_df = pd.DataFrame(rows)

    try:
        existing = writer._read_worksheet_df(WS_COLLECTION_LOG)
        if not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df

        # [BUG-2 수정] 최근 180일치만 보존 — tz_localize(None) 이중 적용 제거
        if "타임스탬프" in combined.columns:
            combined["_dt"] = pd.to_datetime(combined["타임스탬프"], errors="coerce")
            cutoff = datetime.now() - timedelta(days=180)  # tz-naive 기준
            combined = combined[combined["_dt"].notna() & (combined["_dt"] >= cutoff)]
            combined = combined.drop(columns=["_dt"])

        combined = combined.reset_index(drop=True)
        return writer._write_df_to_worksheet(WS_COLLECTION_LOG, combined)

    except Exception as e:
        logger.error(f"collection_log 실패: {e}")
        return False


# ════════════════════════════════════════════════════════
# 7. 통합 실행 함수 — 장 마감 후 전체 파이프라인 1회 실행
# ════════════════════════════════════════════════════════

def run_eod_pipeline(
    writer: SheetsWriter,
    full_df: pd.DataFrame,
    market_status: dict,
    ohlcv_map: Optional[dict[str, pd.DataFrame]] = None,
    now_kst: Optional[datetime] = None,
) -> dict[str, bool]:
    """
    장 마감 후 1회 실행하는 통합 파이프라인.
    각 저장 작업은 독립 실행 — 한 시트 실패가 전체 중단 안 함.

    반환: {"snapshot": True, "trend": True, "ohlcv_log": False, ...}

    scheduler.py 에서 호출 예:
        results = run_eod_pipeline(writer, full_df, market_status, ohlcv_map)
        save_collection_log(writer, results, source="eod_scheduler")

    Streamlit app.py 에서 수동 저장 버튼 예:
        if st.sidebar.button("📤 Sheets 저장"):
            results = run_eod_pipeline(writer, full_df, m_status)
            st.sidebar.json(results)
    """
    if now_kst is None:
        now_kst = datetime.now(KST)

    results: dict[str, bool] = {}

    logger.info(f"[EOD 파이프라인 시작] {now_kst.strftime('%Y-%m-%d %H:%M')}")

    # 1. snapshot
    try:
        results["snapshot"] = save_snapshot(writer, full_df, market_status, now_kst)
    except Exception as e:
        logger.error(f"snapshot 예외: {e}")
        results["snapshot"] = False

    time.sleep(1)   # Sheets API rate limit 방지

    # 2. trend
    try:
        results["trend"] = save_trend(writer, full_df, market_status, now_kst)
    except Exception as e:
        logger.error(f"trend 예외: {e}")
        results["trend"] = False

    time.sleep(1)

    # 3. ohlcv_log (데이터가 있을 때만)
    if ohlcv_map:
        try:
            results["ohlcv_log"] = save_ohlcv_log(writer, ohlcv_map, now_kst)
        except Exception as e:
            logger.error(f"ohlcv_log 예외: {e}")
            results["ohlcv_log"] = False
        time.sleep(1)
    else:
        results["ohlcv_log"] = None   # 스킵

    # 4. market_log
    try:
        results["market_log"] = save_market_log(writer, market_status, now_kst)
    except Exception as e:
        logger.error(f"market_log 예외: {e}")
        results["market_log"] = False

    time.sleep(1)

    # 5. 운영 로그 기록
    try:
        save_collection_log(writer, results, source="eod_pipeline", now_kst=now_kst)
    except Exception as e:
        logger.error(f"collection_log 예외: {e}")

    ok_count = sum(1 for v in results.values() if v is True)
    total    = sum(1 for v in results.values() if v is not None)
    logger.info(f"[EOD 파이프라인 완료] 성공 {ok_count}/{total}")

    return results


# ════════════════════════════════════════════════════════
# 8. Streamlit 사이드바 — 수동 저장 UI 컴포넌트
# ════════════════════════════════════════════════════════

def render_sheets_save_button(
    conn,
    full_df: pd.DataFrame,
    market_status: dict,
    now_kst,
):
    """
    사이드바에 'Sheets 저장' 버튼을 추가하는 Streamlit 컴포넌트.
    ui_components.py 의 render_sidebar() 안에서 호출합니다.

    사용 예 (ui_components.py render_sidebar 내부):
        from sheets_pipeline import render_sheets_save_button
        render_sheets_save_button(conn, full_df, m_status, now_kst)
    """
    import streamlit as st

    st.subheader("☁️ Sheets 저장")

    if st.button("📤 지금 저장", use_container_width=True, key="btn_sheets_save"):
        with st.spinner("Google Sheets 저장 중..."):
            try:
                writer  = SheetsWriter.from_streamlit(conn)
                results = run_eod_pipeline(writer, full_df, market_status, now_kst=now_kst)

                # 결과 표시
                for item, ok in results.items():
                    if ok is None:
                        st.caption(f"⏭️ {item}: 스킵")
                    elif ok:
                        st.success(f"✅ {item}", icon="✅")
                    else:
                        st.error(f"❌ {item} 저장 실패")

            except Exception as e:
                st.error(f"Sheets 연결 실패: {e}")
                st.info("로컬 실행 시 from_service_account() 방식을 사용하세요.")


# ════════════════════════════════════════════════════════
# 9. 독립 실행 — python sheets_pipeline.py
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── 설정 ──────────────────────────────────────────────
    SPREADSHEET_ID   = "YOUR_SPREADSHEET_ID"    # ← 스프레드시트 ID 입력
    CREDENTIAL_PATH  = "service_account.json"   # ← 서비스 계정 JSON 경로

    print("=" * 55)
    print("  가족 자산 관제탑 — Google Sheets 저장 파이프라인")
    print("=" * 55)

    # ── 연결 ──────────────────────────────────────────────
    try:
        # [BUG-1 수정] from_service_account() 이제 정상 동작
        writer = SheetsWriter.from_service_account(SPREADSHEET_ID, CREDENTIAL_PATH)
        print("✅ Google Sheets 연결 성공")
    except Exception as e:
        print(f"❌ 연결 실패: {e}")
        sys.exit(1)

    # ── 데이터 수집 ────────────────────────────────────────
    print("\n📡 데이터 수집 중...")
    try:
        from market_collector import get_market_status_v2, get_krx_ohlcv
        from config import STOCK_CODES
        market_status = get_market_status_v2()
        print(f"  시장 지표: {list(market_status.keys())}")
    except Exception as e:
        print(f"  시장 지표 수집 실패: {e}")
        market_status = {}
        STOCK_CODES = {}

    # OHLCV 수집 (최근 30일)
    ohlcv_map: dict = {}
    from_date = (datetime.now(KST) - timedelta(days=30)).strftime("%Y%m%d")
    for name, code in STOCK_CODES.items():
        try:
            df = get_krx_ohlcv(code, from_date)
            if not df.empty:
                ohlcv_map[name] = df
                print(f"  {name}: {len(df)}행")
        except Exception as e:
            print(f"  {name} OHLCV 실패: {e}")

    # full_df 는 Google Sheets 종목현황 탭에서 로드 (여기선 빈 DataFrame 시뮬레이션)
    full_df = pd.DataFrame()
    print("\n⚠️  full_df 가 비어 있습니다. Streamlit 앱에서 실행하면 실제 포트폴리오 데이터가 사용됩니다.")

    # ── 파이프라인 실행 ────────────────────────────────────
    print("\n💾 Google Sheets 저장 시작...")
    now_kst = datetime.now(KST)
    results = run_eod_pipeline(writer, full_df, market_status, ohlcv_map, now_kst)

    print("\n📊 결과:")
    for item, ok in results.items():
        icon = "✅" if ok is True else ("⏭️" if ok is None else "❌")
        print(f"  {icon} {item}")

    # 로그 기록
    save_collection_log(writer, results, source="manual_run", now_kst=now_kst)
    print("\n완료.")
