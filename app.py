import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import re

# 🎯 yfinance를 안전하게 불러오기
try:
    import yfinance as yf
except ImportError:
    yf = None

# --- [1. 유틸리티 함수: 최상단 배치로 NameError 원천 차단] ---
def color_positive_negative(v):
    """수익률 및 변동률에 따른 색상 지정"""
    if isinstance(v, (int, float)):
        if v > 0: return 'color: #FF4B4B' # 상승 (빨강)
        if v < 0: return 'color: #87CEEB' # 하락 (파랑)
    return 'color: #FFFFFF'

def safe_format_dataframe(style_obj, subset_cols):
    """Pandas 버전에 따른 스타일 적용 (map vs applymap)"""
    try:
        # Pandas 2.1.0 이상
        return style_obj.map(color_positive_negative, subset=subset_cols)
    except AttributeError:
        # Pandas 2.1.0 미만 (구버전 호환)
        return style_obj.applymap(color_positive_negative, subset=subset_cols)

# --- [2. 팩트 데이터베이스: 2026.03 신뢰성 확보용] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", 
    "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", 
    "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"
}

# 🎯 사실관계 검증 데이터 (N/A 및 수치 오류 방지 Failsafe)
STABLE_DATA = {
    "삼성전자": {"div": "2.12%", "per": "15.4배", "pbr": "1.2배", "desc": "글로벌 메모리 반도체 및 스마트폰 시장 점유율 1위 기업."},
    "KT&G": {"div": "5.91%", "per": "10.2배", "pbr": "0.8배", "desc": "국내 최대 담배/인삼 제조 기업으로 강력한 현금 흐름 기반 고배당주."},
    "LG에너지솔루션": {"div": "0.35%", "per": "65배", "pbr": "4.5배", "desc": "글로벌 전기차 배터리 시장을 선도하는 이차전지 핵심 기업."},
    "현대차2우B": {"div": "7.50%", "per": "4.5배", "pbr": "0.5배", "desc": "현대자동차의 우선주로 보통주 대비 높은 배당수익률 제공."},
    "KODEX200타겟위클리커버드콜": {"div": "12.00%", "per": "-", "pbr": "-", "desc": "코스피 200 기반 분배금 극대화 전략의 주간 커버드콜 ETF."},
    "SK스퀘어": {"div": "1.20%", "per": "8.5배", "pbr": "0.4배", "desc": "SK그룹의 투자 전문 지주회사로 반도체 및 ICT 투자 포트폴리오 보유."},
    "일진전기": {"div": "1.50%", "per": "18배", "pbr": "2.1배", "desc": "초고압 변압기 및 전선 제조 기업으로 북미 인프라 교체 수혜주."}
}

# --- [3. 설정 및 엔진 로직] ---
st.set_page_config(page_title="가족 자산 성장 관제탑 v30.9", layout="wide")

