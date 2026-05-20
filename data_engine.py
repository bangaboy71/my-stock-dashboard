"""
data_engine.py — 가족 자산 관제탑 데이터 엔진
외부 데이터 수집(크롤링), 정제, 지표 계산, 저장 로직을 담당합니다.
Streamlit import 없이 순수 Python/Pandas 로직만 포함합니다.
  → 테스트·재사용 가능 / UI 레이어와 완전 분리
"""
from __future__ import annotations

import calendar
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import (
    STOCK_CODES, DIVIDEND_SCHEDULE, DIVIDEND_TAX_RATE,
    KOSPI_BASE_DATE_DEFAULT, STOP_LOSS_PCT, TRAILING_PCT, TARGET_ALERT_PCT,
    WS_PORTFOLIO, WS_TREND, WS_MEMO, WS_SNAPSHOT,
    WS_TRADES, WS_DIVIDEND,
)


# ════════════════════════════════════════════════════════
# 1. 시간 헬퍼
# ════════════════════════════════════════════════════════

def get_now_kst() -> datetime:
    """현재 한국 시간 반환"""
    return datetime.now(timezone(timedelta(hours=9)))


# ════════════════════════════════════════════════════════
# 2. 시장 지수 수집
# ════════════════════════════════════════════════════════

def get_market_status() -> dict:
    """
    KOSPI·KOSDAQ·USD/KRW·미국10년물(US10Y) 실시간 수집.

    Yahoo Finance v8 Chart API (requests 직접 호출) 사용.
    Streamlit Cloud에서 네이버/KRX 방화벽 차단 문제 우회.

    반환 키: KOSPI | KOSDAQ | USD/KRW | US10Y
    각 값: {"val": str, "pct": str, "color": str}
    """
    # 기본값 (수집 실패 시 표시)
    data = {
        "KOSPI":   {"val": "-", "pct": "-",    "color": "#ffffff"},
        "KOSDAQ":  {"val": "-", "pct": "-",    "color": "#ffffff"},
        "USD/KRW": {"val": "-", "pct": "-",    "color": "#ffffff"},
        "US10Y":   {"val": "-", "pct": "-",    "color": "#ffffff"},
    }

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://finance.yahoo.com",
    }

    # Yahoo Finance 티커 매핑
    _TICKERS = {
        "KOSPI":   "^KS11",
        "KOSDAQ":  "^KQ11",
        "USD/KRW": "USDKRW=X",
        "US10Y":   "^TNX",
    }

    def _fetch(ticker: str) -> dict | None:
        """Yahoo v8 Chart API로 단일 티커 조회"""
        for base in ("https://query1.finance.yahoo.com",
                     "https://query2.finance.yahoo.com"):
            try:
                resp = requests.get(
                    f"{base}/v8/finance/chart/{ticker}",
                    params={"range": "1d", "interval": "1m",
                            "includePrePost": "false"},
                    headers=_HEADERS,
                    timeout=5,
                )
                if resp.status_code != 200:
                    continue
                result = resp.json().get("chart", {}).get("result")
                if result:
                    return result[0].get("meta", {})
            except Exception:
                continue
        return None

    # ── KOSPI / KOSDAQ ────────────────────────────────────
    # Yahoo Finance ^KS11·^KQ11은 실제 지수값의 2배를 반환하는 버그가 있음.
    # 정상 범위 상한: KOSPI 4,500 / KOSDAQ 1,500
    # 초과 시 /2 보정 후 재검증 → 그래도 초과면 무효 처리.
    _KOSPI_MAX  = 4_500.0
    _KOSDAQ_MAX = 1_500.0

    for key, ticker in [("KOSPI", "^KS11"), ("KOSDAQ", "^KQ11")]:
        meta = _fetch(ticker)
        if not meta:
            continue
        cur  = meta.get("regularMarketPrice")
        prev = meta.get("previousClose") or meta.get("chartPreviousClose")
        if not cur or cur <= 0:
            continue
        limit = _KOSPI_MAX if key == "KOSPI" else _KOSDAQ_MAX
        # 2배 버그 보정: 초과 시 /2 후 재검증
        if cur > limit:
            cur = cur / 2.0
            if prev and prev > limit:
                prev = prev / 2.0
            if cur > limit:   # 보정 후에도 초과면 무효
                continue
        if prev and prev > 0:
            chg  = cur - prev
            pct  = chg / prev * 100
            sign = "+" if chg >= 0 else ""
            color = "#FF4B4B" if chg >= 0 else "#87CEEB"
            data[key]["val"]   = f"{cur:,.2f}"
            data[key]["pct"]   = f"{sign}{chg:,.2f} {sign}{pct:.2f}%"
            data[key]["color"] = color
        else:
            data[key]["val"] = f"{cur:,.2f}"

    # ── USD/KRW ───────────────────────────────────────────
    meta = _fetch("USDKRW=X")
    if meta:
        cur  = meta.get("regularMarketPrice")
        prev = meta.get("previousClose") or meta.get("chartPreviousClose")
        if cur and cur > 0:
            chg   = (cur - prev) if prev and prev > 0 else 0.0
            sign  = "+" if chg >= 0 else ""
            color = "#FF4B4B" if chg >= 0 else "#87CEEB"
            data["USD/KRW"]["val"]   = f"{cur:,.2f}"
            data["USD/KRW"]["pct"]   = f"{sign}{chg:.2f}원"
            data["USD/KRW"]["color"] = color

    # ── US10Y (미국 10년물 국채금리) ──────────────────────
    meta = _fetch("^TNX")
    if meta:
        cur  = meta.get("regularMarketPrice")
        prev = meta.get("previousClose") or meta.get("chartPreviousClose")
        if cur and cur > 0:
            chg   = (cur - prev) if prev and prev > 0 else 0.0
            sign  = "+" if chg >= 0 else ""
            color = "#FF4B4B" if chg >= 0 else "#87CEEB"
            data["US10Y"]["val"]   = f"{cur:.2f}"
            data["US10Y"]["pct"]   = f"{sign}{chg:.2f}%p"
            data["US10Y"]["color"] = color

    return data


