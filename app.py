import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 구글 시트 연결
st.set_page_config(page_title="가족 투자 대시보드 v12.1", layout="wide")

# 사이드바에서 캐시 제거 및 새로고침 버튼
if st.sidebar.button("🔄 전체 시스템 초기화 및 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [상단] 데이터 로드 엔진 (최후의 수단: ttl=0 적용) ---
try:
    # 1. 메인 종목 데이터 (첫 번째 탭)
    full_df = conn.read(ttl="1m")
    
    # 2. 일일 트렌드 데이터 (이름으로 읽되, 캐시를 0으로 설정하여 즉시 반영)
    try:
        # worksheet 이름을 다시 한번 확인하세요: "daily_trend"
        history_df = conn.read(worksheet="daily_trend", ttl=0) 
    except Exception as e:
        history_df = pd.DataFrame()
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

# 진단용 코드 (왼쪽 사이드바에서 숫자 확인용)
st.sidebar.write(f"🔍 트렌드 데이터 행 수: {len(history_df)}")

# 종목 코드 매핑
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220",
    "현대글로비스": "086280", "현대차2우B": "005387",
    "KODEX200타겟위클리커버드콜": "498400", 
    "에스티팜": "237690", "테스": "095610", "일진전기": "103590",
    "SK스퀘어": "402340"
}

# 시세 크롤링 함수
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

# 표 색상 스타일 함수 (하늘색 적용)
def color_positive_negative(val):
    if isinstance(val, (int, float)):
        color = '#FF4B4B' if val > 0 else '#87CEEB' if val < 0 else '#FFFFFF'
        return f'color: {color}'
    return ''

# 2. 메인 UI
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 투자 실시간 클라우드 대시보드</h1>", unsafe_allow_html=True)

# 계좌 선택 필터
target = st.sidebar.selectbox("📂 계좌 선택", full_df['계좌명'].unique())

# --- 데이터 계산 로직 ---
df = full_df[full_df['계좌명'] == target].copy()

with st.spinner('실시간 시세를 분석 중...'):
    for col in ['수량', '매입단가']:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    
    df['현재가'] = df['종목명'].apply(get_naver_price)
    df['매입금액'] = df['수량'] * df['매입단가']
    df['평가금액'] = df['수량'] * df['현재가']
    df['손익'] = df['평가금액'] - df['매입금액']
    df['수익률'] = (df['손익'] / df['매입금액'] * 100).fillna(0)

# 3. 주요 지표 출력
t_buy, t_eval = df['매입금액'].sum(), df['평가금액'].sum()
t_pl, t_roi = t_eval - t_buy, (t_eval/t_buy - 1)*100 if t_buy > 0 else 0

c1, c2, c3 = st.columns(3)
c1.metric("총 평가액", f"{t_eval:,.0f}원", f"{t_pl:+,.0f}원")
c2.metric("총 매입금액", f"{t_buy:,.0f}원")
c3.metric("누적 수익률", f"{t_roi:.2f}%", f"{t_roi:+.2f}%")

st.markdown("---")

# 4. 차트 섹션
col_l, col_r = st.columns(2)
with col_l:
    st.subheader("🍩 종목별 자산 비중")
    fig = px.pie(df, values='평가금액', names='종목명', hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r)
    st.plotly_chart(fig, use_container_width=True)
with col_r:
    st.subheader("📈 종목별 수익률 현황")
    max_val = max(abs(df['수익률']).max(), 1) 
    fig_bar = px.bar(df.sort_values('수익률'), x='수익률', y='종목명', orientation='h',
                     color='수익률', 
                     color_continuous_scale=[[0, '#87CEEB'], [0.5, '#FFFFFF'], [1, '#FF4B4B']], 
                     range_color=[-max_val, max_val])
    fig_bar.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white")
    st.plotly_chart(fig_bar, use_container_width=True)

# 5. 상세 데이터 표
st.subheader(f"📑 {target} 상세 현황")
st.dataframe(
    df[['종목명', '수량', '매입단가', '현재가', '평가금액', '손익', '수익률']].style
    .map(color_positive_negative, subset=['손익', '수익률'])
    .format({'매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'}),
    hide_index=True, use_container_width=True
)

# 6. 시장 대비 성과 추이 (KOSPI vs 전 계좌)
if not history_df.empty and len(history_df) >= 1:
    st.divider()
    st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")
    
    # 데이터 타입 강제 변환 (에러 방지)
    for col in ['KOSPI', '서은수익률', '서희수익률', '큰스님수익률']:
        if col in history_df.columns:
            history_df[col] = pd.to_numeric(history_df[col], errors='coerce').fillna(0)

    # 데이터 정규화 (첫날을 100으로 기준)
    first_kospi = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
    history_df['KOSPI_IDX'] = (history_df['KOSPI'] / first_kospi) * 100
    
    # 계좌별 지수화
    history_df['SE_IDX'] = 100 + history_df['서은수익률'] - history_df['서은수익률'].iloc[0]
    history_df['SH_IDX'] = 100 + history_df['서희수익률'] - history_df['서희수익률'].iloc[0]
    history_df['KS_IDX'] = 100 + history_df['큰스님수익률'] - history_df['큰스님수익률'].iloc[0]

    fig_trend = go.Figure()
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['KOSPI_IDX'], name='KOSPI 지수', line=dict(dash='dash', color='gray')))
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['SE_IDX'], name='서은투자', line=dict(color='#FF4B4B', width=3)))
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['SH_IDX'], name='서희투자', line=dict(color='#87CEEB', width=3)))
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['KS_IDX'], name='큰스님투자', line=dict(color='#00FF00', width=3)))

    fig_trend.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white",
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig_trend, use_container_width=True)
else:
    st.info("💡 'daily_trend' 탭의 데이터를 읽어오는 중이거나 데이터가 비어 있습니다. (시트 이름을 확인해 주세요)")

st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
