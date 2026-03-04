import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 투자 대시보드 v13.0", layout="wide")

# --- [중요] 여기에 확인하신 GID 숫자들을 넣어주세요 ---
STOCKS_GID = "301897027"          # 종목 리스트 탭의 GID (보통 0)
TREND_GID = "1055700982"  # 트렌드 데이터 탭의 GID

if st.sidebar.button("🔄 전체 시스템 강제 초기화"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [상단] 데이터 로드 엔진 (GID 개별 조준) ---
try:
    # 1. 종목 리스트 로드 (STOCKS_GID 사용)
    full_df = conn.read(worksheet=STOCKS_GID, ttl="1m")
    
    # 2. 트렌드 데이터 로드 (TREND_GID 사용)
    try:
        history_df = conn.read(worksheet=TREND_GID, ttl=0)
    except:
        history_df = pd.DataFrame()
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

# 🔍 사이드바 진단 (두 데이터가 모두 들어왔는지 확인)
st.sidebar.markdown("---")
st.sidebar.write(f"📊 보유 종목 수: **{len(full_df) if '종목명' in full_df.columns else 0}**")
st.sidebar.write(f"📈 트렌드 행 수: **{len(history_df)}**")

# (시세 크롤링 및 색상 함수)
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}
def get_naver_price(n):
    code = STOCK_CODES.get(str(n).strip().replace(" ", ""))
    if not code: return 0
    try:
        r = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        return int(BeautifulSoup(r.text, 'html.parser').find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
    except: return 0

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 투자 실시간 클라우드 대시보드</h1>", unsafe_allow_html=True)

# --- [중단] 보유 종목 분석 섹션 ---
if not full_df.empty and '계좌명' in full_df.columns:
    target = st.sidebar.selectbox("📂 계좌 선택", full_df['계좌명'].unique())
    df = full_df[full_df['계좌명'] == target].copy()
    
    with st.spinner('실시간 분석 중...'):
        for c in ['수량', '매입단가']:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        df['현재가'] = df['종목명'].apply(get_naver_price)
        df['매입금액'] = df['수량'] * df['매입단가']
        df['평가금액'] = df['수량'] * df['현재가']
        df['손익'] = df['평가금액'] - df['매입금액']
        df['수익률'] = ((df['평가금액'] / df['매입금액'] - 1) * 100).fillna(0)

    # 주요 지표
    c1, c2, c3 = st.columns(3)
    c1.metric("총 평가액", f"{df['평가금액'].sum():,.0f}원", f"{df['손익'].sum():+,.0f}원")
    c2.metric("총 매입금액", f"{df['매입금액'].sum():,.0f}원")
    c3.metric("누적 수익률", f"{(df['평가금액'].sum()/df['매입금액'].sum()-1)*100 if df['매입금액'].sum()>0 else 0:.2f}%")

    # 차트 섹션
    st.markdown("---")
    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("🍩 종목별 자산 비중")
        st.plotly_chart(px.pie(df, values='평가금액', names='종목명', hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r), use_container_width=True)
    with col_r:
        st.subheader("📈 종목별 수익률 현황")
        m = max(abs(df['수익률']).max(), 1)
        fig_bar = px.bar(df.sort_values('수익률'), x='수익률', y='종목명', orientation='h', color='수익률', color_continuous_scale=[[0, '#87CEEB'], [0.5, '#FFFFFF'], [1, '#FF4B4B']], range_color=[-m, m])
        st.plotly_chart(fig_bar, use_container_width=True)

    # 상세 내역 표
    st.subheader(f"📑 {target} 상세 내역")
    st.dataframe(df[['종목명', '수량', '매입단가', '현재가', '평가금액', '손익', '수익률']].style.map(color_positive_negative, subset=['손익', '수익률']).format({'매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)
else:
    st.error("첫 번째 GID 설정이 잘못되었거나 '계좌명' 컬럼을 찾을 수 없습니다.")

# --- [하단] 시장 대비 성과 추이 차트 ---
if not history_df.empty and len(history_df) >= 1:
    st.divider()
    st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")
    for col in history_df.columns:
        if col != 'Date':
            history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    fig_t = go.Figure()
    bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
    fig_t.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI', line=dict(dash='dash', color='gray')))
    
    accs = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
    for c, clr in accs.items():
        if c in history_df.columns:
            nv = 100 + history_df[c] - history_df[c].iloc[0]
            fig_t.add_trace(go.Scatter(x=history_df['Date'], y=nv, name=c.replace('수익률',''), line=dict(color=clr, width=3)))

    fig_t.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig_t, use_container_width=True)

st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
