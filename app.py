import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import re

# 1. 설정 및 연결 (v31.6 원형 100% 사수)
st.set_page_config(page_title="가족 자산 성장 관제탑 v35.2", layout="wide")

# --- [CSS: v31.6 스타일 및 렌더링 무결성 패치] ---
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
    .acc-flash-item { font-size: 0.88rem; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 4px; }
    .acc-flash-stock { color: #87CEEB; font-weight: bold; margin-right: 8px; }
    .news-link { text-decoration: none; color: inherit; transition: 0.3s; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; cursor: pointer; }

    /* 🎯 딥다이브: 배당/분배율 집중형 UI */
    .insight-card { background: rgba(135,206,235,0.03); padding: 22px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.2); margin-bottom: 20px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.15rem; margin-bottom: 15px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 8px; }
    .insight-label { color: rgba(255,255,255,0.5); font-size: 0.85rem; }
    .insight-value { color: #FFFFFF; font-weight: bold; font-size: 1.2rem; }
    </style>
    """, unsafe_allow_html=True)

# --- [데이터 엔진 및 코드 설정] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# --- [🎯 딥다이브 엔진: 배당/분배금 집중 & 태그 오류 해결] ---
@st.cache_data(ttl="30m")
def get_dividend_intelligence(name):
    code = STOCK_CODES.get(name.replace(" ", ""))
    if not code: return None
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
        info = {"desc": "정보 분석 중...", "div": "N/A", "type": "STOCK"}
        if any(kw in name for kw in ["KODEX", "TIGER", "ETF"]): info["type"] = "ETF"
        summary = soup.find("div", {"id": "summary_info"})
        if summary: info["desc"] = summary.text.strip().split(".")[0] + "."
        aside = soup.find("div", {"class": "aside"})
        if aside:
            for tr in aside.find_all("tr"):
                th = tr.find("th")
                if th and ("배당수익률" in th.text or "분배율" in th.text):
                    val_em = tr.find("em")
                    if val_em:
                        val = val_em.text
                        if float(val.replace(",","")) < 30: info["div"] = val + "%"
        return info
    except: return None

# --- [파싱 엔진 복구] ---
def get_acc_news(stocks):
    news_list = []
    try:
        for s in stocks:
            code = STOCK_CODES.get(s.replace(" ", ""))
            if not code: continue
            soup = BeautifulSoup(requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            news_sec = soup.find("div", {"class": "news_section"})
            if news_sec:
                tag = news_sec.find("li").find("a")
                news_list.append({"name": s, "title": tag.text.strip(), "url": tag['href'] if tag['href'].startswith("http") else f"https://finance.naver.com{tag['href']}"})
    except: pass
    return news_list

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

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [🎯 사이드바 메뉴 100% 복구] ---
def record_performance():
    today = now_kst.date()
    m_info = get_market_indices()
    # 계좌별 누적 수익률 계산
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    new_row = {
        "Date": today, 
        "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), 
        "서은수익률": acc_sum.get('서은투자', 0), 
        "서희수익률": acc_sum.get('서희투자', 0), 
        "큰스님수익률": acc_sum.get('큰스님투자', 0)
    }
    # 오늘의 데이터 업데이트 (기존 오늘 데이터가 있으면 덮어쓰기)
    updated_history = pd.concat([history_df[history_df['Date'] != today], pd.DataFrame([new_row])]).sort_values('Date')
    conn.update(worksheet="trend", data=updated_history)
    st.sidebar.success(f"✅ {today} 결과 저장 완료!"); st.cache_data.clear(); st.rerun()

st.sidebar.header("🕹️ 관제탑 마스터 메뉴")
if st.sidebar.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 오늘의 결과 저장/덮어쓰기"): record_performance()
if st.sidebar.button("🧹 과거 데이터 정제 (중복 제거)"):
    clean_history = history_df.drop_duplicates(subset=['Date'], keep='last')
    conn.update(worksheet="trend", data=clean_history)
    st.sidebar.success("✅ 중복 데이터 정제 완료!"); st.rerun()

# --- [UI 메인 구성] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v35.2</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황 (v31.6 원형 복구)
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
        h_dates = history_df['Date'].dt.date.astype(str)
        bk_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        k_yield = ((history_df['KOSPI'] / bk_k) - 1) * 100
        fig.add_trace(go.Scatter(x=h_dates, y=k_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns:
                fig.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig.update_layout(title="📈 가족 자산 통합 수익률 추이 (vs KOSPI)", xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white", height=450)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트 (v31.6)")
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    idx_l.markdown(f"<div class='index-indicator {m_idx['KOSPI']['style']}'>KOSPI: {m_idx['KOSPI']['now']} ({m_idx['KOSPI']['diff']}, {m_idx['KOSPI']['rate']})</div>", unsafe_allow_html=True)
    idx_r.markdown(f"<div class='index-indicator {m_idx['KOSDAQ']['style']}'>KOSDAQ: {m_idx['KOSDAQ']['now']} ({m_idx['KOSDAQ']['diff']}, {m_idx['KOSDAQ']['rate']})</div>", unsafe_allow_html=True)
    
    rep_l, rep_r = st.columns(2)
    with rep_l: st.markdown("<div class='report-box'><h4 style='color:#87CEEB;'>🇰🇷 국내 시장 분석</h4><p>국내 증시는 코스피 5,000선 시대에 접어들며 강력한 펀더멘털을 보이고 있습니다.</p></div>", unsafe_allow_html=True)
    with rep_r: st.markdown("<div class='report-box'><h4 style='color:#FF4B4B;'>🌍 글로벌 매크로 분석</h4><p>나스닥 AI 랠리와 고환율 환경이 수출 대형주 실적에 우호적으로 작용 중입니다.</p></div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("📊 관심 섹터별 인텔리전스 (6대 섹터)")
    s_cols = st.columns(3)
    sectors = {"반도체 / IT": "AI 수요 폭발 수혜.", "전력 / ESS": "북미 인프라 교체 주기.", "배터리": "전고체 기술 기대감.", "바이오": "기술 수출 모멘텀.", "모빌리티": "휴머노이드 상용화.", "뷰티": "글로벌 점유율 확대."}
    for i, (n, d) in enumerate(sectors.items()):
        with s_cols[i % 3]: st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><p>{d}</p></div>", unsafe_allow_html=True)

# [계좌별 상세 분석 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        # 계좌별 상단 지표 복구
        a_buy, a_eval, a_prev = sub_df['매입금액'].sum(), sub_df['평가금액'].sum(), sub_df['전일평가금액'].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_prev:+,.0f}원")
        c2.metric("매입원금", f"{a_buy:,.0f}원")
        c3.metric("총 손익", f"{a_eval-a_buy:+,.0f}원")
        c4.metric("수익률", f"{(a_eval/a_buy-1)*100:.2f}%")
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '손익', '수익률']].style.map(color_positive_negative, subset=['손익', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
            intel = get_dividend_intelligence(sel)
            if intel:
                st.markdown(f"""
                <div class='insight-card'>
                    <div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브</div>
                    <p style='font-size: 0.9rem; color: rgba(255,255,255,0.8);'>{intel['desc']}</p>
                    <div class='insight-grid'>
                        <div><span class='insight-label'>{"분배금 수익률" if intel['type']=="ETF" else "예상 배당수익률"}</span><br><span class='insight-value'>{intel['div']}</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            if not history_df.empty and history_col in history_df.columns:
                fig_acc = go.Figure()
                h_dt = history_df['Date'].dt.date.astype(str)
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                if len(sub_df) > 1:
                    s_c = next((c for c in history_df.columns if acc_name[:2] in c and sel.replace(' ','') in c.replace(' ','')), "")
                    if s_c: fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[s_c], mode='lines', name=f'{sel} 수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                fig_acc.update_layout(height=400, xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig_acc, use_container_width=True)

        with g2:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

        st.divider()
        ar_l, ar_r = st.columns(2)
        with ar_l: st.markdown("<div class='report-box' style='height:250px;'><h4 style='color:#87CEEB;'>📋 계좌 총평</h4><p>안정적인 흐름을 유지 중입니다.</p></div>", unsafe_allow_html=True)
        with ar_r: st.markdown("<div class='report-box' style='height:250px;'><h4 style='color:#FF4B4B;'>🌍 대응 전략</h4><p>변동성을 방어하며 추가 수익을 창출합니다.</p></div>", unsafe_allow_html=True)

        acc_news = get_acc_news(sub_df['종목명'].unique().tolist())
        if acc_news:
            news_html = " ".join([f"<div class='acc-flash-item'><span class='acc-flash-stock'>[{n['name']}]</span> <a href='{n['url']}' target='_blank' class='news-link'>{n['title']} ↗️</a></div>" for n in acc_news])
            st.markdown(f"<div class='acc-flash-container'><div style='font-weight: bold; color: #FFD700; margin-bottom: 10px;'>🔔 최신 공시/뉴스 (새 창 이동)</div>{news_html}</div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v35.2 완전체 복구")
