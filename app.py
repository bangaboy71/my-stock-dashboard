import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import re

# 🎯 yfinance를 안전하게 불러오기 (설치 전 오류 방지)
try:
    import yfinance as yf
except ImportError:
    yf = None

# 1. 설정 및 연결 (v30.9 원형)
st.set_page_config(page_title="가족 자산 성장 관제탑 v31.9", layout="wide")

# --- [CSS: v30.9 스타일 100% 복구] ---
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

    /* 🎯 딥다이브 카드 스타일 */
    .insight-card { background: rgba(135,206,235,0.03); padding: 22px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.2); margin-bottom: 15px; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.15rem; margin-bottom: 10px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 8px; }
    .insight-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 10px; }
    .insight-label { color: rgba(255,255,255,0.5); font-size: 0.85rem; }
    .insight-value { color: #FFFFFF; font-weight: bold; font-size: 1rem; }
    .target-price { color: #FFD700; font-size: 1.15rem; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- [데이터 엔진 및 시간 설정: v30.9 원형] ---
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

# --- [🎯 딥다이브 엔진: 에셋 타겟팅 + yfinance 하이브리드] ---
@st.cache_data(ttl="1h")
def get_stock_intelligence(name):
    if yf is None: return None
    code = STOCK_CODES.get(name.replace(" ", ""))
    if not code: return None
    
    # 1. 종목 성격 판별
    is_etf = any(kw in name for kw in ["KODEX", "TIGER", "ETF"])
    is_pref = "우" in name and "B" in name
    
    # 2. 야후 티커 설정
    yahoo_code = f"{code}.KS" if int(code) < 300000 or is_etf else f"{code}.KQ"
    
    try:
        ticker = yf.Ticker(yahoo_code)
        info = ticker.info
        
        res = {"type": "STOCK", "desc": "정보 분석 중...", "per": "N/A", "pbr": "N/A", "div": "N/A", "tp": "N/A"}
        
        # 기업 개요 (영문 기반 번역 생략하고 핵심만)
        res["desc"] = info.get("longBusinessSummary", "정보를 불러올 수 없습니다.")[:120] + "..."
        
        if is_etf:
            res["type"] = "ETF"
            res["div"] = f"{info.get('trailingAnnualDividendYield', 0)*100:.2f}%" if info.get('trailingAnnualDividendYield') else "N/A"
        else:
            res["per"] = f"{info.get('trailingPE'):.2f}배" if info.get('trailingPE') else "N/A"
            res["pbr"] = f"{info.get('priceToBook'):.2f}배" if info.get('priceToBook') else "N/A"
            res["div"] = f"{info.get('dividendYield', 0)*100:.2f}%" if info.get('dividendYield') else "N/A"
            if is_pref: res["type"] = "PREF"
            
            # 목표가 및 한국어 상세 요약은 네이버에서 보완
            n_url = f"https://finance.naver.com/item/main.naver?code={code}"
            soup = BeautifulSoup(requests.get(n_url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            tp_tag = soup.select_one(".aside .expect em")
            if tp_tag: res["tp"] = tp_tag.text + "원"
            summary = soup.find("div", {"id": "summary_info"})
            if summary: res["desc"] = summary.text.strip().split(".")[0] + "."
            
        return res
    except: return None

# (get_market_indices, get_stock_data, get_acc_news 등 v30.9 원형 유지)
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
            cls = "up-style" if "+" in diff else "down-style" if "-" in diff else ""
            market[code] = {"now": val, "diff": diff, "rate": rate, "style": cls}
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

def get_acc_news(stocks):
    news_list = []
    try:
        for s in stocks:
            code = STOCK_CODES.get(s.replace(" ", ""))
            if not code: continue
            res = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            news_sec = soup.find("div", {"class": "news_section"})
            if news_sec:
                tag = news_sec.find("li").find("a")
                news_list.append({"name": s, "title": tag.text.strip(), "url": tag['href'] if tag['href'].startswith("http") else f"https://finance.naver.com{tag['href']}"})
    except: pass
    return news_list

# --- [데이터 로드 및 전처리: v30.9 무결성] ---
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

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v31.9</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황 (v30.9 레이아웃 100% 사수)
with tabs[0]:
    t_buy, t_eval, t_prev_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum(), full_df['전일평가금액'].sum()
    daily_rate = ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{t_eval-t_buy:+,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{daily_rate:+.2f}%")
    
    st.markdown("---")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

    if not history_df.empty:
        st.markdown("<br>", unsafe_allow_html=True)
        fig_t = go.Figure()
        h_dates = history_df['Date'].astype(str)
        fig_t.add_trace(go.Scatter(x=h_dates, y=((history_df['KOSPI']/history_df['KOSPI'].iloc[0])-1)*100, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns: fig_t.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig_t.update_layout(title="📈 가족 자산 통합 수익률 추이 (vs KOSPI)", height=450, xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig_t, use_container_width=True)

    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    idx_l.markdown(f"<div class='index-indicator {m_idx['KOSPI']['style']}'>KOSPI: {m_idx['KOSPI']['now']} ({m_idx['KOSPI']['diff']}, {m_idx['KOSPI']['rate']})</div>", unsafe_allow_html=True)
    idx_r.markdown(f"<div class='index-indicator {m_idx['KOSDAQ']['style']}'>KOSDAQ: {m_idx['KOSDAQ']['now']} ({m_idx['KOSDAQ']['diff']}, {m_idx['KOSDAQ']['rate']})</div>", unsafe_allow_html=True)

# [계좌별 상세 분석 탭: v30.9 레이아웃 + 딥다이브 카드]
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
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '전일대비(%)', '수익률']].style.map(color_positive_negative, subset=['주가변동', '손익', '전일대비(%)', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원', '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            stk_list = sub_df['종목명'].unique().tolist()
            sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", stk_list, key=f"sel_{acc_name}")
            
            # 🎯 [하이브리드] yfinance 기반 딥다이브 카드 표출
            intel = get_stock_intelligence(sel)
            if intel:
                st.markdown(f"""
                <div class='insight-card'>
                    <div class='insight-title'>🔍 {sel} 인텔리전스 (Hybrid 엔진)</div>
                    <p style='font-size: 0.88rem; color: rgba(255,255,255,0.8);'>{intel['desc']}</p>
                    <div class='insight-grid'>
                        <div><span class='insight-label'>배당/분배수익률</span><br><span class='insight-value'>{intel['div']}</span></div>
                        <div><span class='insight-label'>리서치 목표가</span><br><span class='target-price'>{intel['tp']}</span></div>
                        <div><span class='insight-label'>PER</span><br><span class='insight-value'>{intel['per']}</span></div>
                        <div><span class='insight-label'>PBR</span><br><span class='insight-value'>{intel['pbr']}</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                h_dt = history_df['Date'].astype(str)
                fig.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                s_c = next((c for c in history_df.columns if acc_name[:2] in c and sel.replace(' ','') in c.replace(' ','')), "")
                if s_c: fig.add_trace(go.Scatter(x=h_dt, y=history_df[s_c], mode='lines', name=f'{sel} 수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                fig.update_layout(title=f"📈 {acc_name} 성과 추이", height=400, xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
        with g2:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

        st.divider()
        acc_news = get_acc_news(sub_df['종목명'].unique().tolist())
        if acc_news:
            news_html = " ".join([f"<div class='acc-flash-item'><span class='acc-flash-stock'>[{n['name']}]</span> <a href='{n['url']}' target='_blank' class='news-link'>{n['title']} ↗️</a></div>" for n in acc_news])
            st.markdown(f"<div class='acc-flash-container'><div style='font-weight: bold; color: #FFD700; margin-bottom: 10px;'>🔔 최신 공시/뉴스 (새 창 이동)</div>{news_html}</div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v31.9 하이브리드 엔진 & 예외처리 강화")