# ════════════════════════════════════════════════════════
# 3. 종목 주가 수집
# ════════════════════════════════════════════════════════

def _yahoo_api_price(ticker_sym: str) -> tuple[int, int]:
    """
    Yahoo Finance v8 Chart API → (현재가, 전일종가).

    requests 직접 호출 — yfinance 라이브러리 불필요.
    meta.regularMarketPrice = 장중 실시간 현재가
    meta.previousClose      = 전일 확정 종가

    가격 합리성 검증(1 ~ 5,000,000원):
    .KS로 잘못 조회된 KOSDAQ 종목 등 오류 가격 차단.
    """
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": "https://finance.yahoo.com",
    }
    _MIN, _MAX = 1, 5_000_000

    for base in ("https://query1.finance.yahoo.com",
                 "https://query2.finance.yahoo.com"):
        url = f"{base}/v8/finance/chart/{ticker_sym}"
        try:
            resp = requests.get(
                url,
                params={"range": "1d", "interval": "1m", "includePrePost": "false"},
                headers=_HEADERS,
                timeout=5,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            result = data.get("chart", {}).get("result")
            if not result:
                continue
            meta = result[0].get("meta", {})
            cur  = meta.get("regularMarketPrice")
            prev = meta.get("previousClose") or meta.get("chartPreviousClose")
            if cur and _MIN <= cur <= _MAX:
                prev_val = int(prev) if prev and _MIN <= prev <= _MAX else int(cur)
                return int(cur), prev_val
        except Exception:
            continue
    return 0, 0


def get_stock_data(name: str, code: str = None) -> tuple[int, int]:
    """
    종목명 → (현재가, 전일종가) 반환. 실패 시 (0, 0).

    수집 전략:
      1차) Yahoo Finance v8 Chart API — regularMarketPrice(실시간) + previousClose
           Streamlit Cloud에서 네이버/KRX 방화벽 차단 문제 완전 우회.
      2차) yfinance history("5d") 폴백 — 1차 실패 시.
    PREFERRED_STOCK_TICKERS 등록 종목은 명시 Yahoo 티커 우선 사용.
    (테스 095610.KQ, 우선주, 신규상장 ETF 영숫자 코드 등)
    """
    if not code:
        code = STOCK_CODES.get(str(name).replace(" ", ""))
    if not code:
        return 0, 0

    # ── 티커 목록 결정 ────────────────────────────────────────
    tickers_to_try: list[str] = []
    try:
        from config import PREFERRED_STOCK_TICKERS as _PREF
        _explicit = next(
            (v for v in _PREF.values() if v.split(".")[0] == code),
            None,
        )
        if _explicit:
            tickers_to_try = [_explicit]
    except Exception:
        pass
    if not tickers_to_try:
        tickers_to_try = [f"{code}.KS", f"{code}.KQ"]

    # ── 1차: Yahoo v8 직접 호출 ──────────────────────────────
    for ticker_sym in tickers_to_try:
        cur, prev = _yahoo_api_price(ticker_sym)
        if cur > 0:
            return cur, prev

    # ── 2차: yfinance history 폴백 ───────────────────────────
    try:
        import yfinance as yf
        for ticker_sym in tickers_to_try:
            try:
                hist = yf.Ticker(ticker_sym).history(period="5d", interval="1d")
                if hist is not None and not hist.empty:
                    cur  = int(hist["Close"].iloc[-1])
                    prev = int(hist["Close"].iloc[-2]) if len(hist) >= 2 else cur
                    if 1 <= cur <= 5_000_000:
                        return cur, prev
            except Exception:
                continue
    except Exception:
        pass

    return 0, 0


def get_stock_data_parallel(
    names: list[str],
    on_progress=None,
    portfolio_df=None,
) -> list[tuple[int, int]]:
    """
    종목 리스트를 ThreadPoolExecutor로 병렬 수집 (원본 순서 보장).
    on_progress(done, total, name): 종목 1개 완료 시 호출되는 콜백.
    portfolio_df: STOCK_CODES 미등록 신규 종목의 코드 폴백 (종목코드 컬럼 참조).
    """
    # 종목코드 폴백 맵: 시트의 종목코드 컬럼(예: "0173Y0.KS") → 숫자 코드 추출
    fallback_code_map: dict[str, str] = {}
    if portfolio_df is not None and not portfolio_df.empty:
        code_col = next(
            (c for c in ["종목코드", "코드", "code"] if c in portfolio_df.columns),
            None,
        )
        if code_col:
            for _, r in portfolio_df.iterrows():
                nm = str(r.get("종목명", "")).strip()
                cd = str(r.get(code_col, "")).strip()
                if nm and cd and nm not in STOCK_CODES:
                    cd_clean = cd.split(".")[0].strip()
                    if cd_clean:
                        fallback_code_map[nm] = cd_clean

    results = {}
    total = len(names)
    done  = 0
    with ThreadPoolExecutor(max_workers=min(total, 10)) as executor:
        future_to_name = {
            executor.submit(
                get_stock_data, n,
                fallback_code_map.get(n),      # 미등록 종목 코드 전달
            ): n for n in names
        }
        for future in as_completed(future_to_name):
            n = future_to_name[future]
            try:
                results[n] = future.result()
            except Exception:
                results[n] = (0, 0)
            done += 1
            if on_progress:
                on_progress(done, total, n)
    return [results.get(n, (0, 0)) for n in names]


# ════════════════════════════════════════════════════════
# 4. 뉴스 수집
# ════════════════════════════════════════════════════════

def get_stock_news(name: str) -> list[dict]:
    """종목명 → 최신 뉴스 6개 반환"""
    code = STOCK_CODES.get(str(name).replace(" ", ""))
    if not code:
        return []
    news_list = []
    header = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://finance.naver.com/item/main.naver?code={code}",
    }
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}"
        res = requests.get(url, headers=header, timeout=5)
        res.encoding = "euc-kr"
        soup   = BeautifulSoup(res.text, "html.parser")
        titles = soup.find_all("td", class_="title")
        infos  = soup.find_all("td", class_="info")
        dates  = soup.find_all("td", class_="date")

        for i in range(min(len(titles), 6)):
            link_el  = titles[i].find("a")
            date_str = dates[i].get_text(strip=True) if i < len(dates) else "-"
            is_recent = False
            try:
                if "전" in date_str:
                    is_recent = True
                else:
                    n_time = datetime.strptime(date_str, "%Y.%m.%d %H:%M")
                    if (datetime.now() - n_time).total_seconds() < 86400:
                        is_recent = True
            except Exception:
                pass
            if link_el:
                news_list.append({
                    "title":     link_el.get_text(strip=True),
                    "link":      "https://finance.naver.com" + link_el["href"],
                    "info":      infos[i].get_text(strip=True) if i < len(infos) else "정보없음",
                    "date":      date_str,
                    "is_recent": is_recent,
                })
    except Exception:
        pass
    return news_list


