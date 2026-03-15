import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import yfinance as yf

# --- [1. 설정 및 UI 스타일] ---
st.set_page_config(page_title="가족 자산 성장 관제탑 v40.94", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 350px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 25px; color: white; }
    .news-card { margin-bottom: 10px; padding: 12px; border-radius: 8px; background: rgba(255,255,255,0.02); }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 전역 설정 및 매핑 데이터] ---
GLOBAL_RENAME_MAP = {'전일대비손익': '전일대비(원)', '전일대비변동율': '전일대비(%)'}
GLOBAL_DISPLAY_COLS = ['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '손익', '전일대비(원)', '전일대비(%)', '누적수익률']

STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "테스": "095610", "LG에너지솔루션": "373220",
    "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400",
    "에스티팜": "237690", "일진전기": "103590", "SK스퀘어": "402340"
}

DIVIDEND_SCHEDULE = {
    "삼성전자": [5, 8, 11, 4], "KT&G": [5, 8, 11, 4], "현대차2우B": [5, 8, 11, 4],
    "현대글로비스": [4, 8], "테스": [4], "에스티팜": [4], "일진전기": [4],
    "KODEX200타겟위클리커버드콜": list(range(1, 13))
}

RESEARCH_DATA = {
    "삼성전자": {"metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%")], "implications": ["HBM3E 양산 본격화"]},
    "KT&G": {"metrics": [("영업이익률", "20.5%", "20.8%")], "implications": ["자사주 소각 가속화"]},
    "테스": {"metrics": [("영업이익률", "10.7%", "19.0%")], "implications": ["선단공정 장비 수요 폭증"]},
    "KODEX200타겟위클리커버드콜": {"metrics": [("목표 분배율", "연 12%", "월 1%↑")], "implications": ["매주 옵션 매도를 통한 현금 흐름"]}
    # ... (기존 RESEARCH_DATA 내용 유지)
}

# --- [3. 코어 엔진 함수] ---

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))

def get_cashflow_grade(amount):
    if amount >= 1000000: return "💎 Diamond"
    elif amount >= 300000: return "🥇 Gold"
    elif amount >= 100000: return "🥈 Silver"
    else: return "🥉 Bronze"

@st.cache_data(ttl=60) # 지수 정보 1분 캐싱
def get_market_status():
    data = {"KOSPI": {"val": "-", "pct": "0.00%", "color": "#ffffff"}, "KOSDAQ": {"val": "-", "pct": "0.00%", "color": "#ffffff"}, "USD/KRW": {"val": "-", "pct": "0원", "color": "#ffffff"}, "VOLUME": {"val": "-", "pct": "천주", "color": "#ffffff"}}
    header = {'User-Agent': 'Mozilla/5.0'}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers=header, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            now_el = soup.select_one("#now_value")
            if now_el: data[code]["val"] = now_el.get_text(strip=True)
            diff_el = soup.select_one("#change_value_and_rate")
            if diff_el:
                raw_txt = diff_el.get_text(" ", strip=True)
                for word in ["상승", "하락", "보합"]: raw_txt = raw_txt.replace(word, "")
                if "+" in raw_txt: data[code]["color"] = "#FF4B4B"
                elif "-" in raw_txt: data[code]["color"] = "#87CEEB"
                data[code]["pct"] = raw_txt.strip()
    except: pass
    return data

def get_stock_data(name): # 네이버 단일 종목 크롤링
    code = STOCK_CODES.get(str(name).replace(" ", ""))
    if not code: return 0, 0
    try:
        res = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        now_p = int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
        prev_p = int(soup.find("td", {"class": "first"}).find("span", {"class": "blind"}).text.replace(",", ""))
        return now_p, prev_p
    except: return 0, 0

def get_current_prices_yfinance(df): # yfinance 일괄 수집
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
    df['현재가_yf'] = df['종목코드'].map(price_map)
    return df

def get_stock_news(name):
    code = STOCK_CODES.get(str(name).replace(" ", ""))
    if not code: return []
    news_list = []
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        titles = soup.find_all('td', class_='title')
        dates = soup.find_all('td', class_='date')
        for i in range(min(len(titles), 6)):
            date_str = dates[i].get_text(strip=True)
            is_recent = "전" in date_str or (len(date_str) > 10 and (datetime.now() - datetime.strptime(date_str, '%Y.%m.%d %H:%M')).total_seconds() < 86400)
            news_list.append({'title': titles[i].find('a').get_text(strip=True), 'link': "https://finance.naver.com" + titles[i].find('a')['href'], 'date': date_str, 'is_recent': is_recent})
    except: pass
    return news_list

