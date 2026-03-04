import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import io
import plotly.graph_objects as go  # 이 줄을 추가하세요!

# 1. 설정 및 구글 시트 연결
st.set_page_config(page_title="가족 투자 대시보드 v11.1", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

# --- 1. 메인 종목 데이터 읽기 (full_df 정의) ---
try:
    # 기본 시트에서 종목 리스트를 가져옵니다.
    full_df = conn.read(ttl="1m")
except Exception as e:
    st.error(f"메인 종목 데이터를 읽어오지 못했습니다: {e}")
    st.stop()

# --- 2. 일일 트렌드 데이터 읽기 (history_df 정의) ---
try:
    # 사용자님이 만드신 'daily_trend' 탭을 정확히 읽어옵니다.
    history_df = conn.read(worksheet="daily_trend", ttl="1m")
except Exception as e:
    # 시트가 아직 비어있거나 생성 중일 때 에러로 멈추지 않게 합니다.
    st.info("구글 시트의 'daily_trend' 데이터를 기다리고 있습니다.")
    history_df = pd.DataFrame()

if not history_df.empty:
    st.divider()
    st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")

    # 데이터 정규화 (시작점을 100으로 맞춤)
    first_kospi = history_df['KOSPI'].iloc[0]
    history_df['KOSPI_IDX'] = (history_df['KOSPI'] / first_kospi) * 100
    
    # 각 계좌별 지수화
    history_df['SE_IDX'] = 100 + history_df['서은수익률'] - history_df['서은수익률'].iloc[0]
    history_df['SH_IDX'] = 100 + history_df['서희수익률'] - history_df['서희수익률'].iloc[0]
    history_df['KS_IDX'] = 100 + history_df['큰스님수익률'] - history_df['큰스님수익률'].iloc[0]

    fig_trend = go.Figure()
    # KOSPI (회색 점선)
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['KOSPI_IDX'], name='KOSPI 지수', line=dict(dash='dash', color='gray')))
    # 계좌별 실선
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['SE_IDX'], name='서은투자', line=dict(color='#FF4B4B', width=3)))
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['SH_IDX'], name='서희투자', line=dict(color='#87CEEB', width=3)))
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['KS_IDX'], name='큰스님투자', line=dict(color='#00FF00', width=3))) # 연두색

    fig_trend.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white")
    st.plotly_chart(fig_trend, use_container_width=True)
    
# 종목 코드 매핑
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220",
    "현대글로비스": "086280", "현대차2우B": "005387",
    "KODEX200타겟위클리커버드콜": "498400", 
    "에스티팜": "237690", "테스": "095610", "일진전기": "103590",
    "SK스퀘어": "402340"
}

# 시세 크롤링 함수 (이름 청소 기능 포함)
def get_naver_price(name):
    clean_name = str(name).strip().replace(" ", "") # 공백 제거
    code = STOCK_CODES.get(clean_name)
    if not code: return 0
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        price = soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text
        return int(price.replace(",", ""))
    except: return 0

# 표 색상 스타일 함수 (플러스 빨강, 마이너스 파랑)
def color_positive_negative(val):
    if isinstance(val, (int, float)):
        # 플러스는 밝은 빨강(#FF4B4B), 마이너스는 화사한 하늘색(#87CEEB)
        color = '#FF4B4B' if val > 0 else '#87CEEB' if val < 0 else '#FFFFFF'
        return f'color: {color}'
    return ''
    
# 2. 메인 UI 및 데이터 처리
st.markdown(f"<h1 style='text-align: center; color: #002060;'>🌐 가족 투자 실시간 클라우드 대시보드</h1>", unsafe_allow_html=True)

target = st.sidebar.selectbox("📂 계좌 선택", full_df['계좌명'].unique())

if st.sidebar.button("🔄 시세/데이터 강제 새로고침"):
    st.cache_data.clear()
    st.rerun()

# --- 데이터 계산 로직 시작 ---
df = full_df[full_df['계좌명'] == target].copy()