# ════════════════════════════════════════════════════════
# 5. 구글 시트 데이터 로드
# ════════════════════════════════════════════════════════

def load_sheets(conn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    구글 시트에서 세 워크시트를 읽어 반환.
    Returns: (full_df, history_df, memo_df)
    실패 시 ValueError 발생 → 호출부에서 st.stop() 처리
    """
    full_df    = conn.read(worksheet=WS_PORTFOLIO, ttl="1m")
    history_df = conn.read(worksheet=WS_TREND,     ttl=0)
    try:
        memo_df = conn.read(worksheet=WS_MEMO, ttl=0)
        if memo_df.empty or "종목명" not in memo_df.columns:
            memo_df = pd.DataFrame(columns=["종목명", "계좌명", "메모", "수정일시"])
    except Exception:
        memo_df = pd.DataFrame(columns=["종목명", "계좌명", "메모", "수정일시"])
    return full_df, history_df, memo_df


def load_snapshot(conn) -> dict:
    """
    구글 시트 'snapshot' 워크시트에서 날짜별 팩트 수치를 읽어 반환.

    시트 구조 (헤더: 날짜 | 항목 | 값)
    ─────────────────────────────────
    2026-03-09 | KOSPI                        | 5251.87
    2026-03-09 | 삼성전자                     | 111400
    2026-03-09 | KODEX200타겟위클리커버드콜   | 16515

    반환: {"2026-03-09": {"KOSPI": 5251.87, "삼성전자": 111400.0, ...}, ...}
    시트 없음 / 오류 시 빈 dict 반환 (앱은 현재가로 폴백)
    """
    try:
        df = conn.read(worksheet=WS_SNAPSHOT, ttl=0)
        if df.empty or not {"날짜", "항목", "값"}.issubset(df.columns):
            return {}
        result: dict = {}
        for _, row in df.iterrows():
            date_str = str(row["날짜"]).strip()
            item     = str(row["항목"]).strip()
            try:
                val = float(row["값"])
            except (ValueError, TypeError):
                continue
            result.setdefault(date_str, {})[item] = val
        return result
    except Exception:
        return {}


def load_overrides(path: str = "overrides.toml") -> dict:
    """
    로컬 overrides.toml에서 설정을 읽어 반환 (오프라인 폴백).
    파일 없으면 빈 dict 반환.

    overrides.toml 예시
    ───────────────────
    [app]
    kospi_base_date = "2026-03-03"

    [snapshots."2026-03-09"]
    KOSPI                        = 5251.87
    삼성전자                     = 111400.0
    KODEX200타겟위클리커버드콜   = 16515.0
    """
    try:
        import sys
        if sys.version_info >= (3, 11):
            import tomllib
            with open(path, "rb") as f:
                return tomllib.load(f)
        else:
            import tomli  # pip install tomli
            with open(path, "rb") as f:
                return tomli.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def resolve_settings(conn) -> dict:
    """
    설정값을 우선순위에 따라 병합해 반환.
    우선순위: secrets.toml  >  구글 시트 snapshot  >  overrides.toml  >  코드 기본값

    반환 dict 키
    ─────────────────────────────────────────────────────
    kospi_base_date : str   — KOSPI 상대비교 기준일
    snapshot        : dict  — { "날짜": {"항목": 값, ...} }
    """
    # 1. 코드 기본값
    settings = {
        "kospi_base_date": KOSPI_BASE_DATE_DEFAULT,
        "snapshot":        {},
    }

    # 2. overrides.toml (로컬 폴백)
    overrides = load_overrides()
    if "app" in overrides:
        if "kospi_base_date" in overrides["app"]:
            settings["kospi_base_date"] = overrides["app"]["kospi_base_date"]
    if "snapshots" in overrides:
        for date_str, vals in overrides["snapshots"].items():
            settings["snapshot"].setdefault(date_str, {}).update(vals)

    # 3. 구글 시트 snapshot (overrides보다 우선)
    sheet_snap = load_snapshot(conn)
    for date_str, vals in sheet_snap.items():
        settings["snapshot"].setdefault(date_str, {}).update(vals)

    # 4. Streamlit secrets.toml (최우선)
    try:
        import streamlit as st
        sec_app = st.secrets.get("app", {})
        if "kospi_base_date" in sec_app:
            settings["kospi_base_date"] = sec_app["kospi_base_date"]
        # secrets의 스냅샷 (선택적)
        sec_snap = st.secrets.get("snapshots", {})
        for date_str, vals in sec_snap.items():
            settings["snapshot"].setdefault(date_str, {}).update(dict(vals))
    except Exception:
        pass

    return settings


# ════════════════════════════════════════════════════════
# 6. 데이터 정제 및 지표 계산
# ════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════
# 거래내역 로드 및 평균단가 계산
# ════════════════════════════════════════════════════════

def load_dividend_actual(conn, portfolio_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    구글 시트 '배당실적' 탭 로드 및 정제.

    시트 컬럼: 입금일 | 계좌명 | 종목명 | 수량 | 주당금액 | 세후금액 | 주당과세표준액 | 비고
    반환 컬럼: 입금일 | 계좌명 | 종목명 | 수량 | 주당금액 | 세전금액 | 세후금액 | 연도 | 연월
    실패 시 빈 DataFrame 반환.
    """
    try:
        df = conn.read(worksheet=WS_DIVIDEND, ttl=0)
        if df.empty:
            return pd.DataFrame()
        df.columns = [str(c).strip() for c in df.columns]

        required = {"입금일", "계좌명", "종목명"}
        if not required.issubset(df.columns):
            return pd.DataFrame()

        df["입금일"] = pd.to_datetime(df["입금일"], errors="coerce")
        df = df.dropna(subset=["입금일"]).copy()

        # 수치 컬럼 정제
        for col in ["수량", "주당금액", "세후금액"]:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", ""), errors="coerce"
                ).fillna(0)
            else:
                df[col] = 0.0

        # 수량이 없으면 portfolio_df에서 보완
        if portfolio_df is not None and not portfolio_df.empty:
            qty_map: dict[tuple, float] = {}
            for _, r in portfolio_df.iterrows():
                key = (str(r.get("계좌명", "")).strip(),
                       str(r.get("종목명", "")).strip())
                qty_map[key] = float(r.get("수량", 0))
            mask_zero = df["수량"] == 0
            for idx in df[mask_zero].index:
                k = (str(df.at[idx, "계좌명"]).strip(),
                     str(df.at[idx, "종목명"]).strip())
                if k in qty_map:
                    df.at[idx, "수량"] = qty_map[k]

        # 세전금액 계산 (주당금액 × 수량)
        df["세전금액"] = df["주당금액"] * df["수량"]

        # 세후금액 비어있으면 세전 × (1 - 배당세율) 자동 계산
        mask_no_net = df["세후금액"] == 0
        df.loc[mask_no_net, "세후금액"] = (
            df.loc[mask_no_net, "세전금액"] * (1 - DIVIDEND_TAX_RATE)
        ).round()

        # 연도·연월 컬럼 추가
        df["연도"] = df["입금일"].dt.year.astype(int)
        df["연월"] = df["입금일"].dt.strftime("%Y-%m")

        cols = ["입금일", "계좌명", "종목명", "수량", "주당금액", "세전금액", "세후금액", "연도", "연월"]
        return df[[c for c in cols if c in df.columns]].reset_index(drop=True)

    except Exception:
        return pd.DataFrame()