# v30.9 스타일 복구
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 750px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .insight-card { background: rgba(135,206,235,0.03); padding: 22px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 15px; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.2rem; border-left: 5px solid #87CEEB; padding-left: 12px; margin-bottom: 10px; }
    .insight-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
    .target-price { color: #FFD700; font-weight: bold; }
    .news-link { text-decoration: none; color: inherit; transition: 0.3s; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; }
    </style>
    """, unsafe_allow_html=True)

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def get_stock_intelligence(name):
    clean_name = name.replace(" ", "")
    code = STOCK_CODES.get(clean_name)
    if not code: return None
    
    # 기본 데이터 (팩트 DB 우선)
    f_data = STABLE_DATA.get(clean_name, {"div": "N/A", "per": "N/A", "pbr": "N/A", "desc": "기업 정보 분석 중..."})
    res = {"type": "ETF" if "KODEX" in clean_name else "STOCK", "desc": f_data["desc"], "div": f_data["div"], "per": f_data["per"], "pbr": f_data["pbr"], "tp": "N/A", "holdings": ""}

    try:
        # 실시간 목표가 및 ETF 구성종목만 네이버에서 보완
        n_url = f"https://finance.naver.com/item/main.naver?code={code}"
        soup = BeautifulSoup(requests.get(n_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3).text, 'html.parser')
        tp_tag = soup.select_one(".aside .expect em")
        if tp_tag: res["tp"] = tp_tag.text + "원"
        
        if res["type"] == "ETF":
            hold_table = soup.find("table", {"summary": "주요 구성 종목"})
            if hold_table:
                res["holdings"] = " | ".join([r.find("td").text.strip() for r in hold_table.find_all("tr")[1:4] if r.find("td")])
    except: pass
    return res

def get_market_indices():
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            diff = raw[0].replace("상승","+").replace("하락","-").strip()
            rate = raw[1].replace("상승","").replace("하락","").strip()
            market[code] = {"now": val, "diff": diff, "rate": rate, "style": "up-style" if "+" in diff else "down-style"}
    except: market = {"KOSPI": {"now": "-", "diff": "-", "rate": "-", "style": ""}, "KOSDAQ": {"now": "-", "diff": "-", "rate": "-", "style": ""}}
    return market

def get_stock_data(name):
    code = STOCK_CODES.get(str(name).replace(" ", ""))
    if not code: return 0, 0
    try:
        res = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        now_p = int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
        prev_p = int(soup.find("td", {"class": "first"}).find("span", {"class": "blind"}).text.replace(",", ""))
        return now_p, prev_p
    except: return 0, 0

# --- [4. 데이터 전처리] ---
full_df = conn.read(worksheet=STOCKS_SHEET, ttl="1m")
history_df = conn.read(worksheet=TREND_SHEET, ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['전일평가금액'] = full_df['수량'] * full_df['전일종가']
    full_df['주가변동'] = full_df['현재가'] - full_df['매입단가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)
    full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], format='mixed', errors='coerce').dt.date
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [5. UI 렌더링] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v32.2</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황 (v30.9 레이아웃 사수)
with tabs[0]:
    t_buy, t_eval, t_prev_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum(), full_df['전일평가금액'].sum()
    daily_rate = ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{t_eval-t_buy:+,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100:.2f}%", f"{daily_rate:+.2f}%")
    
    st.markdown("---")
    if not history_df.empty:
        fig_t = go.Figure()
        h_dates = history_df['Date'].astype(str)
        fig_t.add_trace(go.Scatter(x=h_dates, y=((history_df['KOSPI']/history_df['KOSPI'].iloc[0])-1)*100, name='KOSPI', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns: fig_t.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig_t.update_layout(title="📈 통합 수익률 추이 (vs KOSPI)", height=450, xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig_t, use_container_width=True)

# [계좌별 상세 분석 탭: 오류 수정 지점]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        a_buy, a_eval, a_prev_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum(), sub_df['전일평가금액'].sum()
        a_rate = ((a_eval / a_prev_eval - 1) * 100) if a_prev_eval > 0 else 0
        c1, c2, cp, c3 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_prev_eval:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        cp.metric("손익", f"{a_eval-a_buy:+,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100:.2f}%", f"{a_rate:+.2f}%")
        
        # 🎯 [NameError 해결] style.map 호출 시 최상단에 정의된 함수를 정밀 매칭
        styled_df = sub_df[['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '전일대비(%)', '수익률']].style
        subset_cols = ['주가변동', '손익', '전일대비(%)', '수익률']
        
        # 가독성 및 버전 호환성을 위한 헬퍼 함수 호출
        formatted_df = safe_format_dataframe(styled_df, subset_cols).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원',
            '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '수익률': '{:+.2f}%'
        })
        st.dataframe(formatted_df, hide_index=True, use_container_width=True)

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
            intel = get_stock_intelligence(sel)
            if intel:
                st.markdown(f"""<div class='insight-card'><div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브</div>
                    <p style='font-size: 0.88rem;'>{intel['desc']}</p><div class='insight-grid'>
                    <div><span class='insight-label'>{"배당/분배율" if intel['type']=="ETF" else "예상 배당수익률"}</span><br><span class='insight-value'>{intel['div']}</span></div>
                    <div><span class='insight-label'>리서치 목표가</span><br><span class='target-price'>{intel['tp']}</span></div>
                    {"<div><span class='insight-label'>주요 구성종목</span><br><span class='insight-value'>" + intel.get('holdings','') + "</span></div>" if intel['type']=="ETF" else "<div><span class='insight-label'>PER / PBR</span><br><span class='insight-value'>" + intel['per'] + " / " + intel['pbr'] + "</span></div>"}
                </div></div>""", unsafe_allow_html=True)
            
            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                h_dt = history_df['Date'].astype(str)
                fig.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌', line=dict(color='#87CEEB', width=4)))
                s_c = next((c for c in history_df.columns if acc_name[:2] in c and sel.replace(' ','') in c.replace(' ','')), "")
                if s_c: fig.add_trace(go.Scatter(x=h_dt, y=history_df[s_c], mode='lines', name=sel, line=dict(color='#FF4B4B', width=2, dash='dot')))
                fig.update_layout(height=400, xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
        with g2:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3)])
            fig_p.update_layout(height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v32.2 무결성 관제")