with st.spinner('데이터를 분석 중입니다...'):
    # [중요] 글자 타입을 숫자로 강제 변환 (에러 방지)
    df['수량'] = pd.to_numeric(df['수량'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['매입단가'] = pd.to_numeric(df['매입단가'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    
    # 시세 및 금액 계산
    df['현재가'] = df['종목명'].apply(get_naver_price)
    df['매입금액'] = df['수량'] * df['매입단가']
    df['평가금액'] = df['수량'] * df['현재가']
    df['손익'] = df['평가금액'] - df['매입금액']
    
    # 수익률 계산 ($$ROI = \frac{Profit}{Buy} \times 100$$)
    df['수익률'] = (df['손익'] / df['매입금액']) * 100
    df['수익률'] = df['수익률'].fillna(0)

# 3. 화면 출력 (여기서부터 색상 적용)
t_buy, t_eval = df['매입금액'].sum(), df['평가금액'].sum()
t_pl, t_roi = t_eval - t_buy, (t_eval/t_buy - 1)*100 if t_buy > 0 else 0

c1, c2, c3 = st.columns(3)
# delta_color="normal"을 쓰면 기본 빨강/파랑으로 표시됩니다.
c1.metric("총 평가액", f"{t_eval:,.0f}원", f"{t_pl:+,.0f}원")
c2.metric("총 매입금액", f"{t_buy:,.0f}원")
c3.metric("누적 수익률", f"{t_roi:.2f}%", f"{t_roi:+.2f}%")

# 차트 섹션
st.markdown("---")
col_l, col_r = st.columns(2)
with col_l:
    st.subheader("🍩 종목별 자산 비중")
    fig = px.pie(df, values='평가금액', names='종목명', hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r)
    st.plotly_chart(fig, use_container_width=True)
with col_r:
    st.subheader("📈 종목별 수익률 현황")
    
    # 수익률 절대값의 최대치를 기준으로 범위를 설정하여 0이 항상 가운데 오게 합니다.
    max_val = max(abs(df['수익률']).max(), 1) 
    
    fig_bar = px.bar(df.sort_values('수익률'), x='수익률', y='종목명', orientation='h',
                     color='수익률', 
                     # 하늘색(음수) -> 흰색(0) -> 빨간색(양수) 순으로 색상 변경
                     color_continuous_scale=[[0, '#87CEEB'], [0.5, '#FFFFFF'], [1, '#FF4B4B']], 
                     range_color=[-max_val, max_val])
    
    fig_bar.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white")
    st.plotly_chart(fig_bar, use_container_width=True)
    
# 상세 표 (스타일 적용)
st.subheader(f"📑 {target} 상세 내역")
st.dataframe(
    df[['종목명', '수량', '매입단가', '현재가', '평가금액', '손익', '수익률']].style
    .applymap(color_positive_negative, subset=['손익', '수익률'])
    .format({'매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'}),
    hide_index=True, use_container_width=True
)


st.info(f"💡 업데이트: {datetime.now().strftime('%H:%M:%S')}")

st.divider() # 구분선 추가
st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 계좌)")

if not history_df.empty:
    # 1. 데이터 정규화 (첫날을 100으로 기준)
    # $$NormalizedValue_t = \frac{Value_t}{Value_{start}} \times 100$$
    first_kospi = history_df['KOSPI'].iloc[0]
    history_df['KOSPI_IDX'] = (history_df['KOSPI'] / first_kospi) * 100
    
    # 수익률은 100을 기준으로 변동폭을 더해줍니다.
    history_df['SE_IDX'] = 100 + history_df['서은수익률'] - history_df['서은수익률'].iloc[0]
    history_df['SH_IDX'] = 100 + history_df['서희수익률'] - history_df['서희수익률'].iloc[0]

    # 2. 차트 생성
    fig_trend = go.Figure()

    # 코스피 추이 (회색 점선)
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['KOSPI_IDX'], 
                                   name='KOSPI 지수', line=dict(dash='dash', color='gray')))
    
    # 서은투자 추이 (빨간색 실선)
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['SE_IDX'], 
                                   name='서은투자', line=dict(color='#FF4B4B', width=3)))
    
    # 서희투자 추이 (하늘색 실선)
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['SH_IDX'], 
                                   name='서희투자', line=dict(color='#87CEEB', width=3)))

    # 3. 차트 디자인 (다크 모드 최적화)
    fig_trend.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font_color="white",
        xaxis=dict(showgrid=False, title="날짜"),
        yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.1)', title="지수 (시작일=100)"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0)
    )
    
    st.plotly_chart(fig_trend, use_container_width=True)
else:
    st.info("구글 시트에 'daily_trend' 탭을 만들고 데이터를 입력하면 차트가 나타납니다.")



