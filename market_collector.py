"""
market_collector.py — 가족 자산 관제탑 시장 데이터 수집기
=============================================================
우선순위 1: pykrx(KRX 공식) + yfinance 로 네이버 크롤링을 완전 대체합니다.

데이터 소스 역할 분담
─────────────────────────────────────────────────────────────
│ 데이터            │ 소스                │ 이유
│ 국내 종목 주가    │ pykrx               │ KRX 공식 API, 구조 변경 없음
│ KOSPI / KOSDAQ   │ pykrx               │ 지수 공식 데이터
│ 미국 지수/금리    │ yfinance            │ ^GSPC, ^IXIC, ^TNX
│ USD/KRW 환율     │ yfinance            │ USDKRW=X
│ 종목 뉴스         │ 네이버 (유지)        │ 대체 무료 소스 없음
─────────────────────────────────────────────────────────────

외부 의존성 (requirements.txt 에 추가 필요)
    pykrx>=1.0.47
    yfinance>=0.2.36   ← 이미 존재
"""
from __future__ import annotations

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════
# 1. KRX 공식 — 국내 종목 주가 (pykrx)
# ════════════════════════════════════════════════════════

def get_krx_price(code: str, retries: int = 3) -> tuple[int, int]:
    """
    종목 코드 → (현재가, 전일종가) 반환.
    pykrx는 당일 장중에는 전 영업일 종가를 반환하므로
    '현재가 = 오늘 종가(또는 현재)', '전일종가 = 전날 종가' 로 처리합니다.
    실패 시 (0, 0) 반환.
    """
    try:
        from pykrx import stock as krx

        today = datetime.now().strftime("%Y%m%d")
        # 오늘 포함 최근 5 영업일 조회 (휴장일 안전망)
        from_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")

        for attempt in range(retries):
            try:
                df = krx.get_market_ohlcv(from_date, today, code)
                if df is not None and not df.empty:
                    # 마지막 행 = 가장 최근 거래일
                    current = int(df["종가"].iloc[-1])
                    prev    = int(df["종가"].iloc[-2]) if len(df) >= 2 else current
                    return current, prev
            except Exception as e:
                logger.warning(f"pykrx {code} 시도 {attempt+1}/{retries}: {e}")
                if attempt < retries - 1:
                    time.sleep(0.5 * (attempt + 1))

        return 0, 0

    except ImportError:
        logger.error("pykrx 미설치. pip install pykrx 후 재시도하세요.")
        return 0, 0
    except Exception as e:
        logger.error(f"get_krx_price({code}): {e}")
        return 0, 0


