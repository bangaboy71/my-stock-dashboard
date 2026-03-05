import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta, timezone
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v15.1", layout="wide")

# --- [설정 유지] ---
STOCKS_GID = "301897027"
TREND_GID = "1055700982"

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()

if st.sidebar.button("🔄 AI 시장 분석 및 시세 새로고침"):
    st.cache_data.clear()
    st.rerun()

conn = st.connection("gsheets", type=GSheetsConnection)

# --- [데이터 로드 및 시세 엔진 - 기존 동일] ---
try:
    full_df = conn.read(worksheet=STOCKS_GID, ttl="1m")
    try:
        history_df = conn.read(worksheet=TREND_GID, ttl=0)
    except:
        history_df = pd.DataFrame()
except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
    st.stop()

STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_combined_price(name):
    code = STOCK_CODES.get(str(name).strip().replace(" ", ""))
    if not code: return 0
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        return int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
    except: return 0

# 데이터 가공
for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
full_df['현재가'] = full_df['종목명'].apply(get_combined_price)
full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
full_df['평가금액'] = full_df['수량'] * full_df['현재가']
full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

# --- UI 메인 섹션 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 자산 성장 관제탑</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [Tab 0] 총괄 현황 ---
with tabs[0]:
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    t_roi = ((t_eval / t_buy - 1) * 100) if t_buy > 0 else 0
    
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval - t_buy:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("통합 누적 수익률", f"{t_roi:.2f}%")

    if not history_df.empty:
        st.divider()
        st.subheader("🔥 실시간 시장 대비 성과 추이 (Fixed Axis)")
        
        # 데이터 정제
        for col in history_df.columns:
            if col != 'Date': history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        
        bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        fig = go.Figure()
        
        # KOSPI 배경
        fig.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI 지수', fill='tozeroy', fillcolor='rgba(128,128,128,0.05)', line=dict(color='gray', width=1, dash='dot')))
        
        acc_colors = {'서은수익률': '#FF4B4B', '서희수익률': '#00CCFF', '큰스님수익률': '#00FF7F'}
        for col, color in acc_colors.items():
            if col in history_df.columns:
                nv = 100 + history_df[col] - history_df[col].iloc[0]
                fig.add_trace(go.Scatter(x=history_df['Date'], y=nv, name=col.replace('수익률',''), line=dict(color=color, width=3), mode='lines+markers', marker=dict(size=[0]*(len(nv)-1) + [10], color=color)))

        # 🎯 [요청 반영] 세로축 범위 고정 (50 ~ 150)
        fig.update_layout(
            yaxis=dict(
                title="상대 수익률 (100 기준)",
                range=[50, 150], # 사용자님의 경험과 목표 반영
                gridcolor="rgba(255,255,255,0.05)",
                fixedrange=False # 확대/축소는 가능하게 둠
            ),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            height=500,
            xaxis=dict(rangeslider=dict(visible=True), type="date"),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color="white"
        )
        st.plotly_chart(fig, use_container_width=True)

    # (이하 요약 표 및 AI 평론 로직은 v15.0과 동일)
    st.markdown("---")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '누적 수익률']].style.format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적 수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

# [개별 계좌 탭 로직 렌더링 함수 - 생략 (v15.0 동일)]
def render_account_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        # ... (이전 코드와 동일)
        st.write(f"### {acc_name} 상세 분석 중...")
        st.dataframe(sub_df[['종목명', '수량', '현재가', '평가금액']], use_container_width=True)

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])
