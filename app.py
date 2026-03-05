import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 통합 자산 관제탑 v13.7", layout="wide")

# --- [설정 완료] 사용자님의 실제 시트 GID 반영 ---
STOCKS_GID = "301897027"   # 종목 탭 GID
TREND_GID = "1055700982"  # 트렌드 데이터 탭 GID

if st.sidebar.button("🔄 실시간 시세 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [상단] 데이터 로드 엔진 ---
try:
    # 종목 데이터 로드
    full_df = conn.read(worksheet=STOCKS_GID, ttl="1m")
    try:
        # 트렌드 데이터 로드 (알려주신 GID 사용)
        history_df = conn.read(worksheet=TREND_GID, ttl=0)
    except:
        history_df = pd.DataFrame()
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

# 종목 코드 매핑 및 시세 크롤링
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", 
    "현대글로비스": "086280", "현대차2우B": "005387", 
    "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", 
    "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"
}

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

# 데이터 전처리
with st.spinner('실시간 자산을 분석 중입니다...'):
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    full_df['현재가'] = full_df['종목명'].apply(get_naver_price)
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

# --- UI 메인 섹션 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 통합 자산 관제탑</h1>", unsafe_allow_html=True)
tab_summary, tab_details = st.tabs(["🏠 총괄 현황", "🔍 계좌별 상세 분석"])

# --- [Tab 1] 총괄 현황 ---
with tab_summary:
    # 1. 상단 통합 지표
    total_buy = full_df['매입금액'].sum()
    total_eval = full_df['평가금액'].sum()
    total_profit = total_eval - total_buy
    total_roi = (total_profit / total_buy * 100) if total_buy > 0 else 0
    
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{total_eval:,.0f}원", f"{total_profit:+,.0f}원")
    m2.metric("총 투자 원금", f"{total_buy:,.0f}원")
    m3.metric("통합 누적 수익률", f"{total_roi:.2f}%")

    st.markdown("---")
    
    # 2. 계좌별 요약 현황 표
    st.subheader("📑 계좌별 자산 요약")
    summary_by_acc = full_df.groupby('계좌명').agg({
        '매입금액': 'sum',
        '평가금액': 'sum',
        '손익': 'sum'
    }).reset_index()
    summary_by_acc['누적 수익률'] = (summary_by_acc['손익'] / summary_by_acc['매입금액'] * 100).fillna(0)
    
    st.dataframe(
        summary_by_acc[['계좌명', '매입금액', '평가금액', '손익', '누적 수익률']].style
        .map(color_positive_negative, subset=['손익', '누적 수익률'])
        .format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적 수익률': '{:+.2f}%'}),
        hide_index=True, use_container_width=True
    )

    # 3. 시장 대비 성과 추이 (전 계좌 통합 차트)
    if not history_df.empty:
        st.divider()
        st.subheader("📊 시장 대비 성과 추이 (KOSPI vs 전 계좌)")
        
        for col in history_df.columns:
            if col != 'Date':
                history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

        fig_t = go.Figure()
        bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        fig_t.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        
        acc_colors = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
        for col, color in acc_colors.items():
            if col in history_df.columns:
                nv = 100 + history_df[col] - history_df[col].iloc[0]
                fig_t.add_trace(go.Scatter(x=history_df['Date'], y=nv, name=col.replace('수익률',''), line=dict(color=color, width=3)))

        fig_t.update_layout(height=450, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white",
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_t, use_container_width=True)
    else:
        st.info("💡 트렌드 데이터를 불러올 수 없습니다. GID 설정을 다시 확인해 주세요.")

# --- [Tab 2] 계좌별 상세 분석 ---
with tab_details:
    target = st.selectbox("📂 상세 분석할 계좌 선택", full_df['계좌명'].unique())
    sub_df = full_df[full_df['계좌명'] == target].copy()
    sub_df['수익률'] = ((sub_df['평가금액'] / sub_df['매입금액'] - 1) * 100).fillna(0)
    
    col_l, col_r = st.columns(2)
    with col_l:
        st.plotly_chart(px.pie(sub_df, values='평가금액', names='종목명', hole=0.4, title=f"[{target}] 종목 비중", color_discrete_sequence=px.colors.sequential.Blues_r), use_container_width=True)
    with col_r:
        m = max(abs(sub_df['수익률']).max(), 1)
        fig_bar = px.bar(sub_df.sort_values('수익률'), x='수익률', y='종목명', orientation='h', title=f"[{target}] 종목별 수익률", color='수익률', color_continuous_scale=[[0, '#87CEEB'], [0.5, '#FFFFFF'], [1, '#FF4B4B']], range_color=[-m, m])
        st.plotly_chart(fig_bar, use_container_width=True)

    st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '평가금액', '손익', '수익률']].style.map(color_positive_negative, subset=['손익', '수익률']).format({'매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

st.divider()
st.subheader("🕵️ 보유종목 기반 시장 평론 요약")
st.info("현재 고배당 및 가치주 중심의 포트폴리오는 시장 하락기에도 강력한 방어력을 보여줍니다. 시간의 힘을 통한 복리 효과를 극대화할 수 있는 전략을 유지하시기 바랍니다.")
st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