def get_krx_prices_parallel(
    code_map: dict[str, str],   # {종목명: 종목코드}
    on_progress=None,
    max_workers: int = 5,        # pykrx는 과도한 병렬 요청 시 차단 → 5 권장
) -> dict[str, tuple[int, int]]:
    """
    여러 종목을 병렬 수집.
    반환: {종목명: (현재가, 전일종가)}
    """
    results: dict[str, tuple[int, int]] = {}
    total = len(code_map)
    done  = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {
            executor.submit(get_krx_price, code): name
            for name, code in code_map.items()
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as e:
                logger.error(f"{name} 수집 실패: {e}")
                results[name] = (0, 0)
            done += 1
            if on_progress:
                on_progress(done, total, name)

    return results


def get_krx_prices_as_list(
    names: list[str],
    stock_codes: dict[str, str],
    on_progress=None,
) -> list[tuple[int, int]]:
    """
    기존 data_engine.get_stock_data_parallel() 과 동일한 인터페이스.
    names 순서대로 (현재가, 전일종가) 리스트 반환.
    """
    # 코드가 없는 종목은 후처리에서 0,0 반환
    code_map = {n: stock_codes[n] for n in names if n in stock_codes}
    price_map = get_krx_prices_parallel(code_map, on_progress=on_progress)
    return [price_map.get(n, (0, 0)) for n in names]


# ════════════════════════════════════════════════════════
# 2. yfinance — 시장 지수·환율·금리
# ════════════════════════════════════════════════════════

# yfinance 티커 정의
_YF_TICKERS = {
    # "KOSPI":   "^KS11",   # ❌ Yahoo Finance 2배 스케일 버그 — pykrx 사용
    # "KOSDAQ":  "^KQ11",   # ❌ Yahoo Finance 2배 스케일 버그 — pykrx 사용
    "USD/KRW": "USDKRW=X",  # 환율
    "US10Y":   "^TNX",       # 미국 10년물 국채금리
    "S&P500":  "^GSPC",      # S&P 500
    "NASDAQ":  "^IXIC",      # NASDAQ
    "DJI":     "^DJI",       # 다우존스
}

def get_yf_market_status(
    tickers: Optional[dict[str, str]] = None,
    period: str = "5d",
) -> dict:
    """
    yfinance 기반 시장 지표 수집.
    반환 형식은 기존 get_market_status() 와 동일하게 유지합니다.

    data[key] = {
        "val":   표시값 문자열,
        "pct":   변동폭 문자열,
        "color": 색상 코드 (상승 #FF4B4B / 하락 #87CEEB / 보합 #ffffff),
    }
    """
    if tickers is None:
        tickers = _YF_TICKERS

    result: dict = {}
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance 미설치")
        return result

    # 일괄 다운로드 (1회 요청으로 여러 티커)
    symbols = list(tickers.values())
    try:
        raw = yf.download(
            tickers=symbols,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        logger.error(f"yfinance download 실패: {e}")
        raw = pd.DataFrame()

    for label, sym in tickers.items():
        try:
            if raw.empty:
                raise ValueError("empty response")

            # 단일/복수 티커에 따른 컬럼 구조 차이 처리
            if len(symbols) == 1:
                close = raw["Close"]
            else:
                close = raw[sym]["Close"] if sym in raw.columns.get_level_values(0) else pd.Series(dtype=float)

            close = close.dropna()
            if len(close) < 2:
                raise ValueError("데이터 부족")

            cur   = float(close.iloc[-1])
            prev  = float(close.iloc[-2])
            delta = cur - prev
            pct   = (delta / prev * 100) if prev != 0 else 0.0

            # 표시 형식 — 지표 유형별 분기
            if label == "USD/KRW":
                val_str = f"{cur:,.2f}"
                pct_str = f"{delta:+.2f}원"
            elif label == "US10Y":
                val_str = f"{cur:.2f}"
                pct_str = f"{delta:+.2f}%p"
            elif label in ("KOSPI", "KOSDAQ", "S&P500", "NASDAQ", "DJI"):
                val_str = f"{cur:,.2f}"
                pct_str = f"{pct:+.2f}%"
            else:
                val_str = f"{cur:,.2f}"
                pct_str = f"{pct:+.2f}%"

            color = "#FF4B4B" if delta > 0 else ("#87CEEB" if delta < 0 else "#ffffff")

            result[label] = {"val": val_str, "pct": pct_str, "color": color}

        except Exception as e:
            logger.warning(f"yfinance {label}({sym}) 처리 실패: {e}")
            result[label] = {"val": "-", "pct": "0.00", "color": "#ffffff"}

    return result


def get_yf_market_status_compatible() -> dict:
    """
    기존 get_market_status() 인터페이스 호환 래퍼.

    수집 전략:
    - KOSPI / KOSDAQ : pykrx (KRX 공식) — ^KS11/^KQ11 사용 금지(2배 버그)
    - USD/KRW        : yfinance USDKRW=X
    - US10Y          : yfinance ^TNX
    """
    defaults = {
        "KOSPI":   {"val": "-", "pct": "0.00%",  "color": "#ffffff"},
        "KOSDAQ":  {"val": "-", "pct": "0.00%",  "color": "#ffffff"},
        "USD/KRW": {"val": "-", "pct": "0원",    "color": "#ffffff"},
        "US10Y":   {"val": "-", "pct": "0.00%p", "color": "#ffffff"},
    }

    # ── KOSPI / KOSDAQ: pykrx ────────────────────────────
    try:
        from pykrx import stock as _krx
        import datetime as _dt

        def _pykrx_index(ticker_code: str, label: str) -> dict:
            """pykrx 지수 OHLCV → 현재가·전일대비 계산"""
            for _back in range(7):
                _d  = (_dt.date.today() - _dt.timedelta(days=_back)).strftime("%Y%m%d")
                _d0 = (_dt.date.today() - _dt.timedelta(days=_back + 10)).strftime("%Y%m%d")
                try:
                    _df = _krx.get_index_ohlcv_by_date(_d0, _d, ticker_code)
                    if _df is None or _df.empty:
                        continue
                    _df = _df[_df["종가"] > 0]
                    if len(_df) < 2:
                        continue
                    _cur  = float(_df["종가"].iloc[-1])
                    _prev = float(_df["종가"].iloc[-2])
                    _chg  = _cur - _prev
                    _pct  = (_chg / _prev * 100) if _prev > 0 else 0.0
                    _sign = "+" if _chg >= 0 else ""
                    return {
                        "val":   f"{_cur:,.2f}",
                        "pct":   f"{_sign}{_pct:.2f}%",
                        "color": "#FF4B4B" if _chg >= 0 else "#87CEEB",
                    }
                except Exception:
                    continue
            return defaults[label].copy()

        defaults["KOSPI"]  = _pykrx_index("1001", "KOSPI")   # KOSPI
        defaults["KOSDAQ"] = _pykrx_index("2001", "KOSDAQ")  # KOSDAQ

    except Exception as e:
        logger.warning(f"pykrx 지수 수집 실패: {e}")

    # ── USD/KRW · US10Y: yfinance ────────────────────────
    try:
        yf_data = get_yf_market_status(
            tickers={
                "USD/KRW": "USDKRW=X",
                "US10Y":   "^TNX",
            }
        )
        for k in ("USD/KRW", "US10Y"):
            if k in yf_data and yf_data[k]["val"] != "-":
                defaults[k] = yf_data[k]
    except Exception as e:
        logger.warning(f"yfinance USD/US10Y 수집 실패: {e}")

    return defaults


# ════════════════════════════════════════════════════════
# 3. 종목 기본 정보 (yfinance Ticker)
# ════════════════════════════════════════════════════════

@lru_cache(maxsize=32)
def get_stock_fundamentals(ticker_symbol: str) -> dict:
    """
    yfinance Ticker.info 로 기업 기본 정보 조회.
    국내 종목은 '종목코드.KS' (KOSPI) 또는 '종목코드.KQ' (KOSDAQ) 형식.

    예: get_stock_fundamentals("005930.KS")  # 삼성전자
    결과 캐싱(LRU 32개) — 동일 세션 내 중복 요청 방지.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(ticker_symbol).info
        return {
            "name":         info.get("longName", ""),
            "market_cap":   info.get("marketCap", 0),
            "per":          info.get("trailingPE", 0),
            "pbr":          info.get("priceToBook", 0),
            "dividend_yield": info.get("dividendYield", 0),
            "52w_high":     info.get("fiftyTwoWeekHigh", 0),
            "52w_low":      info.get("fiftyTwoWeekLow", 0),
            "sector":       info.get("sector", ""),
            "industry":     info.get("industry", ""),
        }
    except Exception as e:
        logger.warning(f"fundamentals({ticker_symbol}): {e}")
        return {}


# ════════════════════════════════════════════════════════
# 4. 히스토리 OHLCV (pykrx — 수익률 추이용)
# ════════════════════════════════════════════════════════

def get_krx_ohlcv(
    code: str,
    from_date: str,          # "YYYYMMDD"
    to_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    종목 코드 → 일봉 OHLCV DataFrame 반환.
    컬럼: Date | 시가 | 고가 | 저가 | 종가 | 거래량

    수집 우선순위:
      1차) pykrx  — KRX 공식 데이터 (로컬 / 허용 네트워크 환경)
      2차) yfinance — Yahoo Finance (Streamlit Cloud 등 KRX 차단 환경 폴백)

    배경:
      Streamlit Cloud 에서 krx.co.kr / stock.naver.com 이 방화벽(403)으로
      차단되어 pykrx 가 항상 빈 DataFrame 을 반환함.
      yfinance 는 Yahoo Finance 를 사용하므로 정상 동작.
    """
    to_date_fmt = to_date if to_date is not None else datetime.now().strftime("%Y%m%d")

    # ── 1차: pykrx ────────────────────────────────────────────────
    try:
        from pykrx import stock as krx
        df = krx.get_market_ohlcv(from_date, to_date_fmt, code)
        if df is not None and not df.empty:
            df.index.name = "Date"
            df = df.reset_index()
            # pykrx 버전별 컬럼명 정규화: "날짜" → "Date"
            if "날짜" in df.columns:
                df = df.rename(columns={"날짜": "Date"})
            logger.info(f"pykrx OHLCV 수집 성공({code}): {len(df)}행")
            return df
        logger.warning(f"pykrx OHLCV 빈 결과({code}) — yfinance 폴백 시도")
    except Exception as e:
        logger.warning(f"pykrx OHLCV 실패({code}): {e} — yfinance 폴백 시도")

    # ── 2차: yfinance 폴백 ────────────────────────────────────────
    try:
        import yfinance as yf

        # YYYYMMDD → YYYY-MM-DD 변환
        from_dt = datetime.strptime(from_date,    "%Y%m%d").strftime("%Y-%m-%d")

        # ★ yfinance history()의 end 파라미터는 exclusive (해당 날짜 미포함)
        # end="2026-04-02" 이면 2026-04-01 까지만 반환 → 당일 데이터 누락
        # 수정: to_date_fmt + 1일을 end 로 설정해야 당일 데이터 포함됨
        to_dt = (
            datetime.strptime(to_date_fmt, "%Y%m%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")

        ticker = yf.Ticker(f"{code}.KS")
        df = ticker.history(start=from_dt, end=to_dt, interval="1d")

        if df is None or df.empty:
            logger.warning(f"yfinance OHLCV 빈 결과({code}.KS)")
            return pd.DataFrame()

        df = df.reset_index()

        # yfinance 컬럼명 → 국내 표준 컬럼명으로 매핑
        col_map = {
            "Date":     "Date",
            "Datetime": "Date",
            "Open":     "시가",
            "High":     "고가",
            "Low":      "저가",
            "Close":    "종가",
            "Volume":   "거래량",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # Date 컬럼을 문자열 "YYYY-MM-DD" 로 정규화 (KST 기준)
        # ★ yfinance KS 종목은 날짜를 UTC 15:00 (= KST 00:00 다음날) 로 반환
        #   tz_localize(None) 만 하면 UTC 날짜 그대로 → 하루 전 날짜로 기록됨
        #   수정: tz_convert("Asia/Seoul") 로 KST 변환 후 날짜 추출
        if "Date" in df.columns:
            df["Date"] = (
                pd.to_datetime(df["Date"], utc=True, errors="coerce")
                .dt.tz_convert("Asia/Seoul")   # UTC → KST (+9h) 변환
                .dt.tz_localize(None)           # tz 제거 (naive datetime)
                .dt.strftime("%Y-%m-%d")
            )

        # 필요한 컬럼만 추출 (없는 컬럼은 무시)
        keep = [c for c in ["Date", "시가", "고가", "저가", "종가", "거래량"] if c in df.columns]
        df = df[keep].dropna(subset=["Date"])

        logger.info(f"yfinance OHLCV 폴백 성공({code}.KS): {len(df)}행")
        return df

    except Exception as e:
        logger.error(f"yfinance OHLCV 폴백도 실패({code}): {e}")
        return pd.DataFrame()


def get_krx_investor_trend(
    code: str,
    from_date: str,
    to_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    외국인·기관·개인 매매 동향 DataFrame 반환.
    컬럼: 기관합계, 기타법인, 개인, 외국인합계, 전체
    """
    try:
        from pykrx import stock as krx
        if to_date is None:
            to_date = datetime.now().strftime("%Y%m%d")
        df = krx.get_market_trading_volume_by_investor(from_date, to_date, code)
        df.index.name = "Date"
        return df.reset_index()
    except Exception as e:
        logger.error(f"get_krx_investor_trend({code}): {e}")
        return pd.DataFrame()


# ════════════════════════════════════════════════════════
# 5. 시장 상태 통합 함수 (폴백 체인)
# ════════════════════════════════════════════════════════

def get_market_status_v2() -> dict:
    """
    data_engine.get_market_status() 의 완전 대체 함수.

    수집 전략 (폴백 체인):
    1. yfinance  — 빠르고 안정적, 구조 변경 없음
    2. 네이버 크롤링 — yfinance 실패 시만 폴백
    """
    status = get_yf_market_status_compatible()

    # 주요 지표 수집 실패 시 네이버 폴백
    missing = [k for k, v in status.items() if v["val"] == "-"]
    if missing:
        logger.info(f"yfinance 실패 지표 {missing} → 네이버 폴백")
        try:
            from data_engine import get_market_status as naver_status
            naver = naver_status()
            for k in missing:
                if k in naver and naver[k]["val"] != "-":
                    status[k] = naver[k]
        except Exception as e:
            logger.warning(f"네이버 폴백도 실패: {e}")

    return status