def load_trades(conn) -> pd.DataFrame:
    """
    구글 시트 '거래내역' 탭 로드.
    컬럼: 날짜 | 계좌명 | 종목명 | 구분 | 수량 | 단가 | 수수료 | 메모
    실패 시 빈 DataFrame 반환.
    """
    try:
        df = conn.read(worksheet=WS_TRADES, ttl=0)
        if df.empty:
            return pd.DataFrame()
        df.columns = [str(c).strip() for c in df.columns]
        # 필수 컬럼 확인
        required = {"날짜", "계좌명", "종목명", "구분", "수량", "단가"}
        if not required.issubset(df.columns):
            return pd.DataFrame()
        df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(0)
        df["단가"] = pd.to_numeric(df["단가"], errors="coerce").fillna(0)
        df = df[df["수량"] > 0].copy()
        return df
    except Exception:
        return pd.DataFrame()


def calc_avg_cost(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    거래내역 → 종목별 평균단가 계산 (FIFO 방식).

    반환 DataFrame 컬럼: 계좌명 | 종목명 | 수량 | 평균단가 | 매입금액
    attrs["sell_df"]: 매도 실적 DataFrame (편매 실적 탭용)
    """
    if trades_df.empty:
        df = pd.DataFrame(columns=["계좌명", "종목명", "수량", "평균단가", "매입금액"])
        df.attrs["sell_df"] = pd.DataFrame()
        return df

    sell_records = []
    # (계좌명, 종목명) 별로 매수 내역 누적
    holdings: dict[tuple, list[tuple[float, float]]] = {}  # key → [(수량, 단가)]

    # 날짜순 정렬
    df = trades_df.copy()
    if "날짜" in df.columns:
        df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
        df = df.sort_values("날짜")

    for _, row in df.iterrows():
        acc   = str(row.get("계좌명", "")).strip()
        name  = str(row.get("종목명", "")).strip()
        구분   = str(row.get("구분", "")).strip()
        qty   = float(row.get("수량", 0))
        price = float(row.get("단가", 0))
        key   = (acc, name)

        if 구분 == "매수":
            holdings.setdefault(key, []).append((qty, price))
        elif 구분 in ("매도", "일부매도"):
            # FIFO 방식으로 매도 처리
            remaining = qty
            cost_basis = 0.0
            lots = holdings.get(key, [])
            new_lots = []
            for lot_qty, lot_price in lots:
                if remaining <= 0:
                    new_lots.append((lot_qty, lot_price))
                    continue
                if lot_qty <= remaining:
                    cost_basis += lot_qty * lot_price
                    remaining -= lot_qty
                else:
                    cost_basis += remaining * lot_price
                    new_lots.append((lot_qty - remaining, lot_price))
                    remaining = 0
            holdings[key] = new_lots
            avg_cost_sold = cost_basis / qty if qty > 0 else 0
            realized = (price - avg_cost_sold) * qty
            ret_pct  = ((price / avg_cost_sold) - 1) * 100 if avg_cost_sold > 0 else 0.0
            _날짜 = row.get("날짜")
            _날짜_str = str(_날짜)[:10] if _날짜 is not None else ""
            sell_records.append({
                "매도일":      _날짜_str,          # ui_components 요구: "매도일"
                "날짜":        _날짜,
                "계좌명":      acc,
                "종목명":      name,
                "매도수량":    qty,
                "매도단가":    price,
                "매도금액":    price * qty,         # ui_components 요구: "매도금액"
                "평균매입단가": avg_cost_sold,
                "실현손익":    realized,
                "수익률(%)":   round(ret_pct, 2),   # ui_components 요구: "수익률(%)"
                "연도":        _날짜_str[:4] if _날짜_str else "",
            })

    # 보유 잔고 → 평균단가 계산
    rows = []
    for (acc, name), lots in holdings.items():
        total_qty  = sum(q for q, _ in lots)
        total_cost = sum(q * p for q, p in lots)
        if total_qty > 0:
            rows.append({
                "계좌명":   acc,
                "종목명":   name,
                "수량":     total_qty,
                "평균단가": round(total_cost / total_qty),
                "매입금액": round(total_cost),
            })

    result = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["계좌명", "종목명", "수량", "평균단가", "매입금액"]
    )
    sell_df = pd.DataFrame(sell_records) if sell_records else pd.DataFrame()
    result.attrs["sell_df"] = sell_df
    return result


def merge_trades_to_portfolio(
    full_df: pd.DataFrame,
    avg_cost_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    종목현황(full_df)에 거래내역 기반 평균단가를 병합.
    매입단가를 평균단가로, 수량도 거래내역 기준으로 보완.
    """
    if avg_cost_df.empty or full_df.empty:
        return full_df

    df = full_df.copy()
    for _, row in avg_cost_df.iterrows():
        acc  = row["계좌명"]
        name = row["종목명"]
        mask = (
            (df["계좌명"].str.strip() == acc) &
            (df["종목명"].str.strip() == name)
        )
        if mask.any():
            # 평균단가 업데이트
            df.loc[mask, "매입단가"] = row["평균단가"]
            df.loc[mask, "수량"]     = row["수량"]
    return df


def process_portfolio(full_df: pd.DataFrame, prices: list[tuple]) -> pd.DataFrame:
    """
    주가 수집 결과를 받아 수익 지표·보유일수 계산 후 반환.
    prices: get_stock_data_parallel() 결과 리스트
    """
    df = full_df.copy()
    df.columns = [c.strip() for c in df.columns]

    # 숫자 컬럼 변환
    num_cols = ["수량", "매입단가", "52주최고가", "매입후최고가", "목표가", "주당 배당금", "목표수익률"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",", "").str.replace("%", ""),
                errors="coerce",
            ).fillna(0)
        elif c == "목표수익률":
            df["목표수익률"] = 10.0

    # 주가 반영
    df["현재가"],  df["전일종가"] = zip(*prices)

    # 수익 지표
    df["매입금액"]       = df["수량"] * df["매입단가"]
    df["평가금액"]       = df["수량"] * df["현재가"]
    df["손익"]           = df["평가금액"] - df["매입금액"]
    df["전일대비손익"]   = df["평가금액"] - (df["수량"] * df["전일종가"])
    df["전일평가액"]     = df["평가금액"] - df["전일대비손익"]
    df["예상배당금"]     = df["수량"] * df["주당 배당금"]
    df["누적수익률"]     = (df["손익"] / df["매입금액"].replace(0, float("nan")) * 100).fillna(0)
    df["전일대비변동율"] = (
        df["전일대비손익"] / df["전일평가액"].replace(0, float("nan")) * 100
    ).fillna(0)
    df["목표대비상승여력"] = df.apply(
        lambda x: ((x["목표가"] / x["현재가"] - 1) * 100)
        if x["현재가"] > 0 and x["목표가"] > 0 else 0,
        axis=1,
    )

    # 보유일수
    if "최초매입일" in df.columns:
        df["최초매입일"] = pd.to_datetime(df["최초매입일"], errors="coerce")
        base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        df["보유일수"] = (
            (base - df["최초매입일"].dt.tz_localize(None))
            .dt.days.fillna(365).astype(int).clip(lower=1)
        )
    else:
        df["보유일수"] = 365

    return df


