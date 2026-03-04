import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 구글 시트 연결
st.set_page_config(page_title="가족 투자 대시보드 v12.3", layout="wide")

# 사이드바: 전체 시스템 강제 초기화 버튼
if st.sidebar.button("🔄 전체 시스템 초기화 및 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [데이터 로드 엔진] ---
try:
    # 1. 메인 종목 데이터 읽기
    full_df = conn.read(ttl="1m")
    
    # 2. 트렌드 데이터 읽기 (강력한 진단 로직 추가)
    try:
        # 캐시 무시(ttl=0)하고 읽기 시도
        history_df = conn.read(worksheet="daily_trend", ttl=0)
    except Exception as e:
        # 읽기 실패 시 에러 내용을 화면에 살짝 표시
        st.sidebar.warning(f"탭 읽기 시도 중: {str(e)[:50]}...")
        history_df = pd.DataFrame()

except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

# 🔍 [진단 섹션] 사이드바에서 데이터 상태 확인
st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ 데이터 진단 도구")
st.sidebar.write(f"📈 트렌드 데이터 행 수: **{len(history_df)}**")

if history_df.empty:
    st.sidebar.error("⚠️ 데이터를 찾지 못했습니다.")
    st.sidebar.info("💡 팁: 'daily_trend' 탭 이름 앞뒤에 공백이 있는지, 혹은 데이터가 2행부터 시작하는지 확인하세요.")
else:
    st.sidebar.success("✅ 데이터를 성공적으로 읽었습니다!")
    # 읽어온 데이터의 컬럼명들을 보여줍니다 (오타 확인용)
    st.sidebar.write("검출된 항목:", list(history_df.columns))

# --- 기존 대시보드 로직 (동일) ---
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

with st.spinner('실시간 시세를 분석 중입니다...'):
    for col in ['수량', '매입단가']:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['현재가'] = df['종목명'].apply(get_naver_price)
    df['매입금액'] = df['수량'] * df['매입단가']
    df['평가금액'] = df['수량'] * df['현재가']
    df['손익'] = df['평가금액'] - df['매입금액']
    df['수익률'] = (df['손익'] / df['매입금액'] * 100).fillna(0)

t_buy, t_eval = df['매입금액'].sum(), df['평가금액'].sum()
t_pl, t_roi = t_eval - t_buy, (t_eval/t_buy - 1)*100 if t_buy > 0 else 0

c1, c2, c3 = st.columns(3)
c1.metric("총 평가액", f"{t_eval:,.0f}원", f"{t_pl:+,.0f}원")
c2.metric("총 매입금액", f"{t_buy:,.0f}원")
c3.metric("누적 수익률", f"{t_roi:.2f}%", f"{t_roi:+.2f}%")

st.markdown("---")
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

st.subheader(f"📑 {target} 상세 현황")
st.dataframe(
    df[['종목명', '수량', '매입단가', '현재가', '평가금액', '손익', '수익률']].style
    .map(color_positive_negative, subset=['손익', '수익률'])
    .format({'매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'}),
    hide_index=True, use_container_width=True
)

# --- 시장 대비 성과 추이 차트 ---
if not history_df.empty and len(history_df) >= 1:
    st.divider()
    st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")
    
    # 컬럼 존재 여부 확인 후 계산
    required_cols = ['KOSPI', '서은수익률', '서희수익률', '큰스님수익률']
    for col in required_cols:
        if col in history_df.columns:
            history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    if 'KOSPI' in history_df.columns and history_df['KOSPI'].iloc[0] != 0:
        first_kospi = history_df['KOSPI'].iloc[0]
        history_df['KOSPI_IDX'] = (history_df['KOSPI'] / first_kospi) * 100
        
        # 지수화 계산
        for col, idx_name in zip(['서은수익률', '서희수익률', '큰스님수익률'], ['SE_IDX', 'SH_IDX', 'KS_IDX']):
            if col in history_df.columns:
                history_df[idx_name] = 100 + history_df[col] - history_df[col].iloc[0]

        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['KOSPI_IDX'], name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        if 'SE_IDX' in history_df.columns:
            fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['SE_IDX'], name='서은투자', line=dict(color='#FF4B4B', width=3)))
        if 'SH_IDX' in history_df.columns:
            fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['SH_IDX'], name='서희투자', line=dict(color='#87CEEB', width=3)))
        if 'KS_IDX' in history_df.columns:
            fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=history_df['KS_IDX'], name='큰스님투자', line=dict(color='#00FF00', width=3)))

        fig_trend.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white",
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_trend, use_container_width=True)
else:
    st.info("💡 'daily_trend' 탭의 데이터를 읽어오는 중이거나 탭이 비어 있습니다. (사이드바의 진단 도구를 확인하세요)")

st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
