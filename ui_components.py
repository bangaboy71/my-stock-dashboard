"""
ui_components.py — 가족 자산 관제탑 UI 컴포넌트
모든 st.xxx 렌더링 로직을 함수 단위로 캡슐화합니다.
app.py는 이 모듈의 함수를 호출하기만 하면 됩니다.
"""
from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from config import (
    GLOBAL_RENAME_MAP, GLOBAL_DISPLAY_COLS, RESEARCH_DATA,
    DIVIDEND_SCHEDULE, DIVIDEND_TAX_RATE,
    STOP_LOSS_PCT, TRAILING_PCT,
)
from data_engine import (
    get_cashflow_grade, find_matching_col,
    get_stock_news, get_dividend_calendar, load_dividend_actual,
    get_memo, save_memo,
    get_csv_bytes, get_excel_bytes,
)


# ════════════════════════════════════════════════════════
# 테이블 헬퍼
# ════════════════════════════════════════════════════════

def col_width(series: pd.Series) -> str:
    """값 최대 길이 기준 small / medium / large 반환"""
    try:
        max_len = series.astype(str).str.len().max()
    except Exception:
        max_len = 8
    if max_len <= 7:   return "small"
    if max_len <= 14:  return "medium"
    return "large"


def style_pnl(df: pd.DataFrame, cols: list[str]):
    """양수 빨강·음수 파랑 색상 Styler 반환"""
    def _color(val):
        if isinstance(val, (int, float)):
            if val > 0: return "color: #FF4B4B; font-weight:600"
            if val < 0: return "color: #87CEEB; font-weight:600"
        return ""
    styler = df.style
    try:
        styler = styler.map(_color, subset=[c for c in cols if c in df.columns])
    except AttributeError:
        styler = styler.applymap(_color, subset=[c for c in cols if c in df.columns])
    return styler


