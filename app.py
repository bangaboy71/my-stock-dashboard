import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 투자 대시보드 v12.9", layout="wide")

# GID 설정 (여기에 방금 확인한 숫자를 넣으세요!)
# 예: TREND_GID = "123456789"
TREND_GID = "1055700982" 

if st.sidebar.button("🔄 전체 시스템 강제 초기화"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [상단] 초정밀 데이터 로드 엔진 (GID 조준형) ---
try:
    # 1. 메인 종목 데이터 (첫 번째 탭)
    full_df = conn.read(worksheet=0, ttl="1m")
    
    # 2. 트렌드 데이터 (GID를 활용한 직접 로드)
    try:
        # 이름 대신 GID로 직접 접근하여 400 에러를 원천 차단합니다.
        # 만약 GID를 아직 안 넣으셨다면 순서(1)로 시도합니다.
        target_sheet = TREND_GID if TREND_GID != "YOUR_GID_HERE" else 1
        history_df = conn.read(worksheet=target_sheet, ttl=0)
    except:
        history_df = pd.DataFrame()
except Exception as e:
    st.error(f"데이터 연결 오류: {e}")
    st.stop()

# 🔍 진단용 사이드바
st.sidebar.write(f"📈 트렌드 로드 상태: **{'성공' if not history_df.empty else '찾는 중'}**")
st.sidebar.write(f"🔢 데이터 행 수: **{len(history_df)}**")

# (중략: 시세 크롤링 및 색상 함수는 이전과 동일)
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}
def get_naver_price(n):
    code = STOCK_CODES.get(str(n).strip().replace(" ", ""))
    if not code: return 0
    try:
        r = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        return int(BeautifulSoup(r.text, 'html.parser').find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
    except: return 0

st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 투자 실시간 클라우드 대시보드</h1>", unsafe_allow_html=True)

# 메인 분석 (기존 차트 2종 포함)
if not full_df.empty and '계좌명' in full_df.columns:
    target = st.sidebar.selectbox("📂 계좌 선택", full_df['계좌명'].unique())
    df = full_df[full_df['계좌명'] == target].copy()
    
    with st.spinner('실시간 분석 중...'):
        for c in ['수량', '매입단가']: df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        df['현재가'] = df['종목명'].apply(get_naver_price)
        df['평가금액'] = df['수량'] * df['현재가']
        df['매입금액'] = df['수량'] * df['매입단가']
        df['수익률'] = ((df['평가금액'] / df['매입금액'] - 1) * 100).fillna(0)

    # 지표 출력
    c1, c2, c3 = st.columns(3)
    c1.metric("총 평가액", f"{df['평가금액'].sum():,.0f}원")
    c2.metric("총 매입금액", f"{df['매입금액'].sum():,.0f}원")
    c3.metric("수익률", f"{df['수익률'].mean():.2f}%")

    # 차트 섹션
    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("🍩 종목별 자산 비중")
        st.plotly_chart(px.pie(df, values='평가금액', names='종목명', hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r), use_container_width=True)
    with col_r:
        st.subheader("📈 종목별 수익률 현황")
        m = max(abs(df['수익률']).max(), 1)
        fig_bar = px.bar(df.sort_values('수익률'), x='수익률', y='종목명', orientation='h', color='수익률', color_continuous_scale=[[0, '#87CEEB'], [0.5, '#FFFFFF'], [1, '#FF4B4B']], range_color=[-m, m])
        st.plotly_chart(fig_bar, use_container_width=True)

# --- [하단] 시장 대비 성과 추이 차트 (GID 기반 로직) ---
if not history_df.empty and len(history_df) >= 1:
    st.divider()
    st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")
    
    # 데이터 정제 (숫자형 변환)
    for col in history_df.columns:
        if col != 'Date': history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    fig_t = go.Figure()
    # KOSPI 기준점 (100)
    bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
    fig_t.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI', line=dict(dash='dash', color='gray')))
    
    # 계좌별 추이
    accs = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
    for c, clr in accs.items():
        if c in history_df.columns:
            # 수익률의 변화를 100 기준 지수로 변환
            idx_v = 100 + history_df[c] - history_df[c].iloc[0]
            fig_t.add_trace(go.Scatter(x=history_df['Date'], y=idx_v, name=c.replace('수익률',''), line=dict(color=clr, width=3)))

    fig_t.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig_t, use_container_width=True)
else:
    st.info("💡 트렌드 데이터를 찾고 있습니다. GID 설정을 확인하거나 데이터를 입력해 주세요.")

st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
