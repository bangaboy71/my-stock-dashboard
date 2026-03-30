"""
analysis_engine.py — 가족 자산 관제탑 기술적 지표 분석 엔진
=============================================================

지원 지표: RSI · MACD · 볼린저밴드 · 이동평균 · 거래량 추이

라이브러리 폴백 체인 (자동 감지)
─────────────────────────────────────────────────────────────
1순위  TA-Lib       C 라이브러리 — 가장 빠름
        설치: apt-packages.txt 에 libta-lib0 추가 후 pip install TA-Lib
2순위  pandas_ta    순수 Python — Streamlit Cloud 즉시 사용 가능
        설치: pip install pandas-ta
3순위  numpy 직접   외부 의존성 없음 — 항상 동작
─────────────────────────────────────────────────────────────

입력 DataFrame 컬럼 (data_store.load_ohlcv_from_cache 출력과 동일)
    Date | 시가 | 고가 | 저가 | 종가 | 거래량

사용 예
─────────────────────────────────────────────────────────────
    from analysis_engine import TechnicalAnalysis

    ta = TechnicalAnalysis.from_cache("005930")   # SQLite 자동 로드
    result = ta.run_all()

    print(result.rsi.iloc[-1])           # 최신 RSI
    print(result.macd_signal.iloc[-1])   # MACD 시그널
    print(result.bb_upper.iloc[-1])      # 볼린저밴드 상단

    # Streamlit 차트
    ta.render_chart("삼성전자")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


# ════════════════════════════════════════════════════════
# 라이브러리 감지
# ════════════════════════════════════════════════════════

def _detect_backend() -> str:
    """사용 가능한 지표 라이브러리 자동 감지"""
    try:
        import talib  # noqa: F401
        return "talib"
    except ImportError:
        pass
    try:
        import pandas_ta  # noqa: F401
        return "pandas_ta"
    except ImportError:
        pass
    return "numpy"

_BACKEND = _detect_backend()
logger.info(f"기술적 지표 백엔드: {_BACKEND}")


# ════════════════════════════════════════════════════════
# 결과 컨테이너
# ════════════════════════════════════════════════════════

@dataclass
class TAResult:
    """
    모든 기술적 지표 계산 결과를 담는 컨테이너.
    각 Series는 원본 OHLCV DataFrame 과 동일한 DatetimeIndex 를 가짐.
    """
    close:       pd.Series = field(default_factory=pd.Series)
    volume:      pd.Series = field(default_factory=pd.Series)

    # ── 이동평균 ──────────────────────────────────────
    ma5:         pd.Series = field(default_factory=pd.Series)
    ma20:        pd.Series = field(default_factory=pd.Series)
    ma60:        pd.Series = field(default_factory=pd.Series)
    ma120:       pd.Series = field(default_factory=pd.Series)

    # ── RSI ───────────────────────────────────────────
    rsi:         pd.Series = field(default_factory=pd.Series)   # 기본 14일

    # ── MACD ──────────────────────────────────────────
    macd:        pd.Series = field(default_factory=pd.Series)   # MACD 라인
    macd_signal: pd.Series = field(default_factory=pd.Series)   # 시그널 라인
    macd_hist:   pd.Series = field(default_factory=pd.Series)   # 히스토그램

    # ── 볼린저밴드 (20일, 2σ) ─────────────────────────
    bb_upper:    pd.Series = field(default_factory=pd.Series)
    bb_mid:      pd.Series = field(default_factory=pd.Series)   # = MA20
    bb_lower:    pd.Series = field(default_factory=pd.Series)
    bb_pct:      pd.Series = field(default_factory=pd.Series)   # %B

    # ── 시그널 ────────────────────────────────────────
    signals:     list[dict] = field(default_factory=list)

    @property
    def latest(self) -> dict:
        """마지막 행 기준 주요 지표 요약 dict"""
        def _last(s: pd.Series):
            return round(float(s.iloc[-1]), 2) if not s.empty and pd.notna(s.iloc[-1]) else None

        return {
            "종가":       _last(self.close),
            "RSI":        _last(self.rsi),
            "MACD":       _last(self.macd),
            "MACD시그널": _last(self.macd_signal),
            "MACD히스토": _last(self.macd_hist),
            "BB상단":     _last(self.bb_upper),
            "BB중단":     _last(self.bb_mid),
            "BB하단":     _last(self.bb_lower),
            "BB%B":       _last(self.bb_pct),
            "MA5":        _last(self.ma5),
            "MA20":       _last(self.ma20),
            "MA60":       _last(self.ma60),
        }


# ════════════════════════════════════════════════════════
# 핵심 계산 함수 — 3단 폴백
# ════════════════════════════════════════════════════════

# ── RSI ──────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI 계산. TA-Lib → pandas_ta → numpy 순 폴백."""
    if len(close) < period + 1:
        return pd.Series(index=close.index, dtype=float)

    if _BACKEND == "talib":
        import talib
        return pd.Series(talib.RSI(close.values, timeperiod=period),
                         index=close.index)

    if _BACKEND == "pandas_ta":
        import pandas_ta as pta
        result = pta.rsi(close, length=period)
        return result if result is not None else _rsi_numpy(close, period)

    return _rsi_numpy(close, period)