def process_history(
    history_df: pd.DataFrame,
    kospi_base_date: str = KOSPI_BASE_DATE_DEFAULT,
) -> pd.DataFrame:
    """수익률 추이 정규화 및 KOSPI 상대 수익률 계산"""
    df = (
        history_df.copy()
        .pipe(lambda d: d.assign(Date=pd.to_datetime(d["Date"], errors="coerce")))
        .dropna(subset=["Date"])
        .sort_values("Date")
        .drop_duplicates("Date", keep="last")
        .reset_index(drop=True)
    )
    base_date = pd.Timestamp(kospi_base_date)
    base_row  = df[df["Date"] == base_date]
    base_val  = base_row["KOSPI"].values[0] if not base_row.empty else df["KOSPI"].iloc[0]
    df["KOSPI_Relative"] = (df["KOSPI"] / base_val - 1) * 100
    return df


# ════════════════════════════════════════════════════════
# 7. 헬퍼 함수
# ════════════════════════════════════════════════════════

def get_cashflow_grade(amount: float) -> str:
    """월 세후 수령액 기준 등급 반환"""
    if amount >= 1_000_000: return "💎 Diamond"
    if amount >= 300_000:   return "🥇 Gold"
    if amount >= 100_000:   return "🥈 Silver"
    return "🥉 Bronze"


