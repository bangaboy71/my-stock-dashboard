import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import re

# 🎯 yfinance를 안전하게 임포트
try:
    import yfinance as yf
except ImportError:
    yf = None

# --- [1. 유틸리티 함수 및 스타일 정의] ---
def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return 'color: #FF4B4B' if v > 0 else 'color: #87CEEB' if v < 0 else 'color: #FFFFFF'
    return 'color: #FFFFFF'

st.set_page_config(page_title="가족 자산 성장 관제탑 v32.5", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 650px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 18px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.04); min-height: 200px; margin-bottom: 15px; }
    .sector-title { font-size: 1.1rem; font-weight: bold; border-bottom: 3px solid #87CEEB; padding-bottom: 8px; margin-bottom: 10px; color: #87CEEB; }
    .insight-card { background: rgba(135,206,235,0.03); padding: 22px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 15px; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.2rem; border-left: 5px solid #87CEEB; padding-left: 12px; margin-bottom: 15px; }
    .insight-grid { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 12px; margin-top: 10px; }
    .insight-label { color: rgba(255,255,255,0.5); font-size: 0.8rem; }
    .insight-value { color: #FFFFFF; font-weight: bold; font-size: 0.95rem; }
    .target-price { color: #FFD700; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 핵심 데이터 엔진] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

@st.cache_data(ttl="1h")
def get_advanced_intelligence(name):
    code = STOCK_CODES.get(name.replace(" ", ""))
    if not code: return None
    is_etf = any(kw in name for kw in ["KODEX", "TIGER", "ETF"])
    is_pref = "우" in name and "B" in name
    
    try:
        res = {"type": "STOCK", "desc": "기업 정보 분석 중...", "div": "N/A", "tp": "N/A", "per": "N/A", "pbr": "N/A", "mc": "N/A", "equity": "N/A", "eps": "N/A", "roe": "N/A"}
        
        # 1. Naver 파싱 (목표가 및 기본 재무제표 수치)
        n_url = f"https://finance.naver.com/item/main.naver?code={code}"
        soup = BeautifulSoup(requests.get(n_url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
        
        # 기업개요
        summary = soup.find("div", {"id": "summary_info"})
        if summary: res["desc"] = summary.text.strip().split(".")[0] + "."
        
        # 목표가
        tp_tag = soup.select_one(".aside .expect em")
        if tp_tag: res["tp"] = tp_tag.text + "원"

        if is_etf:
            res["type"] = "ETF"
            div_tag = soup.select_one(".aside tr:-soup-contains('분배율') em")
            if div_tag: res["div"] = div_tag.text + "%"
        else:
            if is_pref: res["type"] = "PREF"
            # 보통주 및 우선주 재무 지표 추출
            for tr in soup.select(".aside tr"):
                th = tr.find("th")
                if th:
                    txt = th.text
                    val = tr.find("em").text if tr.find("em") else "N/A"
                    if "PER" in txt: res["per"] = val + "배"
                    elif "PBR" in txt: res["pbr"] = val + "배"
                    elif "배당수익률" in txt: res["div"] = val + "%"
            
            # 보통주 전용 지표 (시총, 자기자본, EPS, ROE)
            if not is_pref:
                mc_tag = soup.find("em", {"id": "_market_sum"})
                if mc_tag: res["mc"] = mc_tag.text.strip() + "억"
                # 주요재무정보 테이블 파싱
                finance_sec = soup.select_one(".section.cop_analysis")
                if finance_sec:
                    ths = [th.text.strip() for th in finance_sec.select("th")]
                    tds = [td.text.strip() for td in finance_sec.select("td")]
                    if "ROE(%)" in ths: res["roe"] = tds[ths.index("ROE(%)")+1] + "%"
                    if "EPS(원)" in ths: res["eps"] = tds[ths.index("EPS(원)")+1] + "원"
                    if "BPS(원)" in ths: res["equity"] = tds[ths.index("BPS(원)")+1] + "원"
        
        return res
    except: return None

# (get_market_indices, get_stock_data 등 v30.9 엔진 유지)
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

# --- [3. 데이터 로드 및 전처리] ---
def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'], full_df['평가금액'] = full_df['수량'] * full_df['매입단가'], full_df['수량'] * full_df['현재가']
    full_df['전일평가금액'] = full_df['수량'] * full_df['전일종가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)
    full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

# --- [4. UI 구성] ---
st.sidebar.header("🕹️ 관제탑 관리 메뉴")
if st.sidebar.button("🔄 실시간 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 데이터 저장"):
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    new_row = {"Date": now_kst.date(), "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    conn.update(worksheet="trend", data=pd.concat([history_df, pd.DataFrame([new_row])]).drop_duplicates(subset=['Date'], keep='last'))
    st.sidebar.success("저장 완료")

st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v32.5</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 (v30.9 원형 복구)
with tabs[0]:
    t_eval, t_buy = full_df['평가금액'].sum(), full_df['매입금액'].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("가족 총 평가액", f"{t_eval:,.0f}원")
    c2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    c3.metric("총 손익", f"{t_eval-t_buy:+,.0f}원")
    c4.metric("누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%")
    
    st.markdown("---")
    if not history_df.empty:
        history_df['Date'] = pd.to_datetime(history_df['Date']).dt.date
        fig = go.Figure()
        h_dates = history_df['Date'].astype(str)
        fig.add_trace(go.Scatter(x=h_dates, y=history_df['서은수익률'], name='서은', line=dict(color='#FF4B4B', width=3)))
        fig.add_trace(go.Scatter(x=h_dates, y=history_df['서희수익률'], name='서희', line=dict(color='#87CEEB', width=3)))
        fig.update_layout(title="📈 가족 자산 수익률 추이", xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("🕵️ 데일리 심층 분석 리포트")
    r1, r2 = st.columns(2)
    with r1: st.markdown("<div class='report-box'><h4 style='color:#87CEEB;'>🇰🇷 국내 시장 분석</h4><p>2026년 3월 7일 현재, KOSPI 5,000선 시대의 강력한 펀더멘털을 확인하고 있습니다.</p></div>", unsafe_allow_html=True)
    with r2: st.markdown("<div class='report-box'><h4 style='color:#FF4B4B;'>🌍 글로벌 매크로 분석</h4><p>환율 1,400원대 중후반 유지 속에서 수출 대형주 중심의 수익 방어가 전개 중입니다.</p></div>", unsafe_allow_html=True)

# [계좌별 상세 분석 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '손익', '전일대비(%)', '수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            sel = st.selectbox(f"📍 {acc_name} 종목 분석", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
            intel = get_advanced_intelligence(sel)
            if intel:
                st.markdown(f"""
                <div class='insight-card'>
                    <div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브</div>
                    <p style='font-size: 0.85rem;'>{intel['desc']}</p>
                    <div class='insight-grid'>
                        <div><span class='insight-label'>배당/분배수익률</span><br><span class='insight-value'>{intel['div']}</span></div>
                        <div><span class='insight-label'>리서치 목표가</span><br><span class='target-price'>{intel['tp']}</span></div>
                        {"<div><span class='insight-label'>시가총액</span><br><span class='insight-value'>" + intel['mc'] + "</span></div><div><span class='insight-label'>ROE</span><br><span class='insight-value'>" + intel['roe'] + "</span></div>" if intel['type']=="STOCK" else ""}
                        {"<div><span class='insight-label'>EPS / BPS</span><br><span class='insight-value'>" + intel['eps'] + " / " + intel['equity'] + "</span></div>" if intel['type']=="STOCK" else ""}
                        {"<div><span class='insight-label'>PER / PBR</span><br><span class='insight-value'>" + intel['per'] + " / " + intel['pbr'] + "</span></div>" if intel['type'] != "ETF" else ""}
                    </div>
                </div>
                """, unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v32.5 인텔리전스 콤플리트")
