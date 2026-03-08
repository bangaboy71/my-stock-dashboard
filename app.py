import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 UI 스타일 정의
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.21", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 280px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(135,206,235,0.2); background-color: rgba(135,206,235,0.03); min-height: 250px; margin-bottom: 20px; }
    .sector-title { font-size: 1.2rem; font-weight: bold; border-bottom: 3px solid #87CEEB; padding-bottom: 10px; margin-bottom: 15px; color: #87CEEB; }
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 25px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.3rem; margin-bottom: 20px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 12px; }
    .insight-flex { display: flex; gap: 30px; align-items: flex-start; }
    .insight-left { flex: 1.3; }
    .insight-right { flex: 1; background: rgba(255,215,0,0.04); padding: 20px; border-radius: 10px; border-left: 5px solid #FFD700; }
    .research-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
    .research-table th { text-align: left; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
    .research-table td { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .target-val { color: #FFD700; font-weight: bold; }
    .acc-flash-container { background: rgba(255,215,0,0.05); padding: 20px; border-radius: 10px; border: 1px dashed #FFD700; margin-top: 25px; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; cursor: pointer; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 엔진 및 연구 데이터베이스] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}
RESEARCH_DATA = {
    "삼성전자": {"metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("특별 DPS", "500원", "3.5~7천원")], "implications": ["HBM3E 양산 본격화", "특별 배당 기반 강력 환원"]},
    "KT&G": {"metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("자사주 소각", "0.9조", "0.5~1.1조")], "implications": ["NGP 성장 동력 확보", "발행주식 20% 소각 가속화"]},
    "현대차2우B": {"metrics": [("영업이익률", "6.2%", "7.0%"), ("시가배당률", "5.7%", "6.4%"), ("정규 DPS", "1.36만", "1.45~1.55만")], "implications": ["제네시스 믹스 개선", "은퇴 포트폴리오 핵심 캐시카우"]}
}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def get_market_indices():
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            market[code] = {"now": val, "diff": raw[0].replace("상승","+").replace("하락","-"), "rate": raw[1], "style": "up-style" if "+" in raw[0] or "상승" in raw[0] else "down-style"}
    except: market = {"KOSPI": {"now": "-", "diff": "-", "rate": "-", "style": ""}}
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
            soup = BeautifulSoup(requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            news_sec = soup.find("div", {"class": "news_section"})
            if news_sec:
                tag = news_sec.find("li").find("a")
                news_list.append({"name": s, "title": tag.text.strip(), "url": tag['href'] if tag['href'].startswith("http") else f"https://finance.naver.com{tag['href']}"})
    except: pass
    return news_list

# --- [3. 데이터 로드 및 정규화 엔진 (사실 근거)] ---
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'], full_df['평가금액'] = full_df['수량'] * full_df['매입단가'], full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
    full_df['전일대비변동률'] = (full_df['전일대비손익'] / (full_df['수량'] * full_df['전일종가']).replace(0, float('nan')) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    # 🎯 중복 제거 및 확정 일자 정렬 (3월 6일 데이터 사수)
    history_df = history_df.dropna(subset=['Date']).sort_values('Date').drop_duplicates('Date', keep='last').reset_index(drop=True)
    
    # 🎯 [정규화] 3월 3일 기준 0% 보정
    base_date = pd.Timestamp("2026-03-03")
    base_row = history_df[history_df['Date'] == base_date]
    if not base_row.empty:
        k_base = base_row['KOSPI'].values[0]
        history_df['KOSPI_Norm'] = (history_df['KOSPI'] / k_base - 1) * 100
        for col in ['서은수익률', '서희수익률', '큰스님수익률']:
            if col in history_df.columns:
                s_base = base_row[col].values[0]
                history_df[f'{col}_Norm'] = history_df[col] - s_base
    else:
        history_df['KOSPI_Norm'] = (history_df['KOSPI'] / (history_df['KOSPI'].iloc[0] if not history_df.empty else 1) - 1) * 100

# --- [4. 정밀 색채 스타일 엔진] ---
def style_summary(df):
    def apply_color(row):
        eval_c = 'color: #FF4B4B' if row['평가금액'] > row['매입금액'] else 'color: #87CEEB' if row['평가금액'] < row['매입금액'] else ''
        p_c = 'color: #FF4B4B' if row['손익'] > 0 else 'color: #87CEEB' if row['손익'] < 0 else ''
        d_c = 'color: #FF4B4B' if row['전일대비손익'] > 0 else 'color: #87CEEB' if row['전일대비손익'] < 0 else ''
        return ['', '', eval_c, p_c, d_c, d_c, p_c]
    return df.style.apply(apply_color, axis=1)

def style_holdings(df):
    def apply_color(row):
        price_c = 'color: #FF4B4B' if row['현재가'] > row['매입단가'] else 'color: #87CEEB' if row['현재가'] < row['매입단가'] else ''
        d_c = 'color: #FF4B4B' if row['전일대비손익'] > 0 else 'color: #87CEEB' if row['전일대비손익'] < 0 else ''
        t_c = 'color: #FF4B4B' if row['누적수익률'] > 0 else 'color: #87CEEB' if row['누적수익률'] < 0 else ''
        return ['', '', '', '', price_c, '', d_c, d_c, t_c]
    return df.style.apply(apply_color, axis=1)

# --- [5. 사이드바 및 저장 엔진] ---
st.sidebar.header("🕹️ 관제탑 마스터 메뉴")
if st.sidebar.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()

if st.sidebar.button("💾 오늘의 결과 저장"):
    today = pd.Timestamp(now_kst.date())
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    stock_sum = full_df.groupby('종목명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    
    new_row = {"Date": today, "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    for s_name, s_yield in stock_sum.items():
        new_row[s_name.replace(' ', '')] = s_yield
        
    update_df = pd.concat([history_df[history_df['Date'] != today], pd.DataFrame([new_row])]).sort_values('Date')
    conn.update(worksheet="trend", data=update_df)
    st.cache_data.clear(); st.sidebar.success("✅ 저장 완료!"); st.rerun()

# --- [6. UI 메인 구성] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v36.21</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy = full_df['평가금액'].sum(), full_df['매입금액'].sum()
    st.columns(4)[0].metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_buy:+,.0f}원")
    
    st.divider()
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum', '전일대비손익':'sum'}).reset_index()
    sum_acc['누적수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    sum_acc['전일대비변동률'] = (sum_acc['전일대비손익'] / (sum_acc['평가금액'] - sum_acc['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    sum_acc = sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비손익', '전일대비변동률', '누적수익률']]
    st.dataframe(style_summary(sum_acc).format({'매입금액':'{:,.0f}원', '평가금액':'{:,.0f}원', '손익':'{:+,.0f}원', '전일대비손익':'{:+,.0f}원', '전일대비변동률':'{:+.2f}%', '누적수익률':'{:+.2f}%'}), use_container_width=True, hide_index=True)

    if not history_df.empty:
        fig = go.Figure()
        # 🎯 가로축 고정: 시트 내 저장된 날짜만 표출
        h_dates = history_df['Date'].dt.date.astype(str)
        fig.add_trace(go.Scatter(x=h_dates, y=history_df['KOSPI_Norm'], name='KOSPI (3/3 기준)', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률_Norm': '#FF4B4B', '서희수익률_Norm': '#87CEEB', '큰스님수익률_Norm': '#00FF00'}.items():
            if col in history_df.columns:
                fig.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.split('_')[0], line=dict(color=color, width=3)))
        fig.update_layout(title="📈 통합 수익률 추이 (3/3 기준 정규화)", yaxis_title="누적수익률 상대비교지표", xaxis=dict(type='category'), height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    m_idx = get_market_indices()
    st.columns(2)[0].markdown(f"<div class='index-indicator {m_idx.get('KOSPI', {}).get('style', '')}'>KOSPI: {m_idx.get('KOSPI', {}).get('now', '-')}</div>", unsafe_allow_html=True)

# [투자 주체별 상세 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        # 상단 총합 메트릭
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        st.columns(4)[0].metric(f"{acc_name} 평가액", f"{a_eval:,.0f}원", f"{a_eval-a_buy:+,.0f}원")
        
        st.dataframe(style_holdings(sub_df[['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '전일대비손익', '전일대비변동률', '누적수익률']]).format({'매입금액':'{:,.0f}원', '평가금액':'{:,.0f}원', '현재가':'{:,.0f}원', '누적수익률':'{:+.2f}%'}), hide_index=True, use_container_width=True)

        st.divider()
        sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        
        # 🎯 리포트 및 그래프 섹션 (중간)
        g_left, g_right = st.columns([2, 1])
        with g_left:
            if not history_df.empty:
                fig_acc = go.Figure()
                h_dt = history_df['Date'].dt.date.astype(str)
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df['KOSPI_Norm'], name='KOSPI (3/3 기준)', line=dict(dash='dash', color='gray')))
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[f'{history_col}_Norm'], mode='lines+markers', name=f'{acc_name} 성과', line=dict(color='#87CEEB', width=4)))
                
                s_c = next((c for c in history_df.columns if sel.replace(' ','') in c.replace(' ','')), "")
                if s_c and s_c != history_col:
                    fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[s_c], mode='lines', name=f'{sel} 실재수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                fig_acc.update_layout(title=f"📈 {acc_name} 성과 추이 (누적수익률 기준)", yaxis_title="누적수익률(%)", xaxis=dict(type='category'), height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig_acc, use_container_width=True)
        with g_right:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

        # 🎯 [복구] 하단 손익 분석 리포트 및 뉴스
        st.divider()
        r_l, r_r = st.columns(2)
        with r_l: st.markdown(f"<div class='report-box'><h4 style='color:#87CEEB;'>📋 {acc_name} 계좌 총평</h4><p>현재 포트폴리오는 연구 자료 가이드라인에 따라 견조하게 관리되고 있습니다. 2026년 Target 달성까지 보유를 지속하며 시장 대비 초과 수익을 추구합니다.</p></div>", unsafe_allow_html=True)
        with r_r: st.markdown("<div class='report-box'><h4 style='color:#FF4B4B;'>🌍 업황 대응 전략</h4><p>거시 경제 변동성에 대비하여 배당주와 성장주의 균형을 유지합니다. 특히 반도체 선단 공정 장비 및 주주 환원 강화주에 집중하여 하방 경직성을 확보합니다.</p></div>", unsafe_allow_html=True)

        acc_news = get_acc_news(sub_df['종목명'].unique().tolist())
        if acc_news:
            news_html = " ".join([f"<div style='margin-bottom:8px;'>[{n['name']}] <a href='{n['url']}' target='_blank' class='news-link' style='color:white; text-decoration:none;'>{n['title']} ↗️</a></div>" for n in acc_news])
            st.markdown(f"<div class='acc-flash-container'><div style='font-weight: bold; color: #FFD700; margin-bottom: 12px;'>🔔 실시간 뉴스 및 공시</div>{news_html}</div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"v36.21 가디언 프리시전 리스토어 | {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