def find_matching_col(df: pd.DataFrame, account: str, stock: str = None):
    """계좌명(+종목명) 기준으로 history_df 컬럼명 탐색"""
    prefix = account.replace("투자", "").replace(" ", "")
    target = (
        f"{prefix}{stock}수익률".replace(" ", "").replace("_", "")
        if stock
        else f"{prefix}수익률".replace(" ", "").replace("_", "")
    )
    for col in df.columns:
        if target == str(col).replace(" ", "").replace("_", "").replace("투자", ""):
            return col
    return None


def get_dividend_calendar(df: pd.DataFrame, now_kst: datetime) -> list[dict]:
    """보유 종목 기준 향후 배당·분배금 예정일 목록 계산.
    DIVIDEND_SCHEDULE은 (월, 일) 튜플 리스트.
    일(day)=0 이면 해당 월의 말일로 자동 계산.
    """
    today  = now_kst.date()
    events = []
    for _, row in df.iterrows():
        name    = row.get("종목명", "")
        acc     = row.get("계좌명", "")
        div_amt = float(row.get("예상배당금", 0))
        if div_amt <= 0:
            continue
        schedule = DIVIDEND_SCHEDULE.get(name, [])
        if not schedule:
            continue

        for entry in schedule:
            # 하위 호환: 기존 정수(월만) 형식도 허용
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                m, d = int(entry[0]), int(entry[1])
            else:
                m, d = int(entry), 0

            # 지급일 계산: d=0이면 말일
            for year in [today.year, today.year + 1]:
                last_day = calendar.monthrange(year, m)[1]
                pay_day  = last_day if d == 0 else min(d, last_day)
                pay_date = datetime(year, m, pay_day).date()
                if pay_date >= today:
                    break

            events.append({
                "종목명":    name,
                "계좌명":    acc,
                "배당월":    m,
                "지급일":    pay_day,
                "지급예정일": pay_date,
                "D_DAY":     (pay_date - today).days,
                "예상배당금": div_amt / len(schedule),
            })

    events.sort(key=lambda x: (x["D_DAY"], -x["예상배당금"]))
    return events


