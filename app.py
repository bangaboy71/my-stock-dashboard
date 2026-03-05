import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta, timezone
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 통합 자산 관제탑 v14.1", layout="wide")

# --- [설정 유지] ---
STOCKS_GID = "301897027"
TREND_GID = "1055700982"

# 한국 시간(KST) 설정 로직
def get_now_kst():
    # 서버(UTC) 시간에 9시간을 더해 한국 시간을 만듭니다.
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()

if st.sidebar.button("🔄 실시간 시세 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [데이터 로드 엔진] ---
try:
    full_df = conn.read(worksheet=STOCKS_GID, ttl="1m")
    try:
        history_df = conn.read(worksheet=TREND_GID, ttl=0)
    except:
        history_df = pd.DataFrame()
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

# --- [통합 시장 시세 엔진] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_combined_price(name):
    clean_name = str(name).strip().replace(" ", "")
    code = STOCK_CODES.get(clean_name)
    if not code: return 0
    
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. 기본 KRX 현재가 추출
        price_text = soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text
        current_price = int(price_text.replace(",", ""))
        
        # 2. NXT/시간외 가격 보정 (장외 시간일 경우에만 시도)
        # 현재 한국 시간 기준으로 판단
        kst_time = now_kst.time()
        if kst_time < time(9, 0) or kst_time > time(15, 30):
            ov_section = soup.find("div", {"class": "aside_invest_info"})
            if ov_section:
                ov_price = ov_section.find("em").text.replace(",", "")
                if ov_price.isdigit():
                    return int(ov_price)
        
        return current_price
    except:
        return 0

# 데이터 전처리
with st.spinner('실시간 시세를 분석 중입니다...'):
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    full_df['현재가'] = full_df['종목명'].apply(get_combined_price)
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# --- UI 렌더링 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 통합 자산 관제탑 (NXT 대응)</h1>", unsafe_allow_html=True)

# 2. 사이드바 시장 상태 표시 (한국 시간 기준)
kst_t = now_kst.time()
if time(8, 0) <= kst_t < time(9, 0):
    st.sidebar.warning(f"🌙 NXT 프리마켓 거래 중 ({now_kst.strftime('%H:%M')})")
elif time(9, 0) <= kst_t <= time(15, 30):
    st.sidebar.success(f"☀️ 정규 시장 거래 중 ({now_kst.strftime('%H:%M')})")
elif time(15, 50) <= kst_t <= time(20, 0):
    st.sidebar.warning(f"🌙 NXT 애프터마켓 거래 중 ({now_kst.strftime('%H:%M')})")
else:
    st.sidebar.info(f"💤 시장 마감 ({now_kst.strftime('%H:%M')})")

tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [Tab 0] 총괄 (기존 로직 유지) ---
with tabs[0]:
    # ... (생략 없이 어제 로직 그대로 들어갑니다)
    total_buy, total_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    total_profit = total_eval - total_buy
    total_roi = (total_profit / total_buy * 100) if total_buy > 0 else 0
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{total_eval:,.0f}원", f"{total_profit:+,.0f}원")
    m2.metric("총 투자 원금", f"{total_buy:,.0f}원")
    m3.metric("통합 누적 수익률", f"{total_roi:.2f}%")
    st.markdown("---")
    summary_by_acc = full_df.groupby('계좌명').agg({'매입금액': 'sum', '평가금액': 'sum', '손익': 'sum'}).reset_index()
    summary_by_acc['누적 수익률'] = (summary_by_acc['손익'] / summary_by_acc['매입금액'] * 100).fillna(0)
    st.dataframe(summary_by_acc[['계좌명', '매입금액', '평가금액', '손익', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '누적 수익률']).format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적 수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)
    if not history_df.empty:
        st.divider()
        st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")
        for col in history_df.columns:
            if col != 'Date': history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        fig_t = go.Figure()
        bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        fig_t.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        acc_colors = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
        for col, color in acc_colors.items():
            if col in history_df.columns:
                nv = 100 + history_df[col] - history_df[col].iloc[0]
                fig_t.add_trace(go.Scatter(x=history_df['Date'], y=nv, name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig_t.update_layout(height=450, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_t, use_container_width=True)

# --- [개별 계좌 탭 공통 로직] ---
def render_account_tab(account_name, tab_object):
    with tab_object:
        sub_df = full_df[full_df['계좌명'] == account_name].copy()
        sub_df['수익률'] = ((sub_df['평가금액'] / sub_df['매입금액'] - 1) * 100).fillna(0)
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        a_profit = a_eval - a_buy
        a_roi = (a_profit / a_buy * 100) if a_buy > 0 else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_profit:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        c3.metric("누적 수익률", f"{a_roi:.2f}%")
        col_l, col_r = st.columns(2)
        with col_l:
            st.plotly_chart(px.pie(sub_df, values='평가금액', names='종목명', hole=0.4, title="종목 비중", color_discrete_sequence=px.colors.sequential.Blues_r), use_container_width=True)
        with col_r:
            m = max(abs(sub_df['수익률']).max(), 1)
            fig_bar = px.bar(sub_df.sort_values('수익률'), x='수익률', y='종목명', orientation='h', title="종목별 수익률", color='수익률', color_continuous_scale=[[0, '#87CEEB'], [0.5, '#FFFFFF'], [1, '#FF4B4B']], range_color=[-m, m])
            st.plotly_chart(fig_bar, use_container_width=True)
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '평가금액', '손익', '수익률']].style.map(color_positive_negative, subset=['손익', '수익률']).format({'매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])

st.divider()
st.info("🕵️ **보유종목 기반 시장 평론:** 현재 시간은 한국 기준입니다. 정규장 및 NXT 시간대에 맞춰 실시간 시세를 모니터링합니다.")
st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST)")
