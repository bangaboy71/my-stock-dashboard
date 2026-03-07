import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import time
import re

# 1. 설정 및 연결 (v31.6 원형 사수)
st.set_page_config(page_title="가족 자산 성장 관제탑 v34.1", layout="wide")

# --- [CSS: v31.6 스타일 100% 복구] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 750px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.04); min-height: 500px; margin-bottom: 20px; }
    .sector-title { font-size: 1.3rem; font-weight: bold; border-bottom: 4px solid #87CEEB; padding-bottom: 12px; margin-bottom: 15px; color: #87CEEB; }
    .market-tag { background-color: rgba(135,206,235,0.2); padding: 5px 12px; border-radius: 6px; color: #87CEEB; font-weight: bold; margin-bottom: 10px; display: inline-block; font-size: 0.9em; }
    .leader-tag { background-color: rgba(255,215,0,0.15); border: 1px solid rgba(255,215,0,0.4); padding: 6px 12px; border-radius: 6px; color: #FFD700; font-weight: bold; margin-bottom: 12px; display: inline-block; font-size: 0.9em; }
    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.2rem; border: 2px solid; text-align: center; box-shadow: 4px 4px 15px rgba(0,0,0,0.3); background-color: rgba(0,0,0,0.2); }
    .up-style { color: #FF4B4B; border-color: #FF4B4B; background-color: rgba(255, 75, 75, 0.05); }
    .down-style { color: #87CEEB; border-color: #87CEEB; background-color: rgba(135, 206, 235, 0.05); }
    
    .acc-flash-container { background: rgba(255,215,0,0.05); padding: 15px; border-radius: 10px; border: 1px dashed #FFD700; margin-top: 20px; }
    .news-link { text-decoration: none; color: inherit; transition: 0.3s; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; cursor: pointer; }

    /* 🎯 딥다이브 카드 고도화 (v34.1) */
    .insight-card { background: rgba(135,206,235,0.03); padding: 22px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.2); margin-bottom: 20px; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.2rem; margin-bottom: 10px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 8px; }
    .insight-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-top: 10px; }
    .insight-label { color: rgba(255,255,255,0.5); font-size: 0.85rem; }
    .insight-value { color: #FFFFFF; font-weight: bold; font-size: 1rem; }
    .target-price { color: #FFD700; font-size: 1.1rem; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- [데이터 엔진 및 코드 설정] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# --- [🎯 딥다이브 엔진: N/A 문제 및 지표 확장] ---
@st.cache_data(ttl="30m")
def get_stock_intelligence(name):
    code = STOCK_CODES.get(name.replace(" ", ""))
    if not code: return None
    is_etf = any(kw in name for kw in ["KODEX", "TIGER", "ETF"])
    is_pref = "우" in name and "B" in name
    
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        info = {"type": "STOCK", "desc": "정보 분석 중...", "div": "N/A", "tp": "N/A", "per": "N/A", "pbr": "N/A", "mc": "N/A", "roe": "N/A", "eps": "N/A", "equity": "N/A"}
        if is_etf: info["type"] = "ETF"
        elif is_pref: info["type"] = "PREF"

        # 1. 기업개요
        summary = soup.find("div", {"id": "summary_info"})
        if summary: info["desc"] = summary.text.strip().split(".")[0] + "."

        # 2. 목표가 및 배당/PER/PBR (aside 테이블 정밀 파싱)
        aside = soup.find("div", {"class": "aside"})
        if aside:
            tp_em = aside.select_one(".expect em")
            if tp_em: info["tp"] = tp_em.text + "원"
            for tr in aside.find_all("tr"):
                th = tr.find("th")
                if th:
                    txt = th.text
                    val_em = tr.find("em")
                    if val_em:
                        val = val_em.text
                        if "PER" in txt and "배" in tr.text: info["per"] = val + "배"
                        elif "PBR" in txt and "배" in tr.text: info["pbr"] = val + "배"
                        elif ("배당수익률" in txt or "분배율" in txt): info["div"] = val + "%"

        # 3. 보통주 심화 지표 (시총, ROE, EPS, BPS)
        if info["type"] == "STOCK":
            mc_tag = soup.find("em", {"id": "_market_sum"})
            if mc_tag: info["mc"] = mc_tag.text.strip().replace("\t","").replace("\n","") + "억"
            
            f_table = soup.select_one(".section.cop_analysis table")
            if f_table:
                for row in f_table.select("tr"):
                    th_txt = row.find("th").text.strip() if row.find("th") else ""
                    tds = [td.text.strip() for td in row.find_all("td")]
                    if "ROE" in th_txt and tds: info["roe"] = tds[0] + "%"
                    elif "EPS" in th_txt and tds: info["eps"] = tds[0] + "원"
                    elif "BPS" in th_txt and tds: info["equity"] = tds[0] + "원"
        
        return info
    except: return None

# --- [v31.6 파싱 엔진 원형] ---
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

# --- [데이터 로드 및 전처리] ---
full_df = conn.read(worksheet=STOCKS_SHEET, ttl="1m")
history_df = conn.read(worksheet=TREND_SHEET, ttl=0)

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

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    history_df = history_df.dropna(subset=['Date'])
    history_df['Date'] = history_df['Date'].dt.date

# --- [사이드바 메뉴 복구] ---
st.sidebar.header("🕹️ 관제탑 마스터 메뉴")
if st.sidebar.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 오늘의 결과 저장/덮어쓰기"):
    today = now_kst.date()
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    new_row = {"Date": today, "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    conn.update(worksheet=TREND_SHEET, data=pd.concat([history_df[history_df['Date']!=today], pd.DataFrame([new_row])]).sort_values('Date'))
    st.sidebar.success("✅ 저장 완료"); st.rerun()

# --- [UI 메인 구성] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v34.1</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황 (v31.6 레이아웃 사수)
with tabs[0]:
    t_eval, t_buy, t_prev = full_df['평가금액'].sum(), full_df['매입금액'].sum(), full_df['전일평가금액'].sum()
    d_rate = ((t_eval / t_prev - 1) * 100) if t_prev > 0 else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("총 손익", f"{t_eval-t_buy:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{d_rate:+.2f}%")
    
    st.markdown("---")
    if not history_df.empty:
        fig = go.Figure()
        h_dates = history_df['Date'].astype(str)
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns:
                fig.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig.update_layout(title="📈 가족 자산 통합 수익률 추이 (v31.6 형식)", xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white", height=450)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    r1, r2 = st.columns(2)
    with r1: st.markdown("<div class='report-box'><h4 style='color:#87CEEB;'>🇰🇷 국내 시장 심층 분석 리포트</h4><p>2026년 3월 7일 현재, 국내 증시는 KOSPI 5,000선 안착을 위한 강력한 수급 기조를 유지 중입니다.</p></div>", unsafe_allow_html=True)
    with r2: st.markdown("<div class='report-box'><h4 style='color:#FF4B4B;'>🌍 글로벌 시장 및 매크로 분석</h4><p>나스닥 AI 랠리와 고환율 환경이 수출 대형주 실적에 우호적으로 작용하고 있습니다.</p></div>", unsafe_allow_html=True)
    
    st.divider()
    st.subheader("📊 관심 섹터별 인텔리전스 (v31.6 원형)")
    s_cols = st.columns(3)
    sectors = {"반도체 / IT": "삼성전자, SK하이닉스 주도.", "전력 / ESS": "북미 인프라 교체 수혜.", "배터리 / 에너지": "전고체 기술 기대감.", "바이오 / 헬스케어": "기술 수출 모멘텀.", "모빌리티 / 로봇": "휴머노이드 상용화.", "소비재 / 뷰티": "북미 점유율 폭증."}
    for i, (n, d) in enumerate(sectors.items()):
        with s_cols[i % 3]: st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><p>{d}</p></div>", unsafe_allow_html=True)

# [계좌별 상세 탭]
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
            sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
            intel = get_stock_intelligence(sel)
            if intel:
                # 🎯 [딥다이브] 지표 확장 버전
                card_html = f"""<div class='insight-card'>
                    <div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브</div>
                    <p style='font-size: 0.9rem; margin-bottom: 20px;'>{intel['desc']}</p>
                    <div class='insight-grid'>
                        <div><span class='insight-label'>{"분배/배당수익률" if intel['type']=="ETF" else "예상 배당률"}</span><br><span class='insight-value'>{intel['div']}</span></div>
                        <div><span class='insight-label'>리서치 목표가</span><br><span class='target-price'>{intel['tp']}</span></div>
                """
                if intel['type'] == "STOCK":
                    card_html += f"""
                        <div><span class='insight-label'>시가총액</span><br><span class='insight-value'>{intel['mc']}</span></div>
                        <div><span class='insight-label'>ROE</span><br><span class='insight-value'>{intel['roe']}</span></div>
                        <div><span class='insight-label'>EPS / BPS</span><br><span class='insight-value' style='font-size:0.8rem;'>{intel['eps']} / {intel['equity']}</span></div>
                        <div><span class='insight-label'>PER / PBR</span><br><span class='insight-value'>{intel['per']} / {intel['pbr']}</span></div>
                    """
                elif intel['type'] == "PREF":
                    card_html += f"<div><span class='insight-label'>PER / PBR</span><br><span class='insight-value'>{intel['per']} / {intel['pbr']}</span></div>"
                
                card_html += "</div></div>"
                st.markdown(card_html, unsafe_allow_html=True)
            
            # 🎯 [그래프] 큰스님 계좌 및 1개 종목인 경우 일원화 로직
            if not history_df.empty and history_col in history_df.columns:
                fig_acc = go.Figure()
                h_dt = history_df['Date'].astype(str)
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                
                # 큰스님 성과 추이 일원화 (종목이 1개면 점선 생략)
                is_single_stock = len(sub_df['종목명'].unique()) <= 1
                if not is_single_stock:
                    s_c = next((c for c in history_df.columns if acc_name[:2] in c and sel.replace(' ','') in c.replace(' ','')), "")
                    if s_c: fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[s_c], mode='lines', name=f'{sel} 수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                
                fig_acc.update_layout(height=400, xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig_acc, use_container_width=True)

        with g2:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v34.1 마스터피스 리스토어")