# ════════════════════════════════════════════════════════
# 8. 메모 CRUD
# ════════════════════════════════════════════════════════

def get_memo(memo_df: pd.DataFrame, stock_name: str, acc_name: str) -> str:
    """메모 DataFrame에서 특정 종목+계좌 메모 반환"""
    if memo_df.empty:
        return ""
    row = memo_df[
        (memo_df["종목명"] == stock_name) & (memo_df["계좌명"] == acc_name)
    ]
    return str(row["메모"].values[0]) if not row.empty else ""


def save_memo(
    conn, memo_df: pd.DataFrame,
    stock_name: str, acc_name: str,
    text: str, now_kst: datetime,
) -> tuple[bool, pd.DataFrame]:
    """
    메모 upsert 후 (성공여부, 갱신된 memo_df) 반환.
    conn: Streamlit GSheets 연결 객체 (app.py에서 전달)
    """
    now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S")
    new_row = pd.DataFrame([{
        "종목명": stock_name, "계좌명": acc_name,
        "메모": text, "수정일시": now_str,
    }])
    mask        = ~((memo_df["종목명"] == stock_name) & (memo_df["계좌명"] == acc_name))
    updated_df  = pd.concat([memo_df[mask], new_row], ignore_index=True)
    try:
        conn.update(worksheet=WS_MEMO, data=updated_df)
        return True, updated_df
    except Exception as e:
        return False, memo_df


