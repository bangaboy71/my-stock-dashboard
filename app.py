import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 구글 시트 연결
st.set_page_config(page_title="가족 투자 대시보드 v12.4", layout="wide")

if st.sidebar.button("🔄 전체 시스템 초기화 및 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [상단] 데이터 로드 엔진 (HTTP 400 방어 로직) ---
try:
    # 1. 메인 종목 데이터 읽기 (첫 번째 탭)
    full_df = conn.read(ttl="1m")
    
    # 2. 트렌드 데이터 읽기 (이름 대신 '인덱스' 우선 시도)
    try:
        # worksheet=1은 왼쪽에서 두 번째 탭을 의미합니다.
        history_df = conn.read(worksheet=1, ttl=0)
        
        # 만약 순서로 읽기 실패 시 이름으로 재시도
        if history_df.empty:
            history_df = conn.read(worksheet="daily_trend", ttl=0)
            
    except Exception as e:
        # 에러 발생 시 로그 표시
        st.sidebar.error(f"⚠️ 탭 읽기 오류: {str(e)[:40]}...")
        history_df = pd.DataFrame()

except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

# 🔍 [진단 섹션] 사이드바 정보
st.sidebar.markdown("---")
st.sidebar.write(f"📈 트렌드 행 수: **{len(history_df)}**")

if not history_df.empty:
    st.sidebar.success("✅ 데이터를 성공적으로 불러왔습니다!")
    # 실제 불러온 데이터의 첫 줄 제목들을 확인 (오타 검수용)
    st.sidebar.write("항목명 확인:", list(history_df.columns))

# --- [중단] 기존 분석 로직 (동일) ---
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220",
    "현대글로비스": "086280", "현대차2우B": "005387",
    "KODEX200타겟위클리커버드콜": "498400", 
    "에스티팜": "237690", "테스": "095610", "일진전기": "103590",
    "SK스퀘어": "402340"
}

def get_naver_price(name):
    clean_name = str(name).strip().replace(" ", "")
    code = STOCK_CODES.get(clean_name)
    if not code: return 0
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        price = soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text
        return int(price.replace(",", ""))
    except: return 0

def color_positive_negative(val):
    if isinstance(val, (int, float)):
        color = '#FF4B4B' if val > 0 else '#87CEEB' if val < 0 else '#FFFFFF'
        return f'color: {color}'
    return ''

st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 투자 실시간 클라우드 대시보드</h1>", unsafe_allow_html=True)

target = st.sidebar.selectbox("📂 계좌 선택", full_df['계좌명'].unique())
df = full_df[full_df['계좌명'] == target].copy()

with st.spinner('시세를 가져오는 중...'):
    for col in ['수량', '매입단가']:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['현재가'] = df['종목명'].apply(get_naver_price)
    df['매입금액'] = df['수량'] * df['매입단가']
    df['평가금액'] = df['수량'] * df['현재가']
    df['손익'] = df['평가금액'] - df['매입금액']
    df['수익률'] = (df['손익'] / df['매입금액'] * 100).fillna(0)

# 주요 지표 및 차트 (중략 - 기존과 동일)
t_buy, t_eval = df['매입금액'].sum(), df['평가금액'].sum()
t_pl, t_roi = t_eval - t_buy, (t_eval/t_buy - 1)*100 if t_buy > 0 else 0

c1, c2, c3 = st.columns(3)
c1.metric("총 평가액", f"{t_eval:,.0f}원", f"{t_pl:+,.0f}원")
c2.metric("총 매입금액", f"{t_buy:,.0f}원")
c3.metric("누적 수익률", f"{t_roi:.2f}%", f"{t_roi:+.2f}%")

st.markdown("---")
# (자산 비중 및 종목별 수익률 차트 부분)
col_l, col_r = st.columns(2)
with col_l:
    st.subheader("🍩 종목별 자산 비중")
    fig = px.pie(df, values='평가금액', names='종목명', hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r)
    st.plotly_chart(fig, use_container_width=True)
with col_r:
    st.subheader("📈 종목별 수익률 현황")
    max_val = max(abs(df['수익률']).max(), 1) 
    fig_bar = px.bar(df.sort_values('수익률'), x='수익률', y='종목명', orientation='h',
                     color='수익률', color_continuous_scale=[[0, '#87CEEB'], [0.5, '#FFFFFF'], [1, '#FF4B4B']], 
                     range_color=[-max_val, max_val])
    fig_bar.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white")
    st.plotly_chart(fig_bar, use_container_width=True)

# --- [하단] 시장 대비 성과 추이 차트 ---
if not history_df.empty:
    st.divider()
    st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")
    
    # 숫자 변환 및 정제
    for col in ['KOSPI', '서은수익률', '서희수익률', '큰스님수익률']:
        if col in history_df.columns:
            history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', '').replace('%', ''), errors='coerce').fillna(0)

    if 'KOSPI' in history_df.columns and not history_df.empty:
        # 첫날을 100으로 기준화
        first_kospi = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        history_df['KOSPI_IDX'] = (history_df['KOSPI'] / first_kospi) * 100
        
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['KOSPI_IDX'], name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        
        # 각 계좌별 선 추가
        colors = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
        for col, color in colors.items():
            if col in history_df.columns:
                idx_val = 100 + history_df[col] - history_df[col].iloc[0]
                fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=idx_val, name=col.replace('수익률',''), line=dict(color=color, width=3)))

        fig_trend.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white",
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_trend, use_container_width=True)
else:
    st.info("💡 탭을 찾았으나 데이터가 없거나, 탭 순서(두 번째)를 확인해 주세요.")

st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
