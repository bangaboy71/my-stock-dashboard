import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import yfinance as yf

# --- [1. 설정 및 UI 스타일] ---
st.set_page_config(page_title="가족 자산 성장 관제탑 v43.00", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .report-box { padding: 20px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.02); margin-bottom: 15px; }
    .news-card { margin-bottom: 10px; padding: 12px; border-radius: 8px; background: rgba(255,255,255,0.02); }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 전역 설정 및 상수] ---
GLOBAL_RENAME_MAP = {'전일대비손익': '전일대비(원)', '전일대비변동율': '전일대비(%)'}
GLOBAL_DISPLAY_COLS = ['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '손익', '전일대비(원)', '전일대비(%)', '누적수익률']

STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "테스": "095610", "LG에너지솔루션": "373220",
    "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400",
    "에스티팜": "237690", "일진전기": "103590", "SK스퀘어": "402340", "SOL팔란티어커버드콜OTM채권혼합": "0040Y0"
}

DIVIDEND_SCHEDULE = {
    "삼성전자": [5, 8, 11, 4], "KT&G": [5, 8, 11, 4], "현대차2우B": [5, 8, 11, 4],
    "현대글로비스": [4, 8], "KODEX200타겟위클리커버드콜": list(range(1, 13)), "SOL팔란티어커버드콜OTM채권혼합": list(range(1, 13))
}

RESEARCH_DATA = {
    "삼성전자": {"metrics": [("영업이익률", "16.8%", "38.5%")], "implications": ["HBM3E 양산 본격화"]},
    "KODEX200타겟위클리커버드콜": {"metrics": [("목표 분배율", "연 12%", "월 1%↑")], "implications": ["매주 옵션 프리미엄 확보"]}
}

# --- [3. 헬퍼 함수 및 엔진] ---
def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))

def get_cashflow_grade(amount):
    if amount >= 1000000: return "💎 Diamond"
    elif amount >= 300000: return "🥇 Gold"
    elif amount >= 100000: return "🥈 Silver"
    else: return "🥉 Bronze"

def get_current_prices(df):
    if df.empty: return df
    tickers = df['종목코드'].unique()
    price_map = {}
    for t in tickers:
        f_t = str(t).strip()
        if f_t.isdigit(): f_t += ".KS"
        try:
            stock = yf.Ticker(f_t)
            data = stock.history(period="1d")
            price_map[t] = data['Close'].iloc[-1] if not data.empty else 0
        except: price_map[t] = 0
    df['현재가'] = df['종목코드'].map(price_map)
    return df

def get_stock_news(name):
    code = STOCK_CODES.get(str(name).strip())
    if not code: return []
    news_list = []
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        titles = soup.find_all('td', class_='title')
        dates = soup.find_all('td', class_='date')
        for i in range(min(len(titles), 5)):
            date_str = dates[i].text.strip()
            is_recent = "전" in date_str or (len(date_str) > 10 and (datetime.now() - datetime.strptime(date_str, '%Y.%m.%d %H:%M')).total_seconds() < 86400)
            news_list.append({'title': titles[i].text.strip(), 'link': "https://finance.naver.com" + titles[i].find('a')['href'], 'date': date_str, 'is_recent': is_recent})
    except: pass
    return news_list

def find_matching_col(df, account, stock=None):
    prefix = account.replace("투자", "").strip()
    target = f"{prefix}{stock}수익률" if stock else f"{prefix}수익률"
    for col in df.columns:
        if target.replace(" ", "") in str(col).replace(" ", ""): return col
    return None

