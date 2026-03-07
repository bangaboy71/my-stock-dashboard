import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import re

# 1. 설정 및 연결 (v30.9 레이아웃 100% 사수)
st.set_page_config(page_title="가족 자산 성장 관제탑 v34.0", layout="wide")

# --- [CSS: v30.9 스타일 무결성 복구] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; font-weight: bold; }
    .report-box { padding: 25px; border-radius: 12px; height: 600px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.04); min-height: 250px; margin-bottom: 20px; }
    .sector-title { font-size: 1.25rem; font-weight: bold; border-bottom: 4px solid #87CEEB; padding-bottom: 10px; margin-bottom: 15px; color: #87CEEB; }
    .leader-tag { background-color: rgba(255,215,0,0.15); border: 1px solid rgba(255,215,0,0.4); padding: 6px 12px; border-radius: 6px; color: #FFD700; font-weight: bold; margin-bottom: 12px; display: inline-block; font-size: 0.9em; }
    
    /* 🎯 딥다이브 카드 가독성 패치 */
    .insight-card { background: rgba(135,206,235,0.04); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 20px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.3rem; border-left: 6px solid #87CEEB; padding-left: 15px; margin-bottom: 15px; }
    .insight-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-top: 15px; }
    .insight-label { color: rgba(255,255,255,0.5); font-size: 0.85rem; }
    .insight-value { color: #FFFFFF; font-weight: bold; font-size: 1rem; }
    .target-price { color: #FFD700 !important; font-weight: bold; }
    
    .index-indicator { padding: 15px; border-radius: 10px; font-weight: bold; text-align: center; border: 2px solid; background: rgba(0,0,0,0.3); font-size: 1.1rem; }
    .up-style { color: #FF4B4B; border-color: #FF4B4B; }
    .down-style { color: #87CEEB; border-color: #87CEEB; }
    .acc-flash-container { background: rgba(255,215,0,0.05); padding: 15px; border-radius: 10px; border: 1px dashed #FFD700; margin-top: 20px; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 신뢰성 중심 데이터 엔진] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def color_pos_neg(v):
    if isinstance(v, (int, float)):
        return 'color: #FF4B4B' if v > 0 else 'color: #87CEEB' if v < 0 else 'color: white'
    return 'color: white'

@st.cache_data(ttl="30m")
def get_verified_intelligence(name):
    code = STOCK_CODES.get(name.replace(" ", ""))
    if not code: return None
    is_etf = "KODEX" in name or "ETF" in name
    is_pref = "우" in name and "B" in name
    
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        info = {"type": "STOCK", "desc": "분석 중...", "div": "N/A", "tp": "N/A", "per": "N/A", "pbr": "N/A", "mc": "N/A", "equity": "N/A", "eps": "N/A", "roe": "N/A", "holdings": ""}
        if is_etf: info["type"] = "ETF"
        elif is_pref: info["type"] = "PREF"

        # 1. 기업개요
        summary = soup.find("div", {"id": "summary_info"})
        if summary: info["desc"] = summary.text.strip().split(".")[0] + "."

        # 2. 목표가 및 배당 (aside 테이블)
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
        
        # 4. ETF 구성종목
        if is_etf:
            hold_table = soup.find("table", {"summary": "주요 구성 종목"})
            if hold_table:
                info["holdings"] = " | ".join([r.find("td").text.strip() for r in hold_table.find_all("tr")[1:4] if r.find("td")])

        return info
    except: return None

# (get_market_indices, get_stock_data, get_acc_news 등 원형 유지)
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
now_kst = datetime.now(timezone(timedelta(hours=9)))
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
    full_df['수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    history_df = history_df.dropna(subset=['Date'])
    history_df['Date'] = history_df['Date'].dt.date

# --- [4. 사이드바 관리 메뉴 복구] ---
st.sidebar.header("🕹️ 관제탑 마스터 메뉴")
if st.sidebar.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 오늘의 결과 저장/덮어쓰기"):
    today = now_kst.date()
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    new_row = {"Date": today, "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    conn.update(worksheet="trend", data=pd.concat([history_df[history_df['Date']!=today], pd.DataFrame([new_row])]).sort_values('Date'))
    st.sidebar.success("저장 완료"); st.rerun()

# --- [5. UI 메인 구성] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v34.0</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황 (v30.9 레이아웃 사수)
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
        fig.update_layout(title="📈 가족 자산 통합 수익률 추이 (v30.9 형식)", xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white", height=450)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    r1, r2 = st.columns(2)
    with r1: st.markdown("<div class='report-box'><h4 style='color:#87CEEB;'>🇰🇷 국내 시장 분석</h4><p>2026년 3월 7일 현재, KOSPI 5,000선 시대의 강력한 수급 기조를 유지 중입니다.</p></div>", unsafe_allow_html=True)
    with r2: st.markdown("<div class='report-box'><h4 style='color:#FF4B4B;'>🌍 글로벌 매크로 분석</h4><p>나스닥 AI 랠리와 고환율 환경이 수출 대형주 실적에 우호적으로 작용하고 있습니다.</p></div>", unsafe_allow_html=True)
    
    st.divider()
    st.subheader("📊 관심 섹터별 인텔리전스 (v30.9 원형 복구)")
    s_cols = st.columns(3)
    sectors = {"반도체 / IT": "AI 수요 폭발 수혜.", "전력 / ESS": "북미 인프라 교체 주기.", "배터리": "전고체 기술 기대감.", "바이오": "기술 수출 모멘텀.", "모빌리티": "휴머노이드 상용화.", "뷰티": "글로벌 점유율 확대."}
    for i, (n, d) in enumerate(sectors.items()):
        with s_cols[i % 3]: st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><p>{d}</p></div>", unsafe_allow_html=True)

# [계좌별 상세 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '손익', '전일대비(%)', '수익률']].style.map(color_pos_neg, subset=['손익', '전일대비(%)', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
            intel = get_verified_intelligence(sel)
            if intel:
                # 🎯 [해결] 자산 성격별 맞춤형 딥다이브 카드
                card_html = f"""<div class='insight-card'>
                    <div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브</div>
                    <p style='font-size: 0.9rem; margin-bottom: 20px;'>{intel['desc']}</p>
                    <div class='insight-grid'>
                        <div class='insight-item'><span class='insight-label'>{"분배/배당수익률" if intel['type']=="ETF" else "예상 배당수익률"}</span><span class='insight-value'>{intel['div']}</span></div>
                        <div class='insight-item'><span class='insight-label'>리서치 목표가</span><span class='insight-value target-price'>{intel['tp']}</span></div>
                """
                if intel['type'] == "STOCK":
                    card_html += f"""
                        <div class='insight-item'><span class='insight-label'>시가총액</span><span class='insight-value'>{intel['mc']}</span></div>
                        <div class='insight-item'><span class='insight-label'>ROE</span><span class='insight-value'>{intel['roe']}</span></div>
                        <div class='insight-item'><span class='insight-label'>EPS</span><span class='insight-value'>{intel['eps']}</span></div>
                        <div class='insight-item'><span class='insight-label'>자기자본(BPS)</span><span class='insight-value'>{intel['equity']}</span></div>
                        <div class='insight-item'><span class='insight-label'>PER</span><span class='insight-value'>{intel['per']}</span></div>
                        <div class='insight-item'><span class='insight-label'>PBR</span><span class='insight-value'>{intel['pbr']}</span></div>
                    """
                elif intel['type'] == "PREF":
                    card_html += f"<div class='insight-item'><span class='insight-label'>PER / PBR</span><span class='insight-value'>{intel['per']} / {intel['pbr']}</span></div>"
                elif intel['type'] == "ETF":
                    card_html += f"<div class='insight-item'><span class='insight-label'>주요 구성종목</span><span class='insight-value' style='font-size:0.75rem;'>{intel['holdings']}</span></div>"
                
                card_html += "</div></div>"
                st.markdown(card_html, unsafe_allow_html=True)
            
            # 🎯 [그래프 복구] 종목별 점선 대조
            if not history_df.empty and history_col in history_df.columns:
                fig_acc = go.Figure()
                h_dt = history_df['Date'].astype(str)
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
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

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v34.0 마스터피스 리스토레이션")
