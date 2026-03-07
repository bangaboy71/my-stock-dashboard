import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import time
import re

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v31.6", layout="wide")

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
    .acc-flash-item { font-size: 0.88rem; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 4px; }
    .acc-flash-stock { color: #87CEEB; font-weight: bold; margin-right: 8px; }
    .news-link { text-decoration: none; color: inherit; transition: 0.3s; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; cursor: pointer; }

    /* 🎯 딥다이브 카드 스타일 고도화 */
    .insight-card { background: rgba(135,206,235,0.03); padding: 22px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.2); margin-bottom: 20px; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.15rem; margin-bottom: 10px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 8px; }
    .insight-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 10px; }
    .insight-label { color: rgba(255,255,255,0.5); font-size: 0.85rem; }
    .insight-value { color: #FFFFFF; font-weight: bold; font-size: 1rem; }
    .target-price { color: #FFD700; font-size: 1.15rem; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- [데이터 엔진 및 시간 설정: v30.9와 100% 동일] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def safe_float(text):
    try: return float(re.sub(r'[^0-9.\-+]', '', str(text))) if text else 0.0
    except: return 0.0

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# --- [🎯 딥다이브 엔진: N/A 문제 완벽 해결을 위한 정밀 로직] ---
def get_stock_intelligence(name):
    code = STOCK_CODES.get(name.replace(" ", ""))
    if not code: return None
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. 기업 개요 추출 (Stock vs ETF 대응)
        desc = "정보 분석 중..."
        summary = soup.find("div", {"id": "summary_info"})
        if not summary: summary = soup.find("div", {"class": "summary_info"})
        if summary:
            p_tag = summary.find("p")
            if p_tag: desc = p_tag.text.strip().split(".")[0] + "."

        tp, per, pbr, div = "N/A", "N/A", "N/A", "N/A"
        
        # 2. 리서치 목표가 (expect 영역 정밀 타격)
        expect_div = soup.find("div", {"class": "expect"})
        if expect_div:
            tp_em = expect_div.find("em")
            if tp_em: tp = tp_em.text + "원"
        
        # 3. 재무 지표 (aside 테이블의 th/td 쌍을 정확히 매칭)
        aside = soup.find("div", {"class": "aside"})
        if aside:
            for tr in aside.find_all("tr"):
                th = tr.find("th")
                if th:
                    th_txt = th.text
                    td_em = tr.find("em")
                    if td_em:
                        val = td_em.text
                        if "PER" in th_txt and "배" in tr.text: per = val + "배"
                        elif "PBR" in th_txt and "배" in tr.text: pbr = val + "배"
                        elif "배당수익률" in th_txt: div = val + "%"
        
        return {"desc": desc, "tp": tp, "per": per, "pbr": pbr, "div": div}
    except: return None

# --- [v30.9 공시/지수/가격 파싱 엔진 원형 복구] ---
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
                top_tag = news_sec.find("li").find("a")
                if top_tag:
                    href = top_tag['href']
                    full_link = href if href.startswith("http") else f"https://finance.naver.com{href}"
                    news_list.append({"name": s, "title": top_tag.text.strip(), "url": full_link})
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

# --- [사이드바 마스터 메뉴] ---
def record_performance():
    today = now_kst.date()
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    new_row = {"Date": today, "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    conn.update(worksheet=TREND_SHEET, data=pd.concat([history_df[history_df['Date']!=today], pd.DataFrame([new_row])]).sort_values('Date'))
    st.sidebar.success("✅ 저장 성공!"); st.cache_data.clear(); st.rerun()

st.sidebar.header("🕹️ 관제탑 마스터 메뉴")
if st.sidebar.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 오늘의 결과 저장/덮어쓰기"): record_performance()
if st.sidebar.button("🧹 과거 데이터 정제 (중복 제거)"):
    history_df['Date'] = pd.to_datetime(history_df['Date']).dt.strftime('%Y-%m-%d')
    conn.update(worksheet=TREND_SHEET, data=history_df.drop_duplicates(subset=['Date'], keep='last')); st.sidebar.success("정제 완료"); st.rerun()

# --- UI 메인 (버전 표시 수정) ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v31.6</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황 (v30.9 레이아웃 100% 사수)
with tabs[0]:
    t_buy, t_eval, t_prev_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum(), full_df['전일평가금액'].sum()
    total_profit, daily_rate = t_eval - t_buy, ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{total_profit:,.0f}원")
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
        bk_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        k_yield = ((history_df['KOSPI'] / bk_k) - 1) * 100
        fig_t.add_trace(go.Scatter(x=h_dates, y=k_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns: fig_t.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig_t.update_layout(title="📈 가족 자산 통합 수익률 추이 (vs KOSPI)", height=450, xaxis=dict(type='category'), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig_t, use_container_width=True)

    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    idx_l.markdown(f"<div class='index-indicator {m_idx['KOSPI']['style']}'>KOSPI: {m_idx['KOSPI']['now']} ({m_idx['KOSPI']['diff']}, {m_idx['KOSPI']['rate']})</div>", unsafe_allow_html=True)
    idx_r.markdown(f"<div class='index-indicator {m_idx['KOSDAQ']['style']}'>KOSDAQ: {m_idx['KOSDAQ']['now']} ({m_idx['KOSDAQ']['diff']}, {m_idx['KOSDAQ']['rate']})</div>", unsafe_allow_html=True)

    rep_l, rep_r = st.columns(2)
    with rep_l:
        st.markdown(f"""<div class='report-box'>
            <h4 style='color: #87CEEB;'>🇰🇷 국내 시장 심층 분석 리포트</h4>
            <div class='market-tag'>데일리 시장 총평</div>
            <p>2026년 3월 7일 현재, 국내 증시는 <b>KOSPI 5,000선</b> 돌파 이후 안착을 위한 강력한 수급 공방이 이어지는 역사적 변곡점에 있습니다.</p>
            <div class='market-tag'>KOSPI 시장 분석</div>
            <p>삼성전자와 SK하이닉스 등 시총 상위주가 지수 성장을 주도하고 있습니다.</p>
            <div class='market-tag'>KOSDAQ 시장 분석</div>
            <p>코스닥은 1,000선을 상회하며 로봇/AI 섹터로의 순환매가 빠르게 전개되고 있습니다.</p>
        </div>""", unsafe_allow_html=True)
    with rep_r:
        st.markdown(f"""<div class='report-box'>
            <h4 style='color: #FF4B4B;'>🌍 글로벌 시장 및 매크로 분석</h4>
            <div class='market-tag'>미국 증시 및 환율 상황</div>
            <p>나스닥은 기술주 중심의 랠리를 지속 중이며, 환율은 <b>1,400원 중후반대</b>를 유지하고 있습니다.</p>
            <div class='market-tag'>2026 미 중간선거 변수</div>
            <p>올해 하반기 미국 중간선거는 섹터별 대응 전략이 필수적인 핵심 변수입니다.</p>
        </div>""", unsafe_allow_html=True)

    st.divider()
    st.subheader("📊 관심 섹터별 인텔리전스")
    sec_cols = st.columns(3)
    sectors = {
        "반도체 / IT": {"주도주": "삼성전자, SK하이닉스", "전망": "AI 칩 수요 폭발."},
        "전력 / ESS": {"주도주": "LS ELECTRIC, 일진전기", "전망": "북미 인프라 교체 수혜."},
        "배터리 / 에너지": {"주도주": "LG에너솔루션, 에코프로", "전망": "전고체 기술 기대감."},
        "바이오 / 헬스케어": {"주도주": "삼성바이오, 알테오젠", "전망": "기술 수출 모멘텀."},
        "모빌리티 / 로봇": {"주도주": "현대차, 두산로보틱스", "전망": "휴머노이드 시장 개화."},
        "소비재 / 뷰티": {"주도주": "아모레퍼시픽, 브이티", "전망": "북미 점유율 폭증."}
    }
    for i, (n, d) in enumerate(sectors.items()):
        with sec_cols[i % 3]:
            st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><div class='leader-tag'>👑 주도주: {d['주도주']}</div><p style='font-size: 0.85em;'><b>🔭 전망:</b> {d['전망']}</p></div>", unsafe_allow_html=True)

# [계좌별 상세 분석 탭: v30.9 레이아웃 + 딥다이브 정상화]
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
            sel = st.selectbox(f"📍 {acc_name} 종목 분석 및 대조", stk_list, key=f"sel_{acc_name}")
            
            # 🎯 [신규] 인텔리전스 딥다이브 카드 (데이터 표출 정상화)
            intel = get_stock_intelligence(sel)
            if intel:
                st.markdown(f"""
                <div class='insight-card'>
                    <div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브</div>
                    <p style='font-size: 0.88rem; color: rgba(255,255,255,0.8);'>{intel['desc']}</p>
                    <div class='insight-grid'>
                        <div><span class='insight-label'>리서치 목표가</span><br><span class='target-price'>{intel['tp']}</span></div>
                        <div><span class='insight-label'>배당수익률</span><br><span class='insight-value'>{intel['div']}</span></div>
                        <div><span class='insight-label'>PER (배)</span><br><span class='insight-value'>{intel['per']}</span></div>
                        <div><span class='insight-label'>PBR (배)</span><br><span class='insight-value'>{intel['pbr']}</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                h_dt = history_df['Date'].astype(str)
                fig.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                # 🎯 종목별 개별 추이 대조 (v30.9 형식)
                s_c = next((c for c in history_df.columns if acc_name[:2] in c and sel.replace(' ','') in c.replace(' ','')), "")
                if s_c: fig.add_trace(go.Scatter(x=h_dt, y=history_df[s_c], mode='lines', name=f'{sel} 수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                fig.update_layout(title=f"📈 {acc_name} 성과 추이", height=400, xaxis=dict(type='category'), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
        with g2:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

        st.divider()
        st.subheader(f"🕵️ {acc_name} 데일리 인텔리전스 리포트")
        ar_l, ar_r = st.columns(2)
        with ar_l: st.markdown(f"<div class='report-box' style='height:250px;'><h4 style='color: #87CEEB;'>📋 계좌 총평</h4><p>현재 계좌는 주도주를 바탕으로 안정적인 흐름을 유지하고 있습니다.</p></div>", unsafe_allow_html=True)
        with ar_r: st.markdown(f"<div class='report-box' style='height:250px;'><h4 style='color: #FF4B4B;'>🌍 업황 대응 전략</h4><p>고환율 실적 효과를 모니터링 중입니다.</p></div>", unsafe_allow_html=True)

        # 🎯 하이퍼링크 공시 알림 (v30.9 유지)
        st.markdown("<br>", unsafe_allow_html=True)
        acc_news = get_acc_news(sub_df['종목명'].unique().tolist())
        if acc_news:
            news_html = " ".join([f"<div class='acc-flash-item'><span class='acc-flash-stock'>[{n['name']}]</span> <a href='{n['url']}' target='_blank' class='news-link'>{n['title']} ↗️</a></div>" for n in acc_news])
            st.markdown(f"<div class='acc-flash-container'><div style='font-weight: bold; color: #FFD700; margin-bottom: 10px;'>🔔 보유종목 최신 공시 (새 창 이동)</div>{news_html}</div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v31.6 파이널 레졸루션")
