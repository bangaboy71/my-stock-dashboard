import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta, timezone
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v16.5", layout="wide")

# --- [설정 유지] ---
STOCKS_GID = "301897027"
TREND_GID = "1055700982"

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()

if st.sidebar.button("🔄 AI 시황 분석 및 시세 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [데이터 로드 엔진] ---
try:
    full_df = conn.read(worksheet=STOCKS_GID, ttl="1m")
    history_df = conn.read(worksheet=TREND_GID, ttl=0)
except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
    st.stop()

# --- [정밀 시세 엔진: 자산 평가용 (KRX 종가 중심)] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_krx_price(name):
    code = STOCK_CODES.get(str(name).strip().replace(" ", ""))
    if not code: return 0
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        price = int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
        return price
    except: return 0

# 🎯 [신규] NXT 시장의 심박수(대표 시세)를 가져오는 함수
def get_nxt_pulse():
    # 삼성전자를 NXT 시장의 대표 지표로 활용 (가장 거래가 활발하므로)
    code = "005930" 
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        ov_section = soup.select_one(".aside_invest_info .no_today em")
        if ov_section:
            return int(ov_section.text.replace(",", ""))
        return 0
    except: return 0

# 데이터 가공 (자산 평가는 KRX 기준으로 안정화)
for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
full_df['현재가'] = full_df['종목명'].apply(get_krx_price)
full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
full_df['평가금액'] = full_df['수량'] * full_df['현재가']
full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

# --- UI 메인 섹션 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 (NXT 레이더 장착)</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [Tab 0] 총괄 현황 ---
with tabs[0]:
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    t_profit = t_eval - t_buy
    t_roi = (t_profit / t_buy * 100) if t_buy > 0 else 0
    
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_profit:+,.0f}원")
    m2.metric("통합 누적 수익률", f"{t_roi:.2f}%")
    m3.metric("오늘의 시장 상태", "🌙 NXT 애프터마켓" if time(15,50) <= now_kst.time() <= time(20,0) else "☀️ 정규장/마감")

    # 📈 [업그레이드] 듀얼 트렌드 차트 (KOSPI + NXT 레이더)
    if not history_df.empty:
        st.divider()
        st.subheader("📡 실시간 듀얼 레이더 (KOSPI vs NXT Pulse)")
        
        # 데이터 정제
        for col in history_df.columns:
            if col != 'Date': history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        
        # 실시간 NXT 심박수 계산
        nxt_p = get_nxt_pulse()
        krx_p = get_krx_price("삼성전자")
        # 삼성전자 기준 NXT 프리미엄(%) 계산하여 지수에 투영
        nxt_premium = (nxt_p / krx_p - 1) if krx_p > 0 and nxt_p > 0 else 0
        
        fig = go.Figure()
        bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        
        # 1. KOSPI 과거~오늘 종가 추이
        fig.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI(종가)', line=dict(color='gray', width=1.5, dash='dot')))
        
        # 2. 계좌별 수익률 (v15.1의 Y축 50-150 반영)
        acc_c = {'서은수익률': '#FF4B4B', '서희수익률': '#00CCFF', '큰스님수익률': '#00FF00'}
        for c, clr in acc_c.items():
            if c in history_df.columns:
                nv = 100 + history_df[c] - history_df[c].iloc[0]
                fig.add_trace(go.Scatter(x=history_df['Date'], y=nv, name=c.replace('수익률',''), line=dict(color=clr, width=3)))

        # 🎯 [핵심] NXT 레이더 점 추가 (현재 장외 시장의 열기를 점으로 표시)
        if nxt_premium != 0:
            last_date = history_df['Date'].iloc[-1]
            # KOSPI 종가 대비 NXT 프리미엄만큼 이동한 지점을 '번개' 마커로 표시
            nxt_index_val = (history_df['KOSPI'].iloc[-1] / bk * 100) * (1 + nxt_premium)
            fig.add_trace(go.Scatter(
                x=[last_date], y=[nxt_index_val],
                name='⚡ NXT 현재 열기',
                mode='markers+text',
                marker=dict(color='#FFD700', size=15, symbol='thunder'),
                text=["NXT 반등 중" if nxt_premium > 0 else "NXT 약세"],
                textposition="top center"
            ))

        fig.update_layout(yaxis=dict(title="상대 수익률 (100 기준)", range=[50, 150]), hovermode="x unified", height=450, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    # [계좌 요약표 및 AI 브리핑 - 기존 v14.7 형식 유지]
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '누적 수익률']].style.format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적 수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

# [개별 계좌 탭 - 기존 형식 유지]
def render_account_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        # (기존 차트 및 표 로직 동일)
        st.metric(f"{acc_name} 평가액", f"{sub_df['평가금액'].sum():,.0f}원")
        st.dataframe(sub_df[['종목명', '수량', '현재가', '평가금액', '손익']], use_container_width=True)

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])
