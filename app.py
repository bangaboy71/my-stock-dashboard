import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta, timezone
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v17.0", layout="wide")

# --- [GID 설정] ---
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

# --- [안정화 시세 엔진 (KRX 종가 기준)] ---
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", 
    "현대글로비스": "086280", "현대차2우B": "005387", 
    "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", 
    "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"
}

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
    except:
        return 0

def get_live_kospi():
    try:
        url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        return float(soup.find("em", {"id": "now_value"}).text.replace(",", ""))
    except: return 0

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# 데이터 가공
with st.spinner('KRX 정규장 시세를 바탕으로 자산을 정밀 분석 중입니다...'):
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    full_df['현재가'] = full_df['종목명'].apply(get_stable_price)
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

# --- UI 메인 섹션: v14.7 횡방향 탭 레이아웃 복구 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑</h1>", unsafe_allow_html=True)

# 시장 상태 표시
kst_t = now_kst.time()
status_msg = "☀️ 정규장 거래 중" if time(9,0) <= kst_t <= time(15,30) else "💤 시장 마감 (KRX 종가 기준)"
st.sidebar.info(f"{status_msg} ({now_kst.strftime('%H:%M')})")

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

    # 🔥 실시간 시장 대비 성과 추이 (Y축 고정 50-150 / Live 연동)
    if not history_df.empty:
        st.divider()
        st.subheader("📊 실시간 시장 대비 성과 추이")
        for col in history_df.columns:
            if col != 'Date': history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        
        live_kospi = get_live_kospi()
        acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
        live_row = {'Date': now_kst.strftime('%Y-%m-%d %H:%M'), 'KOSPI': live_kospi, '서은수익률': acc_sum.get('서은투자', 0), '서희수익률': acc_sum.get('서희투자', 0), '큰스님수익률': acc_sum.get('큰스님투자', 0)}
        display_df = pd.concat([history_df, pd.DataFrame([live_row])], ignore_index=True)
        
        fig_t = go.Figure()
        bk = display_df['KOSPI'].iloc[0] if display_df['KOSPI'].iloc[0] != 0 else 1
        fig_t.add_trace(go.Scatter(x=display_df['Date'], y=(display_df['KOSPI']/bk)*100, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        
        acc_c = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
        for c, clr in acc_c.items():
            if c in display_df.columns:
                nv = 100 + display_df[c] - display_df[c].iloc[0]
                fig_t.add_trace(go.Scatter(x=display_df['Date'], y=nv, name=c.replace('수익률',''), line=dict(color=clr, width=3), mode='lines+markers', marker=dict(size=[0]*(len(nv)-1) + [12], color=clr)))
        
        fig_t.update_layout(yaxis=dict(title="상대 수익률 (100 기준)", range=[50, 150], gridcolor="rgba(255,255,255,0.05)"), hovermode="x unified", height=450, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color="white", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_t, use_container_width=True)

    st.divider()
    st.subheader("🕵️ AI 실시간 마켓 브리핑")
    st.info(f"**📅 {now_kst.strftime('%Y-%m-%d %H:%M')} 시장 리포트:** KRX 정규장 시세를 바탕으로 한 자산 분석입니다. 장기적 관점에서 안정적인 수익률 곡선을 형성 중입니다.")

# --- [계좌별 상세 분석 탭 렌더링 함수] ---
def render_account_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        sub_df['수익률'] = ((sub_df['평가금액'] / sub_df['매입금액'] - 1) * 100).fillna(0)
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_buy:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100 if a_buy>0 else 0:.2f}%")
        
        col_l, col_r = st.columns(2)
        with col_l: st.plotly_chart(px.pie(sub_df, values='평가금액', names='종목명', hole=0.4, title=f"[{acc_name}] 종목 비중", color_discrete_sequence=px.colors.sequential.Blues_r), use_container_width=True)
        with col_r:
            m = max(abs(sub_df['수익률']).max(), 1)
            fig_b = px.bar(sub_df.sort_values('수익률'), x='수익률', y='종목명', orientation='h', title=f"[{acc_name}] 종목별 수익률", color='수익률', color_continuous_scale=[[0, '#87CEEB'], [0.5, '#FFFFFF'], [1, '#FF4B4B']], range_color=[-m, m])
            st.plotly_chart(fig_b, use_container_width=True)
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '평가금액', '손익', '수익률']].style.map(color_positive_negative, subset=['손익', '수익률']).format({'매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | KRX 안정화 모드")
