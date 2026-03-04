import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 구글 시트 연결
st.set_page_config(page_title="가족 투자 대시보드 v12.5", layout="wide")

if st.sidebar.button("🔄 시스템 전체 초기화"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [상단] 초강력 데이터 로드 엔진 ---
try:
    # 모든 데이터를 일단 가져옵니다.
    # 만약 특정 탭 지정에서 400 에러가 난다면, 이름 없이 읽는 것이 가장 안전합니다.
    full_df = conn.read(ttl="1m")
    
    # 트렌드 데이터를 읽기 위한 시도
    try:
        # 방법 1: 이름으로 읽기 ("trend"로 이름을 바꿨다고 가정)
        history_df = conn.read(worksheet="trend", ttl=0)
        
        # 방법 2: 만약 위 방법이 실패(empty)하면 두 번째 탭(index 1) 시도
        if history_df.empty:
            history_df = conn.read(worksheet=1, ttl=0)
            
    except Exception as e:
        # 방법 3: 최후의 수단 - 에러가 나면 빈 표를 만들고 경고만 띄움
        history_df = pd.DataFrame()
        st.sidebar.warning(f"데이터 탐색 중: {str(e)[:30]}")

except Exception as e:
    st.error(f"구글 시트 메인 연결 실패: {e}")
    st.stop()

# 🔍 사이드바 진단 (사용자님 확인용)
st.sidebar.markdown("---")
st.sidebar.write(f"📊 트렌드 데이터 행 수: **{len(history_df)}**")
if not history_df.empty:
    st.sidebar.info(f"항목: {', '.join(history_df.columns[:3])}...")

# --- [중단] 분석 및 UI 로직 (기존과 동일) ---
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

st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 투자 실시간 클라우드 대시보드</h1>", unsafe_allow_html=True)

# 메인 데이터 처리
target = st.sidebar.selectbox("📂 계좌 선택", full_df['계좌명'].unique())
df = full_df[full_df['계좌명'] == target].copy()

# 시세 계산 루틴
with st.spinner('실시간 분석 중...'):
    for col in ['수량', '매입단가']:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['현재가'] = df['종목명'].apply(get_naver_price)
    df['매입금액'] = df['수량'] * df['매입단가']
    df['평가금액'] = df['수량'] * df['현재가']
    df['손익'] = df['평가금액'] - df['매입금액']
    df['수익률'] = (df['손익'] / df['매입금액'] * 100).fillna(0)

# 주요 지표 (Metric) 출력
c1, c2, c3 = st.columns(3)
c1.metric("총 평가액", f"{df['평가금액'].sum():,.0f}원")
c2.metric("총 매입금액", f"{df['매입금액'].sum():,.0f}원")
c3.metric("수익률", f"{(df['평가금액'].sum()/df['매입금액'].sum()-1)*100 if df['매입금액'].sum()>0 else 0:.2f}%")

# --- [하단] 시장 대비 성과 추이 차트 ---
if not history_df.empty and len(history_df) >= 2:
    st.divider()
    st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")
    
    # 데이터 정제 (콤마 제거 등)
    for col in history_df.columns:
        if col != 'Date':
            history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    # 차트 그리기
    fig_trend = go.Figure()
    
    # KOSPI 지수 정규화 (100 기준)
    base_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
    fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/base_k)*100, name='KOSPI', line=dict(dash='dash', color='gray')))
    
    # 계좌별 실선 추가
    acc_cols = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
    for col, color in acc_cols.items():
        if col in history_df.columns:
            # 시작일 수익률을 100으로 잡고 변동폭 표시
            norm_val = 100 + history_df[col] - history_df[col].iloc[0]
            fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=norm_val, name=col.replace('수익률',''), line=dict(color=color, width=3)))

    fig_trend.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white")
    st.plotly_chart(fig_trend, use_container_width=True)
else:
    st.info("💡 트렌드 데이터를 찾고 있습니다. 시트의 탭 이름이나 데이터를 확인해 주세요.")

st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