def hex_to_rgba(hex_color: str, alpha: float = 0.08) -> str:
    """#RRGGBB → 'rgba(R,G,B,A)' 변환 (plotly fillcolor 전용)"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ════════════════════════════════════════════════════════
# HUD — 시장 지수 상단 바
# ════════════════════════════════════════════════════════

def render_market_hud(m_status: dict):
    """KOSPI·KOSDAQ·USD/KRW·미국 10년물 국채금리 4칸 HUD 렌더링"""
    titles = ["KOSPI", "KOSDAQ", "USD/KRW", "🇺🇸 US10Y"]
    keys   = ["KOSPI", "KOSDAQ", "USD/KRW", "US10Y"]
    cols   = st.columns(4)
    for i, col in enumerate(cols):
        with col:
            d         = m_status[keys[i]]
            border    = f"{d['color']}44"
            txt_color = d["color"]
            # US10Y: 숫자값에 % 단위 표시
            val_display = (
                f"{d['val']}%" if keys[i] == "US10Y" and d["val"] != "-"
                else d["val"]
            )
            st.markdown(f"""
                <div style='text-align:center; padding:15px; border-radius:12px;
                            background:rgba(255,255,255,0.03); border:1px solid {border};'>
                    <div style='color:#aaa; font-size:0.85rem; font-weight:bold; margin-bottom:5px;'>
                        {titles[i]}
                    </div>
                    <div style='color:{d["color"]}; font-size:1.8rem; font-weight:bold; line-height:1.2;'>
                        {val_display}
                    </div>
                    <div style='color:{txt_color}; font-size:1.0rem; font-weight:500; margin-top:5px;'>
                        {d["pct"]}
                    </div>
                </div>
            """, unsafe_allow_html=True)
    st.write("")


# ════════════════════════════════════════════════════════
# 총괄 탭 (tabs[0])
# ════════════════════════════════════════════════════════

def render_summary_tab(full_df: pd.DataFrame, history_df: pd.DataFrame):
    """총괄 현황 탭 전체 렌더링"""

    # 1. 패밀리 메트릭
    t_eval      = full_df["평가금액"].sum()
    t_buy       = full_df["매입금액"].sum()
    t_prev_eval = (full_df["수량"] * full_df["전일종가"]).sum()
    t_chg_amt   = t_eval - t_prev_eval
    t_chg_pct   = (t_chg_amt / t_prev_eval * 100) if t_prev_eval != 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액",   f"{t_eval:,.0f}원",
              delta=f"{t_chg_amt:+,.0f}원 ({t_chg_pct:+.2f}%)")
    m2.metric("총 투자 원금",     f"{t_buy:,.0f}원")
    m3.metric("총 누적 손익",     f"{t_eval - t_buy:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy - 1)*100:+.2f}%",
              delta=f"{t_chg_pct:+.2f}%p")
    st.divider()

    # 2. 계좌별 요약 테이블
    sum_acc = full_df.groupby("계좌명").agg({
        "매입금액": "sum", "평가금액": "sum",
        "손익": "sum",    "전일대비손익": "sum",
    }).reset_index()
    sum_acc["전일평가액"]    = sum_acc["평가금액"] - sum_acc["전일대비손익"]
    sum_acc["전일대비변동율"] = (
        sum_acc["전일대비손익"] /
        sum_acc["전일평가액"].replace(0, float("nan")) * 100
    ).fillna(0)
    sum_acc["누적수익률"] = (
        sum_acc["손익"] / sum_acc["매입금액"].replace(0, float("nan")) * 100
    ).fillna(0)

    sum_acc_plot = sum_acc.rename(columns=GLOBAL_RENAME_MAP)
    sum_acc_cols = ["계좌명", "매입금액", "평가금액", "손익",
                    "전일대비(원)", "전일대비(%)", "누적수익률"]
    ret_abs = max(
        abs(float(sum_acc["누적수익률"].min())),
        abs(float(sum_acc["누적수익률"].max())), 1.0
    )
    tbl_acc = style_pnl(
        sum_acc_plot[sum_acc_cols],
        ["손익", "전일대비(원)", "전일대비(%)", "누적수익률"]
    ).format({
        "매입금액":    "{:,.0f}", "평가금액":    "{:,.0f}",
        "손익":        "{:+,.0f}", "전일대비(원)": "{:+,.0f}",
        "전일대비(%)": "{:+.2f}%", "누적수익률":  "{:+.2f}%",
    })
    st.dataframe(tbl_acc, hide_index=True, use_container_width=True,
        column_config={
            "계좌명":     st.column_config.TextColumn("계좌명",   width="small"),
            "매입금액":   st.column_config.NumberColumn("매입금액",  width="medium"),
            "평가금액":   st.column_config.NumberColumn("평가금액",  width="medium"),
            "손익":       st.column_config.NumberColumn("손익",      width="medium"),
            "전일대비(원)": st.column_config.NumberColumn("전일대비(원)", width="medium"),
            "전일대비(%)": st.column_config.NumberColumn("전일대비(%)", width="small"),
            "누적수익률": st.column_config.ProgressColumn(
                "누적수익률", help="매입 대비 누적 손익률",
                format="%.2f%%", min_value=-ret_abs, max_value=ret_abs, width="medium"),
        })
    st.divider()

    # 3. 배당 HUD
    total_div          = full_df["예상배당금"].sum()
    monthly_after_tax  = (total_div * (1 - DIVIDEND_TAX_RATE)) / 12
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("연간 예상 총 배당금", f"{total_div:,.0f}원")
    d2.metric("세후 월 평균 수령액", f"{monthly_after_tax:,.0f}원")
    d3.metric("포트 배당수익률",
              f"{(total_div/t_eval*100):.2f}%" if t_eval != 0 else "0.00%")
    d4.metric("통합 현금흐름 등급", get_cashflow_grade(monthly_after_tax))
    st.divider()

    # 4. 차트 (성장 추이 + 월별 배당)
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        with st.container(border=True):
            _render_growth_chart(history_df, sum_acc)
    with chart_col2:
        with st.container(border=True):
            _render_dividend_bar(full_df)

    # 5. 레이더 차트
    st.divider()
    with st.container(border=True):
        _render_radar_chart(full_df, sum_acc)


def _render_growth_chart(history_df: pd.DataFrame, sum_acc: pd.DataFrame):
    if history_df.empty:
        st.info("성과 추이 데이터를 분석 중입니다...")
        return
    fig = go.Figure()
    h_dt = history_df["Date"].dt.date.astype(str)
    fig.add_trace(go.Scatter(
        x=h_dt, y=history_df["KOSPI_Relative"],
        name="KOSPI", line=dict(dash="dash", color="rgba(255,255,255,0.3)")
    ))
    for acc in sum_acc["계좌명"].unique():
        col = find_matching_col(history_df, acc)
        if col:
            fig.add_trace(go.Scatter(x=h_dt, y=history_df[col], name=acc))
    fig.update_layout(
        title=dict(text="📈 자산 성장 추이 (KOSPI 대비)", x=0.02, y=0.9),
        height=380, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.02)", font_color="white",
        legend=dict(orientation="h", yanchor="bottom", y=-0.4, xanchor="center", x=0.5),
        margin=dict(t=80, b=100, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def _extract_months(schedule: list) -> list[int]:
    """DIVIDEND_SCHEDULE 값에서 월 번호만 추출 (정수·튜플 모두 지원)"""
    months = []
    for entry in schedule:
        if isinstance(entry, (list, tuple)) and len(entry) >= 1:
            months.append(int(entry[0]))
        else:
            months.append(int(entry))
    return months


def _render_dividend_bar(full_df: pd.DataFrame):
    monthly = {m: 0 for m in range(1, 13)}
    for _, row in full_df.iterrows():
        sched  = DIVIDEND_SCHEDULE.get(row["종목명"], [(4, 0)])
        months = _extract_months(sched)
        if row["예상배당금"] > 0:
            for m in months:
                monthly[m] += row["예상배당금"] / len(months)
    vals   = [monthly[m] for m in range(1, 13)]
    colors = ["#FFD700" if v == max(vals) and v > 0
              else "rgba(135,206,235,0.2)" for v in vals]
    fig = go.Figure(go.Bar(
        x=[f"{m}월" for m in range(1, 13)], y=vals,
        marker_color=colors,
        text=[f"{v/10000:.0f}만" if v > 0 else "" for v in vals],
        textposition="outside",
    ))
    fig.update_layout(
        title=dict(text="📅 월별 예상 배당 입금액", x=0.02, y=0.9),
        height=380, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.02)", font_color="white",
        margin=dict(t=80, b=40, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_radar_chart(full_df: pd.DataFrame, sum_acc: pd.DataFrame):
    st.markdown("#### 🕸️ 계좌별 다차원 성과 비교")
    AXES = ["누적수익률", "배당수익률", "전일대비(%)", "목표달성률", "자산집중도"]
    rows = []
    for _, row in sum_acc.iterrows():
        acc    = row["계좌명"]
        acc_df = full_df[full_df["계좌명"] == acc]
        a_eval = row["평가금액"]
        valid  = acc_df[(acc_df["목표가"] > 0) & (acc_df["현재가"] > 0)]
        w      = (acc_df["평가금액"] / a_eval) if a_eval > 0 else pd.Series([1.0])
        rows.append({
            "계좌명":    acc,
            "누적수익률": row["누적수익률"],
            "배당수익률": (acc_df["예상배당금"].sum() / a_eval * 100) if a_eval > 0 else 0,
            "전일대비(%)": row["전일대비변동율"],
            "목표달성률": (valid["현재가"] / valid["목표가"] * 100).mean() if not valid.empty else 0,
            "자산집중도":  (1 - (w ** 2).sum()) * 100,
        })
    radar_df   = pd.DataFrame(rows)
    radar_norm = radar_df.copy()
    for col in AXES:
        mn, mx = radar_df[col].min(), radar_df[col].max()
        radar_norm[col] = (radar_df[col] - mn) / (mx - mn) * 100 if mx - mn > 0 else 50

    COLORS = ["#87CEEB", "#FFD700", "#FF4B4B", "#7CFC00"]
    fig = go.Figure()
    for i, row in radar_norm.iterrows():
        acc   = row["계좌명"]; raw = radar_df.loc[i]; color = COLORS[i % len(COLORS)]
        r_v   = [row[a] for a in AXES] + [row[AXES[0]]]
        axes  = AXES + [AXES[0]]
        fig.add_trace(go.Scatterpolar(
            r=r_v, theta=axes, fill="toself",
            fillcolor=hex_to_rgba(color, 0.08),
            line=dict(color=color, width=2), name=acc,
            hovertemplate=(
                f"<b>{acc}</b><br>"
                f"누적수익률: {raw['누적수익률']:+.2f}%<br>"
                f"배당수익률: {raw['배당수익률']:.2f}%<br>"
                f"전일대비: {raw['전일대비(%)']:+.2f}%<br>"
                f"목표달성률: {raw['목표달성률']:.1f}%<br>"
                f"분산도: {raw['자산집중도']:.1f}<extra></extra>"
            ),
        ))
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(255,255,255,0.02)",
            radialaxis=dict(visible=True, range=[0, 100],
                tickfont=dict(size=10, color="rgba(255,255,255,0.4)"),
                gridcolor="rgba(255,255,255,0.08)", linecolor="rgba(255,255,255,0.08)"),
            angularaxis=dict(
                tickfont=dict(size=12, color="rgba(255,255,255,0.75)"),
                gridcolor="rgba(255,255,255,0.08)", linecolor="rgba(255,255,255,0.15)"),
        ),
        paper_bgcolor="rgba(0,0,0,0)", font_color="white", height=420,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
        margin=dict(t=40, b=60, l=60, r=60),
    )
    st.plotly_chart(fig, use_container_width=True)

    # 수치 보조 테이블
    div_max = float(radar_df["배당수익률"].max()) * 1.2 or 10
    st.dataframe(radar_df, hide_index=True, use_container_width=True,
        column_config={
            "계좌명":    st.column_config.TextColumn("계좌명", width="small"),
            "누적수익률": st.column_config.NumberColumn("누적수익률", format="%+.2f%%", width="small"),
            "배당수익률": st.column_config.ProgressColumn("배당수익률",
                help="연간 예상 배당 / 평가금액", format="%.2f%%",
                min_value=0, max_value=div_max, width="medium"),
            "전일대비(%)": st.column_config.NumberColumn("전일대비(%)", format="%+.2f%%", width="small"),
            "목표달성률":  st.column_config.ProgressColumn("목표달성률",
                help="현재가 / 목표가 평균", format="%.1f%%",
                min_value=0, max_value=100, width="medium"),
            "자산집중도":  st.column_config.NumberColumn("분산도", format="%.1f", width="small"),
        })


# ════════════════════════════════════════════════════════
# 계좌별 탭 — AccountTabRenderer 클래스
# ════════════════════════════════════════════════════════

class AccountTabRenderer:
    """
    계좌별 탭의 모든 렌더링 책임을 캡슐화한 클래스.

    설계 원칙
    ─────────
    • __init__ 에서 공유 데이터를 인스턴스 변수로 저장
      → 각 메서드에서 인자를 반복 전달할 필요 없음
    • render() 한 번 호출로 탭 전체를 순서대로 그림
    • 각 섹션은 private 메서드(_method)로 분리
      → 독립 테스트·재사용 가능
    • 선택된 종목(sel)은 render() 내부에서 결정해
      state를 외부로 노출하지 않음

    사용 예
    ───────
    AccountTabRenderer(
        acc_name="서은투자", tab_obj=tabs[1],
        full_df=full_df, history_df=history_df,
        memo_df=memo_df, conn=conn, now_kst=now_kst,
    ).render()
    """

    # ── 클래스 상수 (색상 팔레트) ──────────────────────────
    COLOR_POS   = "#FF4B4B"
    COLOR_NEG   = "#87CEEB"
    COLOR_GOLD  = "#FFD700"
    COLOR_GREEN = "#00FF00"

    def __init__(
        self,
        acc_name: str,
        tab_obj,
        full_df: pd.DataFrame,
        history_df: pd.DataFrame,
        memo_df: pd.DataFrame,
        conn,
        now_kst,
    ):
        self.acc_name   = acc_name
        self.tab_obj    = tab_obj
        self.full_df    = full_df
        self.history_df = history_df
        self.memo_df    = memo_df
        self.conn       = conn
        self.now_kst    = now_kst

        # 이 계좌에 해당하는 종목 서브셋 (render() 전 준비)
        self.sub_df = full_df[full_df["계좌명"] == acc_name].copy()

    # ── 공개 진입점 ────────────────────────────────────────

    def render(self):
        """탭 전체를 순서대로 렌더링하는 유일한 공개 메서드"""
        with self.tab_obj:
            if self.sub_df.empty:
                st.warning(f"{self.acc_name} 데이터가 발견되지 않았습니다.")
                return

            self._render_metrics()
            self._render_stock_table()
            st.divider()
            self._render_cashflow()
            st.divider()
            self._render_charts()
            st.divider()
            sel = self._render_stock_selector()
            self._render_stock_detail(sel)
            self._render_news(sel)
            self._render_memo(sel)

    # ── 섹션 1: 계좌 요약 메트릭 ──────────────────────────

    def _render_metrics(self):
        a_buy  = self.sub_df["매입금액"].sum()
        a_eval = self.sub_df["평가금액"].sum()
        a_diff = self.sub_df["전일대비손익"].sum()
        a_pct  = (a_diff / (a_eval - a_diff) * 100) if (a_eval - a_diff) != 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("계좌 평가액", f"{a_eval:,.0f}원",
                  delta=f"{a_diff:+,.0f}원 ({a_pct:+.2f}%)")
        c2.metric("계좌 매입액", f"{a_buy:,.0f}원")
        c3.metric("계좌 손익",   f"{a_eval - a_buy:+,.0f}원")
        c4.metric("계좌 수익률", f"{(a_eval/a_buy - 1)*100:+.2f}%",
                  delta=f"{a_pct:+.2f}%p")

    # ── 섹션 2: 보유 종목 테이블 ──────────────────────────

    def _render_stock_table(self):
        plot_df   = self.sub_df.rename(columns=GLOBAL_RENAME_MAP).copy()
        s_ret_abs = max(
            abs(float(plot_df["누적수익률"].min())),
            abs(float(plot_df["누적수익률"].max())), 1.0
        )
        up_max = (max(float(plot_df["목표대비상승여력"].max()), 1.0)
                  if "목표대비상승여력" in plot_df.columns else 30)

        disp   = [c for c in
                  (GLOBAL_DISPLAY_COLS + (["목표대비상승여력"]
                   if "목표대비상승여력" in plot_df.columns else []))
                  if c in plot_df.columns and c != "종목명"]
        tbl_df = plot_df[["종목명"] + disp].set_index("종목명")

        # 색상 + 포맷
        tbl = style_pnl(tbl_df, ["손익", "전일대비(원)", "전일대비(%)", "누적수익률"])
        fmt = {
            "수량": "{:,.0f}", "매입단가": "{:,.0f}", "매입금액": "{:,.0f}",
            "현재가": "{:,.0f}", "평가금액": "{:,.0f}", "손익": "{:+,.0f}",
            "전일대비(원)": "{:+,.0f}", "전일대비(%)": "{:+.2f}%",
            "누적수익률": "{:+.2f}%",
        }
        if "목표대비상승여력" in tbl_df.columns:
            fmt["목표대비상승여력"] = "{:+.1f}%"
        tbl = tbl.format(fmt)

        def _w(c): return col_width(tbl_df[c]) if c in tbl_df.columns else "small"

        st.dataframe(tbl, use_container_width=True, column_config={
            "수량":             st.column_config.NumberColumn("수량",         format="%,.0f",   width=_w("수량")),
            "매입단가":         st.column_config.NumberColumn("매입단가",     format="%,.0f",   width=_w("매입단가")),
            "매입금액":         st.column_config.NumberColumn("매입금액",     format="%,.0f",   width=_w("매입금액")),
            "현재가":           st.column_config.NumberColumn("현재가",       format="%,.0f",   width=_w("현재가")),
            "평가금액":         st.column_config.NumberColumn("평가금액",     format="%,.0f",   width=_w("평가금액")),
            "손익":             st.column_config.NumberColumn("손익",         format="%+,.0f",  width=_w("손익")),
            "전일대비(원)":     st.column_config.NumberColumn("전일대비(원)", format="%+,.0f",  width=_w("전일대비(원)")),
            "전일대비(%)":      st.column_config.NumberColumn("전일대비(%)",  format="%+.2f%%", width="small"),
            "누적수익률":       st.column_config.ProgressColumn(
                "누적수익률", help="매입가 대비 누적 손익률",
                format="%.2f%%", min_value=-s_ret_abs, max_value=s_ret_abs, width="medium"),
            "목표대비상승여력": st.column_config.ProgressColumn(
                "목표여력", help="목표가까지 상승 여력",
                format="%.1f%%", min_value=0, max_value=up_max, width="medium"),
        })

    # ── 섹션 3: 현금흐름 메트릭 ───────────────────────────

    def _render_cashflow(self):
        a_eval      = self.sub_df["평가금액"].sum()
        a_total_div = self.sub_df["예상배당금"].sum()
        a_monthly   = (a_total_div * (1 - DIVIDEND_TAX_RATE)) / 12

        d1, d2, d3, d4 = st.columns(4)
        d1.metric("연간 예상 배당금",   f"{a_total_div:,.0f}원")
        d2.metric("세후 월 수령액",     f"{a_monthly:,.0f}원")
        d3.metric("계좌 배당수익률",    f"{(a_total_div/a_eval*100):.2f}%" if a_eval else "0.00%")
        d4.metric("계좌 현금흐름 등급", get_cashflow_grade(a_monthly))

    # ── 섹션 4: 차트 (배당 예측 + 자산 비중) ──────────────

    def _render_charts(self):
        a_eval   = self.sub_df["평가금액"].sum()
        g_l, g_r = st.columns(2)

        with g_l:
            with st.container(border=True):
                self._build_dividend_bar()

        with g_r:
            with st.container(border=True):
                self._build_weight_bar(a_eval)

    def _build_dividend_bar(self):
        monthly = {m: 0 for m in range(1, 13)}
        for _, row in self.sub_df.iterrows():
            sched  = DIVIDEND_SCHEDULE.get(row["종목명"], [(4, 0)])
            months = _extract_months(sched)
            for m in months:
                monthly[m] += row["예상배당금"] / len(months)
        fig = go.Figure(go.Bar(
            x=[f"{m}월" for m in range(1, 13)],
            y=list(monthly.values()),
            marker_color="rgba(255,215,0,0.6)",
            text=[f"{v/10000:.1f}만" if v > 0 else "" for v in monthly.values()],
            textposition="outside",
        ))
        fig.update_layout(
            title=dict(text="📅 월별 배당 예측", x=0.02),
            height=300, paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,0.02)", font_color="white",
            margin=dict(t=80, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    def _build_weight_bar(self, a_eval: float):
        cd = self.sub_df[["종목명", "평가금액", "누적수익률"]].copy()
        cd["Display"] = cd["종목명"].apply(lambda x: x[:9] + ".." if len(x) > 9 else x)
        fig = go.Figure(go.Bar(
            y=cd["Display"], x=cd["평가금액"], orientation="h",
            marker_color=[self.COLOR_POS if r > 0 else self.COLOR_NEG
                          for r in cd["누적수익률"]],
            text=[f" {int(v/a_eval*100)}%" if a_eval else "" for v in cd["평가금액"]],
            textposition="outside",
        ))
        fig.update_layout(
            title=dict(text="📊 자산 비중", x=0.02),
            height=300, paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,0.02)", font_color="white",
            margin=dict(t=80, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── 섹션 5: 종목 셀렉터 ───────────────────────────────

    def _render_stock_selector(self) -> str:
        return st.selectbox(
            f"🔍 {self.acc_name} 종목 정밀 분석 (전략/성과/뉴스 통합)",
            self.sub_df["종목명"].unique(),
            key=f"sel_{self.acc_name}_unified",
        )

    # ── 섹션 6: 종목 상세 분석 ────────────────────────────

    def _render_stock_detail(self, sel: str):
        s_row     = self.sub_df[self.sub_df["종목명"] == sel].iloc[0]
        curr_p    = float(s_row.get("현재가", 0))
        buy_p     = float(s_row.get("매입단가", 0))
        target_p  = float(s_row.get("목표가", 0))
        high_52   = float(s_row.get("52주최고가", 0))
        post_high = float(s_row.get("매입후최고가", curr_p))
        total_ret = float(s_row.get("누적수익률", 0))
        upside    = float(s_row.get("목표대비상승여력", 0))
        days      = max(int(s_row.get("보유일수", 365)), 1)
        ann_ret   = ((1 + total_ret / 100) ** (365 / days) - 1) * 100
        sl_price  = buy_p    * (1 - STOP_LOSS_PCT)
        tp_price  = post_high * (1 - TRAILING_PCT)

        self._render_research_panel(sel, ann_ret, target_p, upside, curr_p, high_52)
        self._render_risk_alert(curr_p, buy_p, post_high, sl_price, tp_price)
        self._render_performance_chart(sel, s_row)

    def _render_research_panel(
        self, sel: str, ann_ret: float, target_p: float,
        upside: float, curr_p: float, high_52: float,
    ):
        col_res, col_strat = st.columns(2)
        with col_res:
            res = RESEARCH_DATA.get(sel.replace(" ", ""))
            if res:
                rows = "".join([
                    f"<tr><td>{m[0]}</td>"
                    f"<td style='text-align:right;'>{m[1]} → "
                    f"<span style='color:{self.COLOR_GOLD};'>{m[2]}</span></td></tr>"
                    for m in res["metrics"]
                ])
                st.html(
                    f"<div class='report-box' style='height:210px;'>"
                    f"📋 <b>핵심 재무 지표</b>"
                    f"<table style='width:100%'>{rows}</table>"
                    f"<div style='margin-top:10px; font-size:0.85rem; "
                    f"border-top:1px solid rgba(255,255,255,0.05); padding-top:8px;'>"
                    f"<span style='color:{self.COLOR_GOLD};'>💡 인사이트:</span> "
                    f"{res['implications'][0]}</div></div>"
                )
            else:
                st.info("💡 종목 분석 데이터가 없습니다.")

        with col_strat:
            st.html(f"""
                <div style='background:rgba(135,206,235,0.05); padding:15px; border-radius:8px;
                            border:1px solid rgba(135,206,235,0.1); height:210px; text-align:center;'>
                    <div style='color:#87CEEB; font-size:0.85rem; font-weight:bold; margin-bottom:15px;'>
                        ⚡ 실시간 전략 모니터
                    </div>
                    <div style='display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;'>
                        <div>
                            <div style='font-size:0.75rem; opacity:0.6;'>연 환산 수익률</div>
                            <div style='font-size:1.2rem; font-weight:bold; color:{self.COLOR_POS};'>
                                {ann_ret:+.1f}%
                            </div>
                        </div>
                        <div style='border-left:1px solid rgba(255,255,255,0.1);
                                    border-right:1px solid rgba(255,255,255,0.1);'>
                            <div style='font-size:0.75rem; color:{self.COLOR_GOLD};'>🎯 시트 목표가</div>
                            <div style='font-size:1.2rem; font-weight:bold; color:{self.COLOR_GOLD};'>
                                {target_p:,.0f}
                            </div>
                        </div>
                        <div>
                            <div style='font-size:0.75rem; opacity:0.6;'>기대 상승 여력</div>
                            <div style='font-size:1.2rem; font-weight:bold; color:{self.COLOR_GREEN};'>
                                {upside:+.1f}%
                            </div>
                        </div>
                    </div>
                    <div style='border-top:1px solid rgba(255,255,255,0.05); padding-top:10px;
                                margin-top:15px; font-size:0.9rem; color:#bbb;'>
                        현재가: <b>{curr_p:,.0f}원</b> / 52주 최고: {high_52:,.0f}원
                    </div>
                </div>
            """)

    def _render_risk_alert(
        self, curr_p: float, buy_p: float,
        post_high: float, sl_price: float, tp_price: float,
    ):
        sl_hit    = curr_p <= sl_price
        tp_hit    = curr_p <= tp_price
        border_c  = self.COLOR_POS if sl_hit else "rgba(255,255,255,0.1)"
        sl_status = "⚠️ 즉시 대응" if sl_hit else "✅ 매우 안전"
        tp_status = "⚠️ 추세 이탈" if tp_hit else "✅ 추세 유지"
        sl_c = self.COLOR_POS if sl_hit else self.COLOR_GREEN
        tp_c = "#FFA500"       if tp_hit else self.COLOR_GREEN

        st.html(f"""
            <div style='background:rgba(0,0,0,0.2); padding:15px; border-radius:8px;
                        border:1px solid {border_c}; margin-top:15px;'>
                <div style='display:flex; justify-content:space-between; font-size:0.95rem;'>
                    <span>🛡️ <b>손절 가이드 (-{STOP_LOSS_PCT*100:.0f}%):</b>
                        {sl_price:,.0f}원 <small>(매입 {buy_p:,.0f} 대비)</small></span>
                    <span style='color:{sl_c}; font-weight:bold;'>{sl_status}</span>
                </div>
                <div style='display:flex; justify-content:space-between; font-size:0.95rem; margin-top:8px;'>
                    <span>🚨 <b>익절 가이드 (-{TRAILING_PCT*100:.0f}%):</b>
                        {tp_price:,.0f}원 <small>(최고 {post_high:,.0f} 대비)</small></span>
                    <span style='color:{tp_c}; font-weight:bold;'>{tp_status}</span>
                </div>
            </div>
        """)

    def _render_performance_chart(self, sel: str, s_row):
        with st.container(border=True):
            if self.history_df.empty:
                return
            fig = go.Figure()
            hdf  = self.history_df.copy()
            hdf["Date"] = pd.to_datetime(hdf["Date"])
            h_dt = hdf["Date"].dt.date.astype(str)

            goal_val = s_row.get("목표수익률", 10.0)
            if goal_val == 0 or pd.isna(goal_val): goal_val = 10.0

            fig.add_trace(go.Scatter(x=h_dt, y=hdf["KOSPI_Relative"],
                name="KOSPI", line=dict(dash="dash", color="rgba(255,255,255,0.3)", width=1)))
            fig.add_trace(go.Scatter(x=h_dt, y=[float(goal_val)] * len(h_dt),
                name="목표 수익률", line=dict(color=self.COLOR_GOLD, width=2, dash="dot")))

            acc_col = find_matching_col(hdf, self.acc_name)
            if acc_col:
                cy = hdf[acc_col].iloc[-1]
                lc = self.COLOR_GREEN if cy >= float(goal_val) else self.COLOR_POS
                fig.add_trace(go.Scatter(x=h_dt, y=hdf[acc_col],
                    mode="lines+markers", name="계좌 수익률",
                    line=dict(width=4, color=lc)))
            s_col = find_matching_col(hdf, self.acc_name, sel)
            if s_col:
                fig.add_trace(go.Scatter(x=h_dt, y=hdf[s_col],
                    mode="lines", name=sel[:9],
                    line=dict(width=2, dash="dashdot", color="rgba(135,206,235,0.6)")))

            fig.update_layout(
                title=dict(text=f"📈 {sel} 성과 분석 추이", x=0.02),
                height=400, paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(255,255,255,0.02)", font_color="white",
                legend=dict(orientation="h", yanchor="bottom", y=-0.3,
                            xanchor="center", x=0.5),
                margin=dict(t=80, b=80),
                xaxis=dict(type="category", tickangle=-45),
            )
            st.plotly_chart(fig, use_container_width=True)

    # ── 섹션 7: 뉴스 ──────────────────────────────────────

    def _render_news(self, sel: str):
        st.divider()
        st.html(
            f"<div style='font-size:1.2rem; font-weight:bold; margin-bottom:15px;'>"
            f"📰 {sel} 실시간 주요 뉴스</div>"
        )
        try:
            from mem_cache import get_news_cached
            items = get_news_cached(sel)
        except Exception:
            items = get_stock_news(sel)
        if not items:
            st.caption("새로운 뉴스가 없습니다.")
            return
        n1, n2 = st.columns(2)
        for idx, item in enumerate(items[:6]):
            with (n1 if idx % 2 == 0 else n2):
                hot = item.get("is_recent", False)
                bc  = self.COLOR_GOLD if hot else "#87CEEB"
                pfx = f"<span style='color:{self.COLOR_GOLD};'>[NEW]</span> " if hot else ""
                st.html(f"""
                    <div style='margin-bottom:10px; padding:10px; border-radius:8px;
                                border-left:4px solid {bc}; background:rgba(255,255,255,0.02);'>
                        <a href='{item["link"]}' target='_blank'
                           style='text-decoration:none; color:#87CEEB; font-size:0.95rem;'>
                            {pfx}{item["title"]}
                        </a>
                    </div>
                """)

    # ── 섹션 8: 투자 메모 ─────────────────────────────────

    def _render_memo(self, sel: str):
        st.divider()
        st.html(
            f"<div style='font-size:1.2rem; font-weight:bold; margin-bottom:12px;'>"
            f"📝 {sel} 투자 메모 / 근거</div>"
        )
        memo_key  = f"memo_text_{self.acc_name}_{sel}"
        saved_key = f"memo_saved_{self.acc_name}_{sel}"

        # ── 버그픽스 1: nan 방어 ────────────────────────────────
        # Google Sheets 빈 셀 → pandas NaN → str() → "nan" 문자열 발생
        def _safe_memo(text) -> str:
            if text is None:
                return ""
            s = str(text).strip()
            return "" if s.lower() == "nan" else s

        # ── 버그픽스 2: value + key 동시 지정 충돌 해소 ─────────
        # key= 지정 시 Session State 가 위젯을 자동 관리 → value= 제거
        if memo_key not in st.session_state:
            st.session_state[memo_key] = _safe_memo(
                get_memo(self.memo_df, sel, self.acc_name)
            )
        else:
            st.session_state[memo_key] = _safe_memo(st.session_state[memo_key])

        with st.container(border=True):
            existing = _safe_memo(get_memo(self.memo_df, sel, self.acc_name))
            if existing:
                last = self.memo_df[
                    (self.memo_df["종목명"] == sel) &
                    (self.memo_df["계좌명"] == self.acc_name)
                ]["수정일시"].values
                st.html(
                    f"<div style='font-size:0.8rem; color:rgba(255,255,255,0.4); "
                    f"margin-bottom:8px;'>🕒 마지막 저장: "
                    f"{last[0] if len(last) else '-'}</div>"
                )

            new_memo = st.text_area(
                label="메모 입력",
                height=140, key=memo_key,
                placeholder=(
                    "예) 매수 근거: 반도체 사이클 바닥 확인\n"
                    "목표: 6개월 내 +20% / 손절선: 매입가 -15%\n"
                    "리스크: 환율 변동, 경쟁사 점유율 확대"
                ),
                label_visibility="collapsed",
            )
            cs, cc, _ = st.columns([2, 1.5, 6])
            with cs:
                if st.button("💾 저장",
                             key=f"btn_save_{self.acc_name}_{sel}",
                             use_container_width=True):
                    ok, _ = save_memo(
                        self.conn, self.memo_df,
                        sel, self.acc_name, new_memo, self.now_kst,
                    )
                    if ok:
                        st.session_state[saved_key] = True
                        st.rerun()
            with cc:
                if st.button("🗑️ 삭제",
                             key=f"btn_del_{self.acc_name}_{sel}",
                             use_container_width=True):
                    ok, _ = save_memo(
                        self.conn, self.memo_df,
                        sel, self.acc_name, "", self.now_kst,
                    )
                    if ok:
                        st.session_state[memo_key] = ""
                        st.rerun()
            if st.session_state.get(saved_key):
                st.success("✅ 메모가 저장됐습니다.")
                st.session_state[saved_key] = False


# 하위 호환 래퍼 — app.py 변경 없이 그대로 동작
def render_account_tab(
    acc_name: str, tab_obj,
    full_df: pd.DataFrame, history_df: pd.DataFrame,
    memo_df: pd.DataFrame, conn, now_kst,
):
    """AccountTabRenderer.render()의 함수형 래퍼 (app.py 인터페이스 유지)"""
    AccountTabRenderer(
        acc_name=acc_name, tab_obj=tab_obj,
        full_df=full_df, history_df=history_df,
        memo_df=memo_df, conn=conn, now_kst=now_kst,
    ).render()


# ════════════════════════════════════════════════════════
# 사이드바
# ════════════════════════════════════════════════════════

def render_sidebar(
    full_df: pd.DataFrame, history_df: pd.DataFrame,
    now_kst, m_status: dict, conn,
    snapshot: dict = None,
):
    """사이드바 전체 렌더링"""
    with st.sidebar:
        st.header("⚙️ 관리 메뉴")
        if st.button("🔄 실시간 데이터 전체 갱신"):
            from mem_cache import clear_data_cache
            clear_data_cache()
            st.rerun()
        st.divider()

        # 배당 D-Day
        _render_dividend_dday(full_df, now_kst)
        st.divider()

        # 내보내기
        st.subheader("📤 데이터 내보내기")
        ts = now_kst.strftime("%Y%m%d_%H%M")
        st.download_button("📄 CSV 다운로드", data=get_csv_bytes(full_df),
            file_name=f"가족자산_{ts}.csv", mime="text/csv",
            use_container_width=True)
        st.download_button("📊 엑셀 다운로드 (전체 시트)",
            data=get_excel_bytes(full_df, history_df),
            file_name=f"가족자산_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True)
        st.caption("엑셀: 전체·계좌별·수익률 추이 시트 포함")
        st.divider()

        # ── Google Sheets 수동 저장 ───────────────────────────
        _render_sheets_save_section(conn, full_df, m_status, now_kst)
        st.divider()

        # 기록 관리자
        _render_record_manager(full_df, history_df, now_kst, m_status, conn,
                                snapshot=snapshot)


def _render_sheets_save_section(conn, full_df, m_status, now_kst):
    """
    사이드바 — Google Sheets 수동 저장 섹션.
    SheetsWriter 는 버튼 클릭 시점에만 생성 → 앱 시작 시 API 호출 없음.
    """
    st.subheader("☁️ Sheets 저장")

    if st.button("📤 지금 저장", use_container_width=True, key="btn_sheets_save"):
        with st.spinner("Google Sheets 저장 중..."):
            try:
                from sheets_pipeline import SheetsWriter, run_eod_pipeline, save_collection_log
                # 버튼 클릭 시점에만 SheetsWriter 생성 (Rate Limit 방지)
                writer  = SheetsWriter.from_streamlit(conn)
                results = run_eod_pipeline(writer, full_df, m_status, now_kst=now_kst)
                save_collection_log(writer, results, source="manual_sidebar", now_kst=now_kst)
                st.session_state["sheets_last_save"] = now_kst.strftime("%m/%d %H:%M")
                for item, ok in results.items():
                    if ok is None:
                        st.caption(f"⏭️ {item}: 스킵")
                    elif ok:
                        st.success(f"✅ {item}")
                    else:
                        st.error(f"❌ {item} 실패")
            except Exception as e:
                st.error(f"저장 오류: {e}")

    last_save = st.session_state.get("sheets_last_save")
    if last_save:
        st.caption(f"마지막 저장: {last_save}")


def _render_dividend_dday(full_df: pd.DataFrame, now_kst):
    st.subheader("💰 배당 수령 캘린더")
    events = get_dividend_calendar(full_df, now_kst)
    if not events:
        st.caption("배당 예정 종목이 없습니다.")
        return

    near  = [e for e in events if e["D_DAY"] <= 90][:8]
    first = events[0]
    d     = first["D_DAY"]
    label = "🎉 오늘!" if d == 0 else f"D-{d}"
    uc    = "#FF4B4B" if d <= 7 else "#FFD700" if d <= 30 else "#87CEEB"
    at    = first["예상배당금"] * (1 - DIVIDEND_TAX_RATE)

    st.markdown(f"""
        <div style='background:rgba(255,255,255,0.03); border:1px solid {uc}55;
                    border-left:4px solid {uc}; border-radius:10px;
                    padding:12px 14px; margin-bottom:10px;'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <div style='font-size:0.8rem; color:rgba(255,255,255,0.5);'>다음 배당</div>
                <div style='font-size:1.1rem; font-weight:700; color:{uc};'>{label}</div>
            </div>
            <div style='font-size:1.0rem; font-weight:600; margin-top:4px;'>{first["종목명"]}</div>
            <div style='font-size:0.8rem; color:rgba(255,255,255,0.5); margin-top:2px;'>
                {first["지급예정일"].strftime("%Y.%m.%d")} ({first["계좌명"]})
            </div>
            <div style='font-size:0.9rem; color:#FFD700; margin-top:6px;'>
                세후 예상 ≈ {at:,.0f}원
            </div>
        </div>
    """, unsafe_allow_html=True)

    for e in near[1:]:
        d2 = e["D_DAY"]
        c2 = "#FF4B4B" if d2 <= 7 else "#FFD700" if d2 <= 30 else "#87CEEB"
        a2 = e["예상배당금"] * (1 - DIVIDEND_TAX_RATE)
        st.markdown(f"""
            <div style='display:flex; justify-content:space-between; align-items:center;
                        padding:7px 4px; border-bottom:1px solid rgba(255,255,255,0.05);
                        font-size:0.82rem;'>
                <div>
                    <span style='color:rgba(255,255,255,0.75);'>{e["종목명"][:9]}</span>
                    <span style='color:rgba(255,255,255,0.35); margin-left:4px;'>
                        {e["지급예정일"].strftime("%m.%d")}
                    </span>
                </div>
                <div style='text-align:right;'>
                    <span style='color:{c2}; font-weight:600;'>D-{d2}</span>
                    <span style='color:#FFD700; margin-left:8px;'>{a2:,.0f}원</span>
                </div>
            </div>
        """, unsafe_allow_html=True)

    total = sum(e["예상배당금"] * (1 - DIVIDEND_TAX_RATE) for e in near)
    st.markdown(f"""
        <div style='text-align:right; font-size:0.8rem; color:rgba(255,255,255,0.4);
                    margin-top:8px;'>
            90일 내 세후 합계 ≈ <b style='color:#FFD700;'>{total:,.0f}원</b>
        </div>
    """, unsafe_allow_html=True)


def _render_record_manager(
    full_df: pd.DataFrame, history_df: pd.DataFrame,
    now_kst, m_status: dict, conn,
    snapshot: dict = None,   # { "2026-03-09": {"KOSPI": 5251.87, "삼성전자": 111400, ...} }
):
    st.subheader("⚙️ 기록 관리자 모드")
    sel_date = st.date_input("📅 저장/복구 날짜 선택", value=now_kst.date())

    if st.button(f"🔍 {sel_date} 데이터 불러오기"):
        save_str  = sel_date.strftime("%Y-%m-%d")
        day_snap  = (snapshot or {}).get(save_str, {})   # 해당 날짜 스냅샷

        # KOSPI — 스냅샷 우선, 없으면 실시간 HUD 값
        try:
            fallback_kospi = float(m_status["KOSPI"]["val"].replace(",", ""))
        except Exception:
            fallback_kospi = 0.0
        kospi_val = day_snap.get("KOSPI", fallback_kospi)

        # 종목별 가격 — 스냅샷 우선, 없으면 현재가
        tmp = {}
        for _, r in full_df.iterrows():
            nm = r["종목명"]
            tmp[nm] = day_snap.get(nm, float(r["현재가"]))

        st.session_state["edit_kospi"]   = kospi_val
        st.session_state["edit_prices"]  = tmp
        st.session_state["editor_active"] = True
        st.success("✅ 데이터를 가져왔습니다. 아래 양식을 확인하세요.")

    if st.session_state.get("editor_active", False):
        with st.form(key="record_form"):
            st.subheader(f"🛠️ {sel_date} 수치 확정")
            f_kospi  = st.number_input("KOSPI 지수",
                value=st.session_state["edit_kospi"], format="%.2f")
            f_prices = {
                nm: st.number_input(nm, value=pv, format="%.0f")
                for nm, pv in st.session_state["edit_prices"].items()
            }
            if st.form_submit_button("🚀 위 수치로 시트 최종 기록"):
                try:
                    save_str  = sel_date.strftime("%Y-%m-%d")
                    new_entry = pd.Series(index=history_df.columns, dtype="object")
                    new_entry["Date"]  = save_str
                    if "날짜" in new_entry.index: new_entry["날짜"] = save_str
                    new_entry["KOSPI"] = f_kospi

                    for acc in full_df["계좌명"].unique():
                        acc_df   = full_df[full_df["계좌명"] == acc]
                        eval_sum = 0.0
                        buy_tot  = float(acc_df["매입금액"].sum())
                        for _, r in acc_df.iterrows():
                            tp  = f_prices[r["종목명"]]
                            bp  = float(r["매입단가"])
                            sc  = find_matching_col(history_df, acc, r["종목명"])
                            if sc: new_entry[sc] = ((tp / bp) - 1) * 100
                            eval_sum += tp * float(r["수량"])
                        ac = find_matching_col(history_df, acc)
                        if ac: new_entry[ac] = ((eval_sum / buy_tot) - 1) * 100

                    hc  = history_df.copy()
                    hc["Date"] = pd.to_datetime(hc["Date"]).dt.strftime("%Y-%m-%d")
                    upd = pd.concat(
                        [hc[hc["Date"] != save_str], pd.DataFrame([new_entry])],
                        ignore_index=True,
                    )
                    conn.update(worksheet="trend",
                                data=upd.sort_values("Date").reset_index(drop=True))
                    st.success("✅ 시트 기록 성공!")
                    st.session_state["editor_active"] = False
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 오류: {e}")


# ════════════════════════════════════════════════════════
# 배당·분배금 실적 탭
# ════════════════════════════════════════════════════════




def _render_avg_calc():
    """추가매입 평균단가 계산기 (공통 헬퍼)"""
    with st.expander("💹 추가매입 평균단가 계산기"):
        cc1, cc2 = st.columns(2)
        _cur_qty   = cc1.number_input("현재 보유 수량",     min_value=0, value=100,   step=1,   key="calc_cq")
        _cur_price = cc1.number_input("현재 평균단가 (원)", min_value=0, value=60000, step=100, key="calc_cp")
        _add_qty   = cc2.number_input("추가 매입 수량",     min_value=0, value=50,    step=1,   key="calc_aq")
        _add_price = cc2.number_input("추가 매입 단가 (원)",min_value=0, value=55000, step=100, key="calc_ap")
        if _cur_qty + _add_qty > 0:
            _new_qty = _cur_qty + _add_qty
            _new_avg = (_cur_qty*_cur_price + _add_qty*_add_price) / _new_qty
            ra, rb, rc = st.columns(3)
            ra.metric("합산 수량",   f"{_new_qty:,}주")
            rb.metric("새 평균단가", f"{_new_avg:,.0f}원",
                      delta=f"{_new_avg-_cur_price:+,.0f}원",
                      delta_color="inverse" if _new_avg > _cur_price else "normal")
            rc.metric("추가 투자금", f"{_add_qty*_add_price:,.0f}원")

def render_trades_tab(
    trades_df: pd.DataFrame,
    avg_cost_df: pd.DataFrame,
    portfolio_df: pd.DataFrame,
    sell_df: pd.DataFrame = None,
):
    """📋 편매 실적 탭 — 매도 실적 + 실현손익 + 평균단가 계산기"""
    import datetime as _dt
    if sell_df is None:
        sell_df = pd.DataFrame()
    st.markdown("#### 📋 편매 실적 관리")

    # ── 시트 미연동 안내 ─────────────────────────────────
    if trades_df.empty and (sell_df is None or sell_df.empty):
        st.info(
            "**구글 시트에 `거래내역` 탭을 추가하고 아래 헤더로 구성하세요.**\n\n"
            "```\n날짜 | 계좌명 | 종목명 | 구분 | 수량 | 단가 | 수수료 | 메모\n```\n\n"
            "매도(`구분: 매도`) 행 입력 시 편매 실적이 자동 집계됩니다."
        )
        _render_avg_calc()
        return

    # ── 실현손익 요약 카드 ──────────────────────────────
    _realized_total = avg_cost_df["실현손익"].sum() if not avg_cost_df.empty else 0
    _sell_cnt       = len(sell_df) if not sell_df.empty else 0
    _this_year      = str(_dt.datetime.now().year)
    _realized_yr    = 0
    if not sell_df.empty and "매도일" in sell_df.columns:
        _realized_yr = sell_df[sell_df["매도일"].str.startswith(_this_year)]["실현손익"].sum()

    _sell_total_amt = sell_df["매도금액"].sum() if not sell_df.empty else 0
    _avg_ret        = sell_df["수익률(%)"].mean() if not sell_df.empty else 0

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("누적 실현손익",     f"{_realized_total:+,.0f}원",
              delta_color="normal" if _realized_total >= 0 else "inverse")
    s2.metric(f"{_this_year}년 실현손익", f"{_realized_yr:+,.0f}원",
              delta_color="normal" if _realized_yr >= 0 else "inverse")
    s3.metric("총 매도금액",       f"{_sell_total_amt:,.0f}원")
    s4.metric("편매 건수",         f"{_sell_cnt}건",
              delta=f"평균수익률 {_avg_ret:+.1f}%" if _sell_cnt > 0 else None,
              delta_color="normal" if _avg_ret >= 0 else "inverse")

    st.divider()

    # ── 편매 내역 테이블 ─────────────────────────────────
    st.markdown("**📉 편매 내역**")
    if not sell_df.empty:
        # 필터
        sf1, sf2 = st.columns(2)
        _s_acc = sf1.selectbox("계좌", ["전체"]+sorted(sell_df["계좌명"].unique().tolist()),
                                key="sell_acc", label_visibility="collapsed")
        _s_yr  = sf2.selectbox("연도", ["전체"]+sorted(
                                set(s[:4] for s in sell_df["매도일"] if s), reverse=True),
                                key="sell_yr", label_visibility="collapsed")
        disp_s = sell_df.copy()
        if _s_acc != "전체": disp_s = disp_s[disp_s["계좌명"]==_s_acc]
        if _s_yr  != "전체": disp_s = disp_s[disp_s["매도일"].str.startswith(_s_yr)]

        st.dataframe(
            disp_s.sort_values("매도일", ascending=False),
            hide_index=True, use_container_width=True,
            column_config={
                "매도수량":   st.column_config.NumberColumn(format="%,.0f"),
                "매입단가":   st.column_config.NumberColumn(format="%,.0f"),
                "매도단가":   st.column_config.NumberColumn(format="%,.0f"),
                "매도금액":   st.column_config.NumberColumn(format="%,.0f"),
                "실현손익":   st.column_config.NumberColumn(format="%+,.0f"),
                "수익률(%)":  st.column_config.NumberColumn(format="%+.2f%%"),
                "보유일수":   st.column_config.NumberColumn(format="%d일"),
                "수수료":     st.column_config.NumberColumn(format="%,.0f"),
            },
        )
    else:
        st.caption("매도 내역이 없습니다. 거래내역 탭에 매도(구분: 매도)를 입력하면 자동 집계됩니다.")

    # ── 연간 실현손익 추이 차트 ──────────────────────────
    if not sell_df.empty and "매도일" in sell_df.columns:
        st.divider()
        st.markdown("**📈 연간 실현손익 추이**")
        sell_df["연도"] = sell_df["매도일"].str[:4]
        yr_df = sell_df.groupby("연도")["실현손익"].sum().reset_index()
        yr_df["색상"] = yr_df["실현손익"].apply(lambda x: "#7dffb0" if x >= 0 else "#FF4B4B")
        fig_yr = go.Figure(go.Bar(
            x=yr_df["연도"], y=yr_df["실현손익"]/10000,
            marker_color=yr_df["색상"],
            text=[f"{v/10000:+.1f}만" for v in yr_df["실현손익"]],
            textposition="outside",
        ))
        fig_yr.add_hline(y=0, line_color="rgba(255,255,255,0.2)", line_width=1)
        fig_yr.update_layout(
            height=260, paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,0.02)", font_color="white",
            margin=dict(t=20, b=20, l=10, r=10),
            yaxis=dict(title="만원", tickformat=","),
        )
        st.plotly_chart(fig_yr, use_container_width=True)

    # ── 추가매입 평균단가 계산기 ─────────────────────────
    st.divider()
    _render_avg_calc()

def render_dividend_actual_tab(
    full_df: pd.DataFrame,
    conn,
    now_kst,
):
    """배당·분배금 실제 입금 실적 조회·시각화 탭"""
    st.markdown("#### 💸 배당·분배금 실적 관리")
    st.caption(
        "구글 시트 **배당실적** 탭에 입금 내역을 기록하면 자동 집계됩니다. "
        "시트 헤더: `입금일 | 계좌명 | 종목명 | 주당금액 | 세후금액 | 비고`"
    )

    act_df = load_dividend_actual(conn, portfolio_df=full_df)

    if act_df.empty:
        st.info(
            "📋 **배당실적 탭이 없거나 데이터가 없습니다.**\n\n"
            "구글 시트에 `배당실적` 탭을 추가하고 아래 형식으로 입력하세요.\n\n"
            "| 입금일 | 계좌명 | 종목명 | 주당금액 | 세후금액 | 비고 |\n"
            "|---|---|---|---|---|---|\n"
            "| 2026-04-17 | 큰스님투자 | KODEX200타겟위클리커버드콜 | 252 | | |\n"
            "| 2026-04-20 | 서은투자 | 삼성전자 | 361 | | |\n\n"
            "주당금액 × 수량(종목현황 탭 자동 조회) = 세전금액 자동 계산\n"
            "세후금액을 비워두면 세전 × 84.6%로 자동 계산됩니다."
        )
        return

    # ── 상단 요약 메트릭 ──────────────────────────────────
    cur_year   = now_kst.year
    ytd        = act_df[act_df["연도"] == cur_year]
    total_net  = act_df["세후금액"].sum()
    ytd_net    = ytd["세후금액"].sum()
    total_buy  = full_df["매입금액"].sum()
    yield_rate = (total_net / total_buy * 100) if total_buy > 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("누적 세후 수령",   f"{total_net:,.0f}원")
    m2.metric(f"{cur_year}년 수령", f"{ytd_net:,.0f}원")
    m3.metric("누적 배당수익률",   f"{yield_rate:.2f}%",
              help="세후 누적 수령 ÷ 현재 투자원금")
    m4.metric("입금 건수",         f"{len(act_df)}건")

    st.divider()

    # ── 월별 세후 수령액 막대차트 ─────────────────────────
    st.markdown("#### 📅 월별 세후 수령액")
    monthly = (
        act_df.groupby("연월")["세후금액"].sum().reset_index()
    )
    # ── 연도 필터 ──────────────────────────────────────────
    from config import DIVIDEND_SCHEDULE as DS, DIVIDEND_TAX_RATE as DTR, DIVIDEND_PAY_DAY as DPD
    import calendar as _cal

    # 올해·전체 연도 선택
    all_years = sorted(act_df["연도"].unique(), reverse=True)
    sel_year  = st.selectbox(
        "조회 연도", ["전체"] + [str(y) for y in all_years],
        index=0, key="div_year_sel",
    )
    if sel_year != "전체":
        view_df = act_df[act_df["연도"] == int(sel_year)]
    else:
        view_df = act_df

    monthly = view_df.groupby("연월")["세후금액"].sum().reset_index()

    # ── 예상 수령액 계산 (DIVIDEND_SCHEDULE 기준) ─────────
    monthly_pred = {}
    year_for_pred = int(sel_year) if sel_year != "전체" else cur_year
    for _, row in full_df.iterrows():
        name    = row.get("종목명", "")
        ms      = DS.get(name, [])
        div_amt = float(row.get("예상배당금", 0))
        if not ms or div_amt <= 0:
            continue
        amt_net = div_amt * (1 - DTR) / len(ms)
        pay_day_fixed = DPD.get(name, 0)
        for m in ms:
            last_day = _cal.monthrange(year_for_pred, m)[1]
            pay_day  = last_day if pay_day_fixed == 0 else min(pay_day_fixed, last_day)
            key = f"{year_for_pred}-{m:02d}"
            monthly_pred[key] = monthly_pred.get(key, 0) + amt_net

    fig_m = go.Figure()
    fig_m.add_trace(go.Bar(
        x=monthly["연월"], y=monthly["세후금액"] / 10000,
        name="실제 수령", marker_color="#7dffb0",
        text=[f"{v/10000:.1f}만" for v in monthly["세후금액"]],
        textposition="outside",
    ))
    if monthly_pred:
        pred_keys = sorted(monthly_pred.keys())
        fig_m.add_trace(go.Scatter(
            x=pred_keys,
            y=[monthly_pred[k] / 10000 for k in pred_keys],
            name=f"{year_for_pred}년 예상",
            mode="lines+markers",
            line=dict(color="#FFD700", dash="dot", width=2),
            marker=dict(size=7),
        ))
    fig_m.update_layout(
        height=320, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.02)", font_color="white",
        legend=dict(orientation="h", y=-0.25, xanchor="center", x=0.5),
        margin=dict(t=20, b=70, l=10, r=10),
        yaxis=dict(title="세후 수령액 (만원)", tickformat=","),
        xaxis=dict(tickangle=-30), hovermode="x unified",
        barmode="group",
    )
    st.plotly_chart(fig_m, use_container_width=True)

    st.divider()
    left_col, right_col = st.columns(2)

    # ── 종목별 누적 수령 ──────────────────────────────────
    with left_col:
        st.markdown("#### 📊 종목별 누적 세후 수령액")
        by_stock = (
            act_df.groupby("종목명")["세후금액"].sum()
            .sort_values(ascending=False).reset_index()
        )
        fig_s = go.Figure(go.Bar(
            x=by_stock["세후금액"] / 10000,
            y=by_stock["종목명"].apply(lambda x: x[:12]),
            orientation="h",
            marker_color="#87CEEB",
            text=[f"{v/10000:.1f}만" for v in by_stock["세후금액"]],
            textposition="outside",
        ))
        fig_s.update_layout(
            height=300, paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,0.02)", font_color="white",
            margin=dict(t=10, b=20, l=10, r=60),
            xaxis=dict(title="만원"),
        )
        st.plotly_chart(fig_s, use_container_width=True)

    # ── 계좌별 누적 수령 ──────────────────────────────────
    with right_col:
        st.markdown("#### 🏦 계좌별 누적 세후 수령액")
        by_acc = (
            act_df.groupby("계좌명")["세후금액"].sum()
            .sort_values(ascending=False).reset_index()
        )
        colors_acc = ["#FFD700", "#87CEEB", "#FF4B4B"]
        fig_a = go.Figure(go.Bar(
            x=by_acc["계좌명"],
            y=by_acc["세후금액"] / 10000,
            marker_color=colors_acc[:len(by_acc)],
            text=[f"{v/10000:.1f}만" for v in by_acc["세후금액"]],
            textposition="outside",
        ))
        fig_a.update_layout(
            height=300, paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,0.02)", font_color="white",
            margin=dict(t=10, b=20, l=10, r=10),
            yaxis=dict(title="만원"),
        )
        st.plotly_chart(fig_a, use_container_width=True)

    # ── 투자원금 대비 배당수익률 (영리단단리) ───────────────
    st.divider()
    st.markdown("#### 📈 종목별 투자원금 대비 누적 배당수익률")
    by_stock_full = act_df.groupby("종목명")["세후금액"].sum()

    # 종목명 기준 전체 계좌 매입금액 합산 (drop_duplicates 사용 시 다계좌 누락 방지)
    buy_by_stock  = full_df.groupby("종목명")["매입금액"].sum()

    rows_yield = []
    for name in buy_by_stock.index:
        buy_amt = float(buy_by_stock.get(name, 0))
        net_div = float(by_stock_full.get(name, 0))
        if buy_amt > 0:
            rows_yield.append({
                "종목명":        name,
                "투자원금(만원)": round(buy_amt / 10000, 1),
                "세후수령(만원)": round(net_div / 10000, 1),
                "배당수익률(%)":  round(net_div / buy_amt * 100, 2),
            })
    if rows_yield:
        yield_df = pd.DataFrame(rows_yield).sort_values("배당수익률(%)", ascending=False)
        st.dataframe(
            yield_df, hide_index=True, use_container_width=True,
            column_config={
                "투자원금(만원)": st.column_config.NumberColumn(format="%,.1f"),
                "세후수령(만원)": st.column_config.NumberColumn(format="%,.1f"),
                "배당수익률(%)":  st.column_config.ProgressColumn(
                    format="%.2f%%", min_value=0, max_value=20,
                ),
            },
        )

    # ── 종목별 연간 배당 누계 ────────────────────────────────
    st.divider()
    st.markdown("#### 📆 종목별 연간 배당 누계")
    if not act_df.empty:
        pivot = act_df.pivot_table(
            index="종목명", columns="연도",
            values="세후금액", aggfunc="sum", fill_value=0,
        ).reset_index()
        # 합계 열 추가
        year_cols = [c for c in pivot.columns if c != "종목명"]
        pivot["합계"] = pivot[year_cols].sum(axis=1)
        pivot = pivot.sort_values("합계", ascending=False)

        # 만원 단위로 표시
        for col in year_cols + ["합계"]:
            pivot[col] = (pivot[col] / 10000).round(1)

        col_cfg = {
            str(yr): st.column_config.NumberColumn(f"{yr}년(만원)", format="%,.1f")
            for yr in year_cols
        }
        col_cfg["합계"] = st.column_config.NumberColumn("합계(만원)", format="%,.1f")
        col_cfg["종목명"] = st.column_config.TextColumn("종목명")
        pivot.columns = [str(c) for c in pivot.columns]
        st.dataframe(pivot, hide_index=True, use_container_width=True,
                     column_config=col_cfg)

    # ── 전체 실적 테이블 ──────────────────────────────────
    with st.expander("📋 전체 입금 내역 보기"):
        disp = act_df.copy()
        disp["입금일"] = disp["입금일"].dt.strftime("%Y-%m-%d")
        show_cols = ["입금일","계좌명","종목명","주당금액","수량","세전금액","세후금액"]
        if "비고" in disp.columns:
            show_cols.append("비고")
        disp = disp[[c for c in show_cols if c in disp.columns]]
        st.dataframe(
            disp, hide_index=True, use_container_width=True,
            column_config={
                "주당금액": st.column_config.NumberColumn("주당금액(원)", format="%,.0f"),
                "수량":     st.column_config.NumberColumn("수량(주)",    format="%,.0f"),
                "세전금액": st.column_config.NumberColumn("세전금액(원)", format="%,.0f"),
                "세후금액": st.column_config.NumberColumn("세후금액(원)", format="%,.0f"),
            },
        )