def _rsi_numpy(close: pd.Series, period: int = 14) -> pd.Series:
    """
    순수 numpy RSI (Wilder's smoothing).
    pandas Series 대신 numpy 배열로 계산해 iloc 변경 안정성 문제 회피.
    """
    prices = close.values.astype(float)
    n      = len(prices)
    rsi_arr = np.full(n, np.nan)

    if n <= period:
        return pd.Series(rsi_arr, index=close.index)

    delta = np.diff(prices)                    # 길이 n-1
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)

    # 초기 평균: 첫 period 개 변화량의 단순평균
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()

    if avg_loss == 0:
        rsi_arr[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi_arr[period] = 100 - (100 / (1 + rs))

    # Wilder's smoothing — 이후 구간
    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        if avg_loss == 0:
            rsi_arr[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_arr[i + 1] = 100 - (100 / (1 + rs))

    return pd.Series(rsi_arr, index=close.index)


# ── MACD ────────────────────────────────────────────

def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD 계산.
    반환: (macd_line, signal_line, histogram)
    """
    if len(close) < slow + signal:
        empty = pd.Series(index=close.index, dtype=float)
        return empty, empty, empty

    if _BACKEND == "talib":
        import talib
        macd, sig, hist = talib.MACD(close.values, fastperiod=fast,
                                      slowperiod=slow, signalperiod=signal)
        idx = close.index
        return (pd.Series(macd, index=idx),
                pd.Series(sig,  index=idx),
                pd.Series(hist, index=idx))

    if _BACKEND == "pandas_ta":
        import pandas_ta as pta
        result = pta.macd(close, fast=fast, slow=slow, signal=signal)
        if result is not None and len(result.columns) >= 3:
            cols = result.columns.tolist()
            # pandas_ta 컬럼명: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
            macd_col = [c for c in cols if c.startswith("MACD_")][0]
            hist_col = [c for c in cols if c.startswith("MACDh_")][0]
            sig_col  = [c for c in cols if c.startswith("MACDs_")][0]
            return result[macd_col], result[sig_col], result[hist_col]

    return _macd_numpy(close, fast, slow, signal)


def _macd_numpy(
    close: pd.Series,
    fast: int = 12, slow: int = 26, signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """순수 numpy MACD"""
    ema_fast = close.ewm(span=fast,   adjust=False).mean()
    ema_slow = close.ewm(span=slow,   adjust=False).mean()
    macd     = ema_fast - ema_slow
    sig      = macd.ewm(span=signal,  adjust=False).mean()
    hist     = macd - sig
    return macd, sig, hist


# ── 볼린저밴드 ───────────────────────────────────────

def calc_bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_mult: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    볼린저밴드 계산.
    반환: (upper, mid, lower, pct_b)
    pct_b = (close - lower) / (upper - lower)  — 0~1 범위
    """
    if len(close) < period:
        empty = pd.Series(index=close.index, dtype=float)
        return empty, empty, empty, empty

    if _BACKEND == "talib":
        import talib
        upper, mid, lower = talib.BBANDS(close.values, timeperiod=period,
                                          nbdevup=std_mult, nbdevdn=std_mult)
        idx   = close.index
        upper = pd.Series(upper, index=idx)
        mid   = pd.Series(mid,   index=idx)
        lower = pd.Series(lower, index=idx)
        pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
        return upper, mid, lower, pct_b

    if _BACKEND == "pandas_ta":
        import pandas_ta as pta
        result = pta.bbands(close, length=period, std=std_mult)
        if result is not None:
            cols  = result.columns.tolist()
            u_col = [c for c in cols if "BBU" in c][0]
            m_col = [c for c in cols if "BBM" in c][0]
            l_col = [c for c in cols if "BBL" in c][0]
            upper, mid, lower = result[u_col], result[m_col], result[l_col]
            pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
            return upper, mid, lower, pct_b

    return _bollinger_numpy(close, period, std_mult)


def _bollinger_numpy(
    close: pd.Series, period: int = 20, std_mult: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """순수 numpy 볼린저밴드"""
    mid   = close.rolling(window=period).mean()
    std   = close.rolling(window=period).std(ddof=0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return upper, mid, lower, pct_b


# ── 이동평균 ─────────────────────────────────────────

def calc_ma(close: pd.Series, period: int) -> pd.Series:
    """단순 이동평균 (SMA)"""
    return close.rolling(window=period, min_periods=1).mean()


# ════════════════════════════════════════════════════════
# 시그널 생성
# ════════════════════════════════════════════════════════

def _generate_signals(result: TAResult) -> list[dict]:
    """
    주요 기술적 시그널 탐지.
    각 시그널: {"type": "BUY"|"SELL"|"CAUTION", "indicator": str, "message": str}
    """
    signals = []
    latest  = result.latest

    # ── RSI 시그널 ────────────────────────────────
    rsi = latest.get("RSI")
    if rsi is not None:
        if rsi <= 30:
            signals.append({
                "type": "BUY", "indicator": "RSI",
                "message": f"RSI {rsi:.1f} — 과매도 구간 (≤30)",
            })
        elif rsi >= 70:
            signals.append({
                "type": "SELL", "indicator": "RSI",
                "message": f"RSI {rsi:.1f} — 과매수 구간 (≥70)",
            })
        elif 40 <= rsi <= 60:
            signals.append({
                "type": "CAUTION", "indicator": "RSI",
                "message": f"RSI {rsi:.1f} — 중립 구간",
            })

    # ── MACD 시그널 (골든크로스 / 데드크로스) ────
    macd = result.macd
    sig  = result.macd_signal
    if len(macd) >= 2 and len(sig) >= 2:
        prev_above = float(macd.iloc[-2]) > float(sig.iloc[-2])
        curr_above = float(macd.iloc[-1]) > float(sig.iloc[-1])
        if not prev_above and curr_above:
            signals.append({
                "type": "BUY", "indicator": "MACD",
                "message": "MACD 골든크로스 — 상승 전환 신호",
            })
        elif prev_above and not curr_above:
            signals.append({
                "type": "SELL", "indicator": "MACD",
                "message": "MACD 데드크로스 — 하락 전환 신호",
            })

    # ── 볼린저밴드 시그널 ─────────────────────────
    bb_pct = latest.get("BB%B")
    if bb_pct is not None:
        if bb_pct <= 0:
            signals.append({
                "type": "BUY", "indicator": "BB",
                "message": f"볼린저밴드 하단 이탈 (%B={bb_pct:.2f}) — 반등 주의",
            })
        elif bb_pct >= 1:
            signals.append({
                "type": "SELL", "indicator": "BB",
                "message": f"볼린저밴드 상단 이탈 (%B={bb_pct:.2f}) — 과열 주의",
            })

    # ── 이동평균 정배열 / 역배열 ─────────────────
    ma5  = latest.get("MA5")
    ma20 = latest.get("MA20")
    ma60 = latest.get("MA60")
    if all(v is not None for v in [ma5, ma20, ma60]):
        if ma5 > ma20 > ma60:
            signals.append({
                "type": "BUY", "indicator": "MA",
                "message": "이동평균 정배열 (MA5 > MA20 > MA60)",
            })
        elif ma5 < ma20 < ma60:
            signals.append({
                "type": "SELL", "indicator": "MA",
                "message": "이동평균 역배열 (MA5 < MA20 < MA60)",
            })

    return signals


# ════════════════════════════════════════════════════════
# TechnicalAnalysis — 메인 클래스
# ════════════════════════════════════════════════════════

class TechnicalAnalysis:
    """
    종목 코드 또는 DataFrame 을 받아 모든 기술적 지표를 계산하는 클래스.

    사용 예 A — SQLite 캐시에서 자동 로드:
        ta = TechnicalAnalysis.from_cache("005930")
        result = ta.run_all()

    사용 예 B — DataFrame 직접 전달:
        ta = TechnicalAnalysis(df)
        result = ta.run_all()

    사용 예 C — Streamlit 차트 렌더링:
        ta = TechnicalAnalysis.from_cache("005930")
        ta.render_chart("삼성전자")
    """

    def __init__(self, df: pd.DataFrame):
        """
        df 컬럼: Date | 시가 | 고가 | 저가 | 종가 | 거래량
        (data_store.load_ohlcv_from_cache 출력과 동일)
        """
        self.df = df.copy()
        # 컬럼 정규화 — 영문 컬럼명도 수용
        col_map = {
            "Open": "시가", "High": "고가", "Low": "저가",
            "Close": "종가", "Volume": "거래량",
        }
        self.df = self.df.rename(columns=col_map)

        if "Date" in self.df.columns:
            self.df["Date"] = pd.to_datetime(self.df["Date"])
            self.df = self.df.set_index("Date").sort_index()

        self.close  = self.df["종가"].astype(float)
        self.high   = self.df["고가"].astype(float)
        self.low    = self.df["저가"].astype(float)
        self.volume = self.df["거래량"].astype(float)

    @classmethod
    def from_cache(
        cls,
        code: str,
        days: int = 200,
    ) -> "TechnicalAnalysis":
        """
        SQLite 캐시에서 OHLCV 를 읽어 TechnicalAnalysis 생성.
        캐시 없으면 pykrx 에서 즉시 수집 (data_store.get_ohlcv 활용).
        """
        try:
            from data_store import get_ohlcv
            from_date = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
            df = get_ohlcv(code, from_date)
            if df.empty:
                raise ValueError(f"{code}: OHLCV 데이터 없음")
            return cls(df)
        except Exception as e:
            logger.error(f"from_cache({code}): {e}")
            return cls(pd.DataFrame(columns=["Date","시가","고가","저가","종가","거래량"]))

    # ── 개별 지표 계산 ──────────────────────────────

    def rsi(self, period: int = 14) -> pd.Series:
        return calc_rsi(self.close, period)

    def macd(
        self, fast: int = 12, slow: int = 26, signal: int = 9,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        return calc_macd(self.close, fast, slow, signal)

    def bollinger_bands(
        self, period: int = 20, std_mult: float = 2.0,
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        return calc_bollinger_bands(self.close, period, std_mult)

    def moving_averages(self) -> dict[str, pd.Series]:
        return {
            "MA5":   calc_ma(self.close, 5),
            "MA20":  calc_ma(self.close, 20),
            "MA60":  calc_ma(self.close, 60),
            "MA120": calc_ma(self.close, 120),
        }

    # ── 전체 실행 ───────────────────────────────────

    def run_all(
        self,
        rsi_period:    int   = 14,
        macd_fast:     int   = 12,
        macd_slow:     int   = 26,
        macd_signal:   int   = 9,
        bb_period:     int   = 20,
        bb_std:        float = 2.0,
    ) -> TAResult:
        """모든 지표를 한 번에 계산해 TAResult 반환"""
        result = TAResult(close=self.close, volume=self.volume)

        # 이동평균
        mas = self.moving_averages()
        result.ma5,   result.ma20  = mas["MA5"],  mas["MA20"]
        result.ma60,  result.ma120 = mas["MA60"], mas["MA120"]

        # RSI
        result.rsi = self.rsi(rsi_period)

        # MACD
        result.macd, result.macd_signal, result.macd_hist = \
            self.macd(macd_fast, macd_slow, macd_signal)

        # 볼린저밴드
        result.bb_upper, result.bb_mid, result.bb_lower, result.bb_pct = \
            self.bollinger_bands(bb_period, bb_std)

        # 시그널 탐지
        result.signals = _generate_signals(result)

        return result

    # ════════════════════════════════════════════════
    # Streamlit 차트 렌더링
    # ════════════════════════════════════════════════

    def render_chart(
        self,
        stock_name: str = "",
        result: Optional[TAResult] = None,
        show_volume: bool = True,
    ) -> None:
        """
        Streamlit 에서 바로 호출하는 차트 렌더링.
        캔들 + 볼린저밴드 + RSI + MACD 를 4개 서브플롯으로 표시.

        ui_components.py _render_stock_detail() 내부에서 호출 예:
            from analysis_engine import TechnicalAnalysis
            ta = TechnicalAnalysis.from_cache(STOCK_CODES.get(sel, ""))
            ta.render_chart(sel)
        """
        try:
            import streamlit as st
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
        except ImportError:
            logger.error("streamlit / plotly 없음")
            return

        if result is None:
            result = self.run_all()

        if self.close.empty:
            st.info(f"📊 {stock_name} — OHLCV 데이터 없음 (캐시를 채운 후 다시 시도하세요)")
            return

        # ── 서브플롯 구성 ─────────────────────────
        row_heights = [0.45, 0.15, 0.20, 0.20] if show_volume else [0.50, 0.20, 0.30]
        n_rows = 4 if show_volume else 3
        subplot_titles = (
            ["캔들 + 볼린저밴드 + 이동평균", "거래량", "RSI (14)", "MACD (12/26/9)"]
            if show_volume else
            ["캔들 + 볼린저밴드 + 이동평균", "RSI (14)", "MACD (12/26/9)"]
        )

        fig = make_subplots(
            rows=n_rows, cols=1,
            shared_xaxes=True,
            row_heights=row_heights,
            vertical_spacing=0.03,
            subplot_titles=subplot_titles,
        )

        dates = self.df.index

        # ── 1행: 캔들 ─────────────────────────────
        fig.add_trace(go.Candlestick(
            x=dates,
            open=self.df["시가"], high=self.df["고가"],
            low=self.df["저가"],  close=self.close,
            name="캔들",
            increasing_line_color="#FF4B4B",
            decreasing_line_color="#87CEEB",
            showlegend=False,
        ), row=1, col=1)

        # 볼린저밴드
        if not result.bb_upper.empty:
            fig.add_trace(go.Scatter(
                x=dates, y=result.bb_upper,
                name="BB상단", line=dict(color="rgba(255,165,0,0.6)", width=1, dash="dot"),
                showlegend=True,
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=dates, y=result.bb_lower,
                name="BB하단", line=dict(color="rgba(255,165,0,0.6)", width=1, dash="dot"),
                fill="tonexty", fillcolor="rgba(255,165,0,0.05)",
                showlegend=True,
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=dates, y=result.bb_mid,
                name="MA20", line=dict(color="rgba(255,215,0,0.8)", width=1),
                showlegend=True,
            ), row=1, col=1)

        # 이동평균
        ma_colors = {"MA5": "#87CEEB", "MA60": "#FF9999", "MA120": "#90EE90"}
        for label, series, color in [
            ("MA5",  result.ma5,  ma_colors["MA5"]),
            ("MA60", result.ma60, ma_colors["MA60"]),
        ]:
            if not series.empty:
                fig.add_trace(go.Scatter(
                    x=dates, y=series, name=label,
                    line=dict(color=color, width=1),
                    showlegend=True,
                ), row=1, col=1)

        # ── 2행: 거래량 ───────────────────────────
        current_row = 2
        if show_volume:
            vol_colors = [
                "#FF4B4B" if float(self.df["종가"].iloc[i]) >= float(self.df["시가"].iloc[i])
                else "#87CEEB"
                for i in range(len(dates))
            ]
            fig.add_trace(go.Bar(
                x=dates, y=self.volume,
                name="거래량", marker_color=vol_colors,
                showlegend=False,
            ), row=2, col=1)
            current_row = 3

        # ── RSI 행 ────────────────────────────────
        if not result.rsi.empty:
            fig.add_trace(go.Scatter(
                x=dates, y=result.rsi,
                name="RSI", line=dict(color="#9B59B6", width=1.5),
                showlegend=False,
            ), row=current_row, col=1)
            # 과매수/과매도 기준선
            for level, color in [(70, "rgba(255,75,75,0.4)"), (30, "rgba(135,206,235,0.4)")]:
                fig.add_hline(y=level, line_dash="dash", line_color=color,
                              row=current_row, col=1)

        # ── MACD 행 ───────────────────────────────
        macd_row = current_row + 1
        if not result.macd.empty:
            fig.add_trace(go.Scatter(
                x=dates, y=result.macd,
                name="MACD", line=dict(color="#87CEEB", width=1.5),
                showlegend=False,
            ), row=macd_row, col=1)
            fig.add_trace(go.Scatter(
                x=dates, y=result.macd_signal,
                name="시그널", line=dict(color="#FFD700", width=1, dash="dot"),
                showlegend=False,
            ), row=macd_row, col=1)
            hist_colors = [
                "#FF4B4B" if v >= 0 else "#87CEEB"
                for v in result.macd_hist.fillna(0)
            ]
            fig.add_trace(go.Bar(
                x=dates, y=result.macd_hist,
                name="히스토그램", marker_color=hist_colors,
                showlegend=False,
            ), row=macd_row, col=1)
            fig.add_hline(y=0, line_dash="solid",
                          line_color="rgba(255,255,255,0.2)",
                          row=macd_row, col=1)

        # ── 레이아웃 ──────────────────────────────
        title = f"📊 {stock_name} 기술적 분석" if stock_name else "📊 기술적 분석"
        fig.update_layout(
            title=dict(text=title, x=0.02, font=dict(size=14)),
            height=700,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,0.02)",
            font_color="white",
            xaxis_rangeslider_visible=False,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02,
                xanchor="right", x=1, font=dict(size=11),
            ),
            margin=dict(t=80, b=20, l=50, r=20),
        )
        fig.update_xaxes(
            showgrid=True, gridcolor="rgba(255,255,255,0.05)",
            showspikes=True, spikecolor="rgba(255,255,255,0.3)",
        )
        fig.update_yaxes(
            showgrid=True, gridcolor="rgba(255,255,255,0.05)",
        )

        st.plotly_chart(fig, use_container_width=True)

        # ── 시그널 카드 ───────────────────────────
        self._render_signals(result.signals)

        # ── 지표 요약 메트릭 ──────────────────────
        self._render_metrics(result)

    def _render_signals(self, signals: list[dict]) -> None:
        """시그널을 컬러 배지로 렌더링"""
        try:
            import streamlit as st
        except ImportError:
            return
        if not signals:
            return

        st.markdown("##### 🔔 기술적 시그널")
        cols = st.columns(min(len(signals), 3))
        for i, sig in enumerate(signals):
            color = {"BUY": "#FF4B4B", "SELL": "#87CEEB", "CAUTION": "#FFD700"}.get(
                sig["type"], "#aaa"
            )
            label = {"BUY": "매수", "SELL": "매도", "CAUTION": "주의"}.get(sig["type"], "")
            with cols[i % 3]:
                st.markdown(
                    f"<div style='padding:8px 12px; border-radius:8px; "
                    f"border-left:4px solid {color}; "
                    f"background:rgba(255,255,255,0.03); margin-bottom:8px;'>"
                    f"<span style='color:{color}; font-size:0.8rem; font-weight:bold;'>"
                    f"[{sig['indicator']}] {label}</span><br>"
                    f"<span style='font-size:0.85rem;'>{sig['message']}</span></div>",
                    unsafe_allow_html=True,
                )

    def _render_metrics(self, result: TAResult) -> None:
        """지표 수치를 4열 메트릭으로 렌더링"""
        try:
            import streamlit as st
        except ImportError:
            return

        latest = result.latest
        st.markdown("##### 📐 지표 수치 (최신일 기준)")
        c1, c2, c3, c4 = st.columns(4)

        rsi = latest.get("RSI")
        rsi_str = f"{rsi:.1f}" if rsi else "-"
        rsi_delta = ("과매수" if rsi and rsi >= 70 else
                     "과매도" if rsi and rsi <= 30 else "중립") if rsi else None
        c1.metric("RSI (14)", rsi_str, delta=rsi_delta)

        macd_v = latest.get("MACD")
        sig_v  = latest.get("MACD시그널")
        c2.metric("MACD", f"{macd_v:.2f}" if macd_v else "-",
                  delta=f"시그널 {sig_v:.2f}" if sig_v else None)

        bb_pct = latest.get("BB%B")
        c3.metric("BB %B", f"{bb_pct:.2f}" if bb_pct else "-",
                  delta="상단 이탈" if bb_pct and bb_pct >= 1 else
                        "하단 이탈" if bb_pct and bb_pct <= 0 else None)

        ma5_v  = latest.get("MA5")
        ma20_v = latest.get("MA20")
        c4.metric("MA5 / MA20",
                  f"{ma5_v:,.0f}" if ma5_v else "-",
                  delta=f"MA20 {ma20_v:,.0f}" if ma20_v else None)