def find_matching_col(df, account, stock=None):
    prefix = account.replace("투자", "").replace(" ", "")
    target_clean = f"{prefix}{stock}수익률".replace(" ", "") if stock else f"{prefix}수익률".replace(" ", "")
    for col in df.columns:
        if target_clean in str(col).replace(" ", "").replace("_", ""): return col
    return None

# --- [4. 데이터 로드 및 통합 연산 엔진] ---

@st.cache_data(ttl=600) # 10분 캐싱으로 429 에러 방지
def load_base_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_stock = conn.read(worksheet="종목 현황")
    df_pension = conn.read(worksheet="연금자산")
    history_df = conn.read(worksheet="trend", ttl=0)
    return df_stock, df_pension, history_df

# 데이터 프로세싱 통합
df_stock, df_pension, history_df = load_base_data()
raw_df = pd.concat([df_stock, df_pension], ignore_index=True)
raw_df.columns = [c.strip() for c in raw_df.columns]

# 가격 수집 (yfinance 우선)
full_df = get_current_prices_yfinance(raw_df)

# 수치 데이터 정제 및 메인 연산
def process_metrics(df):
    num_cols = ['수량', '매입단가', '목표가', '주당 배당금', '52주최고가', '매입후최고가']
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    
    # 가격 보정 (yf 실패 시 네이버 크롤링) - 효율을 위해 현재가가 0인 것만 시도
    df['현재가'] = df.apply(lambda x: x['현재가_yf'] if x['현재가_yf'] > 0 else get_stock_data(x['종목명'])[0], axis=1)
    df['전일종가'] = df['종목명'].apply(lambda x: get_stock_data(x)[1])
    
    df['매입금액'] = df['수량'] * df['매입단가']
    df['평가금액'] = df['수량'] * df['현재가']
    df['손익'] = df['평가금액'] - df['매입금액']
    df['전일대비손익'] = df['평가금액'] - (df['수량'] * df['전일종가'])
    df['예상배당금'] = df['수량'] * df['주당 배당금']
    df['누적수익률'] = (df['손익'] / df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    df['전일대비변동율'] = (df['전일대비손익'] / (df['평가금액'] - df['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    df['목표대비상승여력'] = df.apply(lambda x: ((x['목표가'] / x['현재가'] - 1) * 100) if x['현재가'] > 0 and x['목표가'] > 0 else 0, axis=1)
    
    if '최초매입일' in df.columns:
        df['최초매입일'] = pd.to_datetime(df['최초매입일'], errors='coerce')
        df['보유일수'] = (datetime.now().replace(hour=0,minute=0,second=0,microsecond=0) - df['최초매입일'].dt.tz_localize(None)).dt.days.fillna(365).clip(lower=1)
    return df

processed_full_df = process_metrics(full_df)
actual_df = processed_full_df[processed_full_df['상태'] == '보유'].copy()
watch_df = processed_full_df[processed_full_df['상태'] == '예정'].copy()

# 성과 추이 전처리
if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')
    base_row = history_df.iloc[0]
    history_df['KOSPI_Relative'] = (history_df['KOSPI'] / base_row['KOSPI'] - 1) * 100

# --- [5. 계좌별 탭 렌더링 함수] ---

def render_account_tab(acc_name, tab_obj, yield_col_name):
    with tab_obj:
        sub_df = actual_df[actual_df['계좌명'] == acc_name].copy()
        if sub_df.empty:
            st.warning(f"{acc_name} 데이터가 없습니다."); return

        # 1. 상단 Metric
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        a_diff = sub_df['전일대비손익'].sum()
        a_pct = (a_diff / (a_eval - a_diff) * 100) if (a_eval - a_diff) != 0 else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("계좌 평가액", f"{a_eval:,.0f}원", delta=f"{a_diff:+,.0f}원 ({a_pct:+.2f}%)")
        c2.metric("계좌 매입액", f"{a_buy:,.0f}원")
        c3.metric("계좌 손익", f"{a_eval-a_buy:+,.0f}원")
        c4.metric("계좌 수익률", f"{(a_eval/a_buy-1)*100:+.2f}%", delta=f"{a_pct:+.2f}%p")

        # 2. 보유 종목 테이블
        st.dataframe(sub_df.rename(columns=GLOBAL_RENAME_MAP)[GLOBAL_DISPLAY_COLS].style.apply(lambda x: [
            'color: #FF4B4B' if (i >= 6 and val > 0) else 'color: #87CEEB' if (i >= 6 and val < 0) else '' 
            for i, val in enumerate(x)], axis=1).format({
                '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', 
                '손익': '{:+,.0f}원', '전일대비(원)': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적수익률': '{:+.2f}%'
            }), hide_index=True, use_container_width=True)

        st.divider()

        # 3. 배당 정보
        a_total_div = sub_df['예상배당금'].sum()
        a_monthly_tax = (a_total_div * 0.846) / 12
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("연간 예상 배당금", f"{a_total_div:,.0f}원")
        d2.metric("세후 월 수령액", f"{a_monthly_tax:,.0f}원")
        d3.metric("계좌 배당수익률", f"{(a_total_div/a_eval*100):.2f}%")
        d4.metric("계좌 현금흐름 등급", get_cashflow_grade(a_monthly_tax))

        # 4. 차트 구역
        g_left, g_right = st.columns(2)
        with g_left:
            with st.container(border=True):
                a_monthly_data = {m: 0 for m in range(1, 13)}
                for _, row in sub_df.iterrows():
                    sched = DIVIDEND_SCHEDULE.get(row['종목명'], [4])
                    for m in sched: a_monthly_data[m] += (row['예상배당금']/len(sched))
                fig_a_cal = go.Figure(go.Bar(x=[f"{m}월" for m in range(1, 13)], y=list(a_monthly_data.values()), marker_color='gold'))
                fig_a_cal.update_layout(title="📅 월별 배당 예측", height=300, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig_a_cal, use_container_width=True)
        with g_right:
            with st.container(border=True):
                fig_bar = go.Figure(go.Bar(y=sub_df['종목명'], x=sub_df['평가금액'], orientation='h', marker_color='#87CEEB'))
                fig_bar.update_layout(title="📊 자산 비중", height=300, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig_bar, use_container_width=True)

        # 5. 종목 분석 및 뉴스
        sel = st.selectbox(f"🔍 {acc_name} 종목 분석", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        s_row = sub_df[sub_df['종목명'] == sel].iloc[0]
        
        # (기존 전략 가이드 및 차트 로직 유지)
        res = RESEARCH_DATA.get(sel.replace(" ", ""))
        if res:
            st.info(f"💡 인사이트: {res['implications'][0]}")
        
        news_items = get_stock_news(sel)
        for item in news_items[:4]:
            st.html(f"<div class='news-card' style='border-left:4px solid {'#FFD700' if item['is_recent'] else '#87CEEB'};'><a href='{item['link']}' target='_blank'>{item['title']}</a> <small>{item['date']}</small></div>")

# --- [6. 메인 화면 렌더링] ---

now_kst = get_now_kst()
st.markdown(f"## 🌐 AI 금융 통합 관제탑 <small>v40.94</small>", unsafe_allow_html=True)

# HUD
m_status = get_market_status()
hud_cols = st.columns(4)
for i, (k, v) in enumerate(m_status.items()):
    with hud_cols[i]:
        st.markdown(f"<div style='text-align:center; padding:15px; border-radius:12px; background:rgba(255,255,255,0.03); border:1px solid {v['color']}44;'><div style='color:#aaa; font-size:0.85rem;'>{k}</div><div style='color:{v['color']}; font-size:1.8rem; font-weight:bold;'>{v['val']}</div><div style='color:{v['color']};'>{v['pct']}</div></div>", unsafe_allow_html=True)

tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

with tabs[0]:
    t_eval, t_buy = actual_df['평가금액'].sum(), actual_df['매입금액'].sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("총 누적 손익", f"{t_eval-t_buy:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100:+.2f}%")
    
    st.divider()
    # 계좌별 요약 테이블
    sum_acc = actual_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum', '전일대비손익':'sum'}).reset_index()
    st.dataframe(sum_acc.rename(columns=GLOBAL_RENAME_MAP), use_container_width=True, hide_index=True)

    # 관심 레이더 (탭 0 하단 고정)
    if not watch_df.empty:
        st.divider()
        st.subheader("📡 매입 예정 종목 관심 레이더")
        st.dataframe(watch_df[['계좌명', '종목명', '현재가', '목표가', '목표대비상승여력']].style.format({'현재가': '{:,.0f}원', '목표가': '{:,.0f}원', '목표대비상승여력': '{:+.2f}%'}), hide_index=True, use_container_width=True)

# 개별 탭 호출
render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

# 사이드바 기록 관리 (기존 로직 유지)
with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
    st.caption(f"최종 동기화: {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
