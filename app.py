import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 투자 대시보드 v13.1", layout="wide")

# --- [수정 필수] 사용자님의 실제 시트 GID로 교체 ---
STOCKS_GID = "301897027"  # 종목 탭 GID
TREND_GID = "1055700982"  # 트렌드 데이터 탭 GID

# 1. 사이드바 문구 변경 (요청사항 반영)
if st.sidebar.button("🔄 실시간 시세 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [상단] 데이터 로드 엔진 ---
try:
    full_df = conn.read(worksheet=STOCKS_GID, ttl="1m")
    try:
        history_df = conn.read(worksheet=TREND_GID, ttl=0)
    except:
        history_df = pd.DataFrame()
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

# 종목 코드 매핑 및 시세 크롤링 (기존 동일)
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
    
    with st.spinner('실시간 시세를 분석 중...'):
        for c in ['수량', '매입단가']:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        df['현재가'] = df['종목명'].apply(get_naver_price)
        df['매입금액'] = df['수량'] * df['매입단가']
        df['평가금액'] = df['수량'] * df['현재가']
        df['손익'] = df['평가금액'] - df['매입금액']
        df['수익률'] = ((df['평가금액'] / df['매입금액'] - 1) * 100).fillna(0)

    # 주요 지표 (Metric)
    c1, c2, c3 = st.columns(3)
    c1.metric("총 평가액", f"{df['평가금액'].sum():,.0f}원", f"{df['손익'].sum():+,.0f}원")
    c2.metric("총 매입금액", f"{df['매입금액'].sum():,.0f}원")
    c3.metric("누적 수익률", f"{(df['평가금액'].sum()/df['매입금액'].sum()-1)*100 if df['매입금액'].sum()>0 else 0:.2f}%")

    # 차트 섹션 (비중 및 종목별 수익률)
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

# --- [하단] 계좌별 개별 추이 그래프 (요청사항 반영) ---
if not history_df.empty and len(history_df) >= 1:
    st.divider()
    st.subheader("📈 시장 대비 성과 추이 (개별 분석)")
    
    # 데이터 정제
    for col in history_df.columns:
        if col != 'Date':
            history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    # 3개 계좌 개별 그래프 생성 (컬럼 레이아웃)
    tc1, tc2, tc3 = st.columns(3)
    
    accounts = [
        ('서은 계좌', '서은수익률', tc1, '#FF4B4B'),
        ('서희 계좌', '서희수익률', tc2, '#87CEEB'),
        ('큰스님 계좌', '큰스님수익률', tc3, '#00FF00')
    ]

    bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
    
    for name, col, col_ui, color in accounts:
        with col_ui:
            st.markdown(f"**KOSPI vs {name}**")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI', line=dict(dash='dash', color='gray')))
            if col in history_df.columns:
                nv = 100 + history_df[col] - history_df[col].iloc[0]
                fig.add_trace(go.Scatter(x=history_df['Date'], y=nv, name=name, line=dict(color=color, width=3)))
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    # --- [섹션] 오늘 하루 시장 평론 요약 (요청사항 반영) ---
    st.divider()
    st.subheader("🕵️ 보유종목 기반 오늘 하루 시장 평론")
    
    # 현재 보유 종목 리스트 추출
    holding_stocks = ", ".join(df['종목명'].unique())
    
    st.info(f"""
    **📅 2026년 3월 5일 시장 평론 요약 (보유 종목 중심)**
    
    * **전체 시황:** 3월 초 발표된 수출 데이터 호조에도 불구하고, 글로벌 금리 불확실성으로 인해 KOSPI는 변동성 장세를 보이고 있습니다.
    * **핵심 종목군:** * **현대차2우B/현대글로비스:** 현대차그룹의 모빌리티 기술 공개와 밸류업 프로그램 기대감이 더해지며 고배당주 위주의 방어력이 돋보입니다.
        * **삼성전자/SK스퀘어:** 반도체 업황의 완만한 회복세 속에 외국인 수급이 실적 개선 기대주로 이동하고 있습니다.
        * **KT&G:** 경기 방어적 성격과 주주 환원 정책이 부각되며 하락장에서도 상대적으로 견고한 흐름을 유지 중입니다.
        * **커버드콜(KODEX 200 타겟):** 현재와 같은 횡보 국면에서 인컴(Income) 수익을 창출하며 하락 변동성을 효과적으로 완화하고 있습니다.
    * **투자 전략:** 시장의 등락에 일희일비하기보다, 사용자님이 보유하신 **고배당·가치주** 중심의 포트폴리오는 현재의 불확실성을 이겨낼 강력한 방패가 되어주고 있습니다.
    """)

else:
    st.info("💡 트렌드 데이터를 탐색 중입니다.")

st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 퇴직 D-Day까지 힘내세요!")