# ════════════════════════════════════════════════════════
# 9. 내보내기
# ════════════════════════════════════════════════════════

def build_export_df(df: pd.DataFrame) -> pd.DataFrame:
    """내보내기용 컬럼 추출 및 포맷 정리"""
    cols = [
        "계좌명", "종목명", "수량", "매입단가", "매입금액",
        "현재가", "평가금액", "손익", "누적수익률",
        "전일대비손익", "전일대비변동율", "예상배당금", "목표가", "목표대비상승여력",
    ]
    out = df[[c for c in cols if c in df.columns]].copy()
    for c in ["매입단가", "매입금액", "현재가", "평가금액", "손익",
              "전일대비손익", "예상배당금", "목표가"]:
        if c in out.columns:
            out[c] = out[c].apply(lambda x: round(x, 0) if pd.notna(x) else 0)
    for c in ["누적수익률", "전일대비변동율", "목표대비상승여력"]:
        if c in out.columns:
            out[c] = out[c].apply(lambda x: round(x, 2) if pd.notna(x) else 0)
    return out


def get_csv_bytes(df: pd.DataFrame) -> bytes:
    return build_export_df(df).to_csv(
        index=False, encoding="utf-8-sig"
    ).encode("utf-8-sig")


def get_excel_bytes(df: pd.DataFrame, history_df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        build_export_df(df).to_excel(writer, sheet_name="전체 종목 현황", index=False)
        for acc in df["계좌명"].unique():
            build_export_df(df[df["계좌명"] == acc]).to_excel(
                writer, sheet_name=acc.replace("투자", "")[:10], index=False
            )
        if not history_df.empty:
            history_df.copy().to_excel(writer, sheet_name="수익률 추이", index=False)
    return buf.getvalue()


# ════════════════════════════════════════════════════════
# 10. 목표가 도달 토스트 알림
# ════════════════════════════════════════════════════════

def check_and_toast_targets(df: pd.DataFrame):
    """
    현재가가 목표가에 도달·근접한 종목을 st.toast로 알림.
    Streamlit import는 이 함수 내에서만 사용 (data_engine 전체를 오염시키지 않음).
    """
    import streamlit as st
    if df.empty or "현재가" not in df.columns or "목표가" not in df.columns:
        return

    alerted = st.session_state.get("toasted_targets", set())
    for _, row in df.iterrows():
        name   = row.get("종목명", "")
        curr   = float(row.get("현재가", 0))
        target = float(row.get("목표가", 0))
        ret    = float(row.get("누적수익률", 0))
        if curr <= 0 or target <= 0 or name in alerted:
            continue
        ratio = curr / target
        if ratio >= 1.0:
            st.toast(
                f"🎯 **{name}** 목표가 달성!\n"
                f"현재가 **{curr:,.0f}원** ≥ 목표가 **{target:,.0f}원**\n"
                f"누적 수익률 **{ret:+.2f}%**",
                icon="🚀",
            )
            alerted.add(name)
        elif ratio >= TARGET_ALERT_PCT:
            st.toast(
                f"📡 **{name}** 목표가 근접 ({TARGET_ALERT_PCT*100:.0f}%)\n"
                f"현재가 {curr:,.0f}원 / 목표가 {target:,.0f}원\n"
                f"잔여 여력 **{(ratio-1)*100:+.1f}%**",
                icon="⚡",
            )
            alerted.add(name)
    st.session_state["toasted_targets"] = alerted