# --- [4. 계좌별 탭 렌더링 함수 (Blueprint)] ---
def render_account_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = actual_df[actual_df['계좌명'] == acc_name].copy()
        if sub_df.empty:
            st.warning(f"{acc_name} 데이터가 없습니다.")
            return

        # 연산
        a_eval, a_buy = sub_df['평가금액'].sum(), sub_df['매입금액'].sum()
        a_diff = sub_df['전일대비손익'].sum()
        a_monthly_tax = (sub_df['예상배당금'].sum() * 0.846) / 12

        # HUD
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("평가액", f"{a_eval:,.0f}원", delta=f"{a_diff:+,.0f}원")
        m2.metric("수익률", f"{(a_eval/a_buy-1)*100:+.2f}%")
        m3.metric("월 수령액(세후)", f"{a_monthly_tax:,.0f}원")
        m4.metric("현금흐름 등급", get_cashflow_grade(a_monthly_tax))

        # 테이블
        st.divider()
        st.dataframe(sub_df.rename(columns=GLOBAL_RENAME_MAP)[GLOBAL_DISPLAY_COLS], use_container_width=True, hide_index=True)

        # 분석 섹션
        st.divider()
        sel = st.selectbox(f"🔍 {acc_name} 종목 분석", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        s_row = sub_df[sub_df['종목명'] == sel].iloc[0]

        # 리스크 가이드 및 성과 차트
        c_left, c_right = st.columns([1, 1])
        with c_left:
            st.info(f"🛡️ 손절 가이드: {float(s_row['매입단가'])*0.85:,.0f}원 | 🚨 익절 가이드: {float(s_row.get('매입후최고가', s_row['현재가']))*0.8:,.0f}원")
            if not history_df.empty:
                fig = go.Figure()
                h_dt = history_df['Date'].dt.date.astype(str)
                fig.add_trace(go.Scatter(x=h_dt, y=history_df['KOSPI_Relative'], name='KOSPI', line=dict(dash='dash')))
                acc_col = find_matching_col(history_df, acc_name)
                if acc_col: fig.add_trace(go.Scatter(x=h_dt, y=history_df[acc_col], name='계좌', line=dict(width=3)))
                st.plotly_chart(fig, use_container_width=True)

        with c_right:
            st.markdown(f"##### 📰 {sel} 실시간 뉴스")
            for item in get_stock_news(sel):
                st.html(f"<div class='news-card' style='border-left:4px solid {'#FFD700' if item['is_recent'] else '#87CEEB'};'>{'<b style=\"color:#FFD700\">[NEW]</b> ' if item['is_recent'] else ''}<a href='{item['link']}'>{item['title']}</a></div>")

# --- [5. 데이터 로드 엔진] ---
conn = st.connection("gsheets", type=GSheetsConnection)
try:
    df_stock = conn.read(worksheet="종목 현황", ttl="1m")
    df_pension = conn.read(worksheet="연금자산", ttl="1m")
    history_df = conn.read(worksheet="trend", ttl=0)
    raw_df = pd.concat([df_stock, df_pension], ignore_index=True)
    
    # 기초 연산 및 가격 수집
    full_df_with_price = get_current_prices(raw_df)
    full_df_with_price['매입금액'] = full_df_with_price['수량'] * full_df_with_price['매입단가']
    full_df_with_price['평가금액'] = full_df_with_price['수량'] * full_df_with_price['현재가']
    full_df_with_price['손익'] = full_df_with_price['평가금액'] - full_df_with_price['매입금액']
    full_df_with_price['예상배당금'] = full_df_with_price['수량'] * full_df_with_price['주당 배당금']
    full_df_with_price['전일대비손익'] = 0 # 간소화 (실제 전일종가 크롤링 추가 가능)
    full_df_with_price['누적수익률'] = (full_df_with_price['손익'] / full_df_with_price['매입금액'] * 100).fillna(0)
    full_df_with_price['전일대비변동율'] = 0

    actual_df = full_df_with_price[full_df_with_price['상태'] == '보유'].copy()
    watch_df = full_df_with_price[full_df_with_price['상태'] == '예정'].copy()
    full_df = actual_df
except Exception as e:
    st.error(f"데이터 로드 실패: {e}"); st.stop()

# --- [6. 메인 화면 출력] ---
st.title("🌐 AI 금융 통합 관제탑 v43.00")
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자", "🏢 연금자산"])

with tabs[0]:
    t_eval, t_buy = actual_df['평가금액'].sum(), actual_df['매입금액'].sum()
    st.columns(4)[0].metric("가족 총 평가액", f"{t_eval:,.0f}원", delta=f"{t_eval-t_buy:,.0f}원")
    
    # 관심 레이더 (총괄 탭 하단에만 표시)
    if not watch_df.empty:
        st.divider(); st.subheader("📡 매입 예정 종목 관심 레이더")
        watch_df['진입매력도'] = ((watch_df['목표가']/watch_df['현재가']-1)*100).fillna(0)
        st.dataframe(watch_df[['계좌명', '종목명', '현재가', '목표가', '진입매력도']], use_container_width=True)

# 개별 계좌 호출 (설계도가 위에 있어 NameError 해결)
render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])

with tabs[4]:
    st.subheader("🏢 연금 및 절세 자산 관리")
    p_df = actual_df[actual_df['계좌명'].isin(["IRP", "ISA", "연금저축", "회사DC"])]
    if not p_df.empty:
        safe_ratio = (p_df[p_df['자산구분'].str.contains('안전', na=False)]['평가금액'].sum() / p_df['평가금액'].sum() * 100)
        st.metric("연금 평가액", f"{p_df['평가금액'].sum():,.0f}원", delta=f"안전자산 {safe_ratio:.1f}%")
        st.dataframe(p_df[GLOBAL_DISPLAY_COLS], use_container_width=True)

# 사이드바
with st.sidebar:
    if st.button("🔄 실시간 동기화"): st.cache_data.clear(); st.rerun()
    st.caption(f"Last Sync: {get_now_kst().strftime('%H:%M:%S')}")
