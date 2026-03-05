import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta, timezone
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v17.6", layout="wide")

# --- [GID 설정] ---
STOCKS_GID = "301897027"
TREND_GID = "1055700982"

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()

if st.sidebar.button("🔄 데이터 동기화 및 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [데이터 로드 엔진] ---
try:
    full_df = conn.read(worksheet=STOCKS_GID, ttl="1m")
    # 그래프용 데이터는 시트에서 실시간으로 읽어옵니다.
    history_df = conn.read(worksheet=TREND_GID, ttl=0)
except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
    st.stop()

# --- [시세 엔진 (현재가 평가용)] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_stable_price(name):
    clean_name = str(name).strip().replace(" ", "")
    code = STOCK_CODES.get(clean_name)
    if not code: return 0
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        price_area = soup.find("div", {"class": "today"})
        return int(price_area.find("span", {"class": "blind"}).text.replace(",", ""))
    except: return 0

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# 현재 시점 자산 가공
with st.spinner('구글 시트 데이터를 분석 중입니다...'):
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    full_df['현재가'] = full_df['종목명'].apply(get_stable_price)
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

# --- UI 메인 섹션 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [Tab 0] 총괄 현황 ---
with tabs[0]:
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    t_profit = t_eval - t_buy
    t_roi = (t_profit / t_buy * 100) if t_buy > 0 else 0
    
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_profit:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("통합 누적 수익률", f"{t_roi:.2f}%")

    st.markdown("---")
    st.subheader("📑 계좌별 자산 요약")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '누적 수익률']).format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적 수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

    # 📊 구글 시트 기반 성과 추이 그래프 (단순화 버전)
    if not history_df.empty:
        st.divider()
        st.subheader("📊 시장 대비 성과 추이 (Sheet Data Only)")
        
        # 데이터 정제 및 날짜 형식 강제
        history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
        history_df = history_df.dropna(subset=['Date']).sort_values('Date')
        
        for col in history_df.columns:
            if col != 'Date':
                history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        
        fig_t = go.Figure()
        
        # 첫 번째 행 데이터를 기준으로 지수화 (기준점 100)
        bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        
        # 1. KOSPI 지수 (점선)
        fig_t.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, 
                                   name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        
        # 2. 계좌별 수익률 (실선)
        acc_c = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
        for c, clr in acc_c.items():
            if c in history_df.columns:
                # 시트의 누적 수익률 값을 100 기준으로 환산
                nv = 100 + history_df[c] - history_df[c].iloc[0]
                fig_t.add_trace(go.Scatter(x=history_df['Date'], y=nv, name=c.replace('수익률',''), 
                                           line=dict(color=clr, width=3)))
        
        # 그래프 레이아웃 (사용자 철학 반영: Y축 50~150 고정)
        fig_t.update_layout(
            yaxis=dict(title="상대 수익률 (100 기준)", range=[50, 150], gridcolor="rgba(255,255,255,0.05)"),
            hovermode="x unified",
            height=450, 
            plot_bgcolor='rgba(0,0,0,0)', 
            paper_bgcolor='rgba(0,0,0,0)', 
            font_color="white", 
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig_t, use_container_width=True)

# --- [계좌별 상세 분석 탭] ---
def render_account_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        sub_df['수익률'] = ((sub_df['평가금액'] / sub_df['매입금액'] - 1) * 100).fillna(0)
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_buy:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100 if a_buy>0 else 0:.2f}%")
        
        st.dataframe(sub_df[['종목명', '수량', '현재가', '평가금액', '수익률']].style.map(color_positive_negative, subset=['수익률']).format({'현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | 시트 데이터 기반")
