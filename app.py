import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 구글 시트 연결
st.set_page_config(page_title="가족 투자 대시보드 v12.7", layout="wide")

if st.sidebar.button("🔄 전체 데이터 강제 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [상단] 데이터 로드 엔진 (종목 시트=0, 트렌드 시트=1) ---
try:
    # 종목 리스트 (첫 번째 탭)
    full_df = conn.read(worksheet=0, ttl="1m")
    # 트렌드 데이터 (두 번째 탭)
    try:
        history_df = conn.read(worksheet=1, ttl=0)
    except:
        history_df = pd.DataFrame()
except Exception as e:
    st.error(f"구글 시트 연결 실패: {e}")
    st.stop()

# 종목 코드 매핑
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

# 2. 메인 UI
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 투자 실시간 클라우드 대시보드</h1>", unsafe_allow_html=True)

if not full_df.empty and '계좌명' in full_df.columns:
    target = st.sidebar.selectbox("📂 계좌 선택", full_df['계좌명'].unique())
    df = full_df[full_df['계좌명'] == target].copy()

    with st.spinner('실시간 시세를 분석 중...'):
        for col in ['수량', '매입단가']:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        df['현재가'] = df['종목명'].apply(get_naver_price)
        df['매입금액'] = df['수량'] * df['매입단가']
        df['평가금액'] = df['수량'] * df['현재가']
        df['손익'] = df['평가금액'] - df['매입금액']
        df['수익률'] = (df['손익'] / df['매입금액'] * 100).fillna(0)

    # 상단 지표
    t_buy, t_eval = df['매입금액'].sum(), df['평가금액'].sum()
    t_pl, t_roi = t_eval - t_buy, (t_eval/t_buy - 1)*100 if t_buy > 0 else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("총 평가액", f"{t_eval:,.0f}원", f"{t_pl:+,.0f}원")
    c2.metric("총 매입금액", f"{t_buy:,.0f}원")
    c3.metric("누적 수익률", f"{t_roi:.2f}%", f"{t_roi:+.2f}%")

    # --- 복구된 섹션: 종목 비중 및 수익률 차트 ---
    st.markdown("---")
    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("🍩 종목별 자산 비중")
        fig_pie = px.pie(df, values='평가금액', names='종목명', hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r)
        st.plotly_chart(fig_pie, use_container_width=True)
    with col_r:
        st.subheader("📈 종목별 수익률 현황")
        max_val = max(abs(df['수익률']).max(), 1) 
        fig_bar = px.bar(df.sort_values('수익률'), x='수익률', y='종목명', orientation='h',
                         color='수익률', color_continuous_scale=[[0, '#87CEEB'], [0.5, '#FFFFFF'], [1, '#FF4B4B']], 
                         range_color=[-max_val, max_val])
        fig_bar.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig_bar, use_container_width=True)

    # 상세 표
    st.subheader(f"📑 {target} 상세 내역")
    st.dataframe(
        df[['종목명', '수량', '매입단가', '현재가', '평가금액', '손익', '수익률']].style
        .map(color_positive_negative, subset=['손익', '수익률'])
        .format({'매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'}),
        hide_index=True, use_container_width=True
    )
else:
    st.error("첫 번째 탭에 '계좌명'이 포함된 데이터를 확인해주세요.")

# --- 추가된 섹션: 시장 대비 성과 추이 차트 ---
if not history_df.empty and len(history_df) >= 1:
    st.divider()
    st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")
    
    for col in history_df.columns:
        if col != 'Date':
            history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', '').replace('%',''), errors='coerce').fillna(0)

    if 'KOSPI' in history_df.columns:
        fig_trend = go.Figure()
        base_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/base_k)*100, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        
        acc_colors = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
        for col, color in acc_colors.items():
            if col in history_df.columns:
                norm_val = 100 + history_df[col] - history_df[col].iloc[0]
                fig_trend.add_trace(go.Scatter(x=history_df['Date'], y=norm_val, name=col.replace('수익률',''), line=dict(color=color, width=3)))

        fig_trend.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white",
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_trend, use_container_width=True)
else:
    st.info("💡 두 번째 탭에 트렌드 데이터를 입력하면 시장 비교 차트가 나타납니다.")

st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
