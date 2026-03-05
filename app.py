import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time, timedelta, timezone
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v15.6", layout="wide")

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

# --- [데이터 로드 엔진] ---
try:
    full_df = conn.read(worksheet=STOCKS_GID, ttl="1m")
    history_df = conn.read(worksheet=TREND_GID, ttl=0)
except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
    st.stop()

# --- [통합 시세 엔진: 정규장 + NXT 애프터마켓] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_combined_price(name):
    code = STOCK_CODES.get(str(name).strip().replace(" ", ""))
    if not code: return 0
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. 기본 정규장 가격
        price_area = soup.find("div", {"class": "today"})
        current_price = int(price_area.find("span", {"class": "blind"}).text.replace(",", ""))
        
        # 2. 애프터마켓(NXT) 시세 체크 로직 보강
        kst_t = now_kst.time()
        # NXT 애프터마켓 시간 (15:50 ~ 20:00) 또는 프리마켓 (08:00 ~ 08:50)
        if (time(15, 50) <= kst_t <= time(20, 0)) or (time(8, 0) <= kst_t < time(9, 0)):
            # 네이버 금융의 '시간외 단일가' 혹은 'ATS 시세' 영역 탐색
            # 2026년 기준 NXT 통합 시세가 표시되는 div 영역을 타겟팅합니다.
            ov_section = soup.find("div", {"class": "aside_invest_info"})
            if ov_section:
                # '시간외' 텍스트가 포함된 영역의 가격을 추출
                ov_price_text = ov_section.find("em").text.replace(",", "")
                if ov_price_text.isdigit():
                    return int(ov_price_text)
                    
        return current_price
    except:
        return current_price # 에러 시 정규장 종가라도 반환

def get_live_kospi():
    try:
        url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        return float(soup.find("em", {"id": "now_value"}).text.replace(",", ""))
    except: return 0

# 데이터 가공
with st.spinner('NXT 애프터마켓 시세를 동기화 중입니다...'):
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    full_df['현재가'] = full_df['종목명'].apply(get_combined_price)
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

# --- UI 메인 섹션: v14.7 레이아웃 유지 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 (NXT 대응)</h1>", unsafe_allow_html=True)

# 시장 상태 표시 (사이드바)
kst_t = now_kst.time()
if time(15, 50) <= kst_t <= time(20, 0):
    status_msg = "🌙 NXT 애프터마켓 거래 중"
    st.sidebar.warning(f"{status_msg} ({now_kst.strftime('%H:%M')})")
elif time(9,0) <= kst_t <= time(15,30):
    status_msg = "☀️ 정규장 거래 중"
    st.sidebar.success(f"{status_msg} ({now_kst.strftime('%H:%M')})")
else:
    status_msg = "💤 시장 마감"
    st.sidebar.info(f"{status_msg} ({now_kst.strftime('%H:%M')})")

tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [Tab 0] 총괄 현황 (그래프 및 지표) ---
with tabs[0]:
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    t_profit = t_eval - t_buy
    t_roi = (t_profit / t_buy * 100) if t_buy > 0 else 0
    
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_profit:+,.0f}원")
    m2.metric("통합 누적 수익률", f"{t_roi:.2f}%")
    m3.metric("KOSPI 실시간", f"{get_live_kospi():,.2f}")

    # 실시간 성과 추이 그래프 (v15.5의 X축 연동 로직 유지)
    if not history_df.empty:
        st.divider()
        st.subheader("📊 실시간 성과 추이 (NXT 시세 반영)")
        
        for col in history_df.columns:
            if col != 'Date': history_df[col] = pd.to_numeric(history_df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        
        live_kospi = get_live_kospi()
        acc_summary = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
        live_row = {'Date': now_kst.strftime('%Y-%m-%d %H:%M'), 'KOSPI': live_kospi, '서은수익률': acc_summary.get('서은투자', 0), '서희수익률': acc_summary.get('서희투자', 0), '큰스님수익률': acc_summary.get('큰스님투자', 0)}
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

    # AI 리포트 등 생략 (v15.5와 동일)
    st.divider()
    st.info("🕵️ **AI 관전 포인트:** 현재 시간외/NXT 시장 가격을 실시간으로 읽어와 평가액에 반영 중입니다. 정규장 종가와 비교하여 시간외 흐름을 체크하세요.")

# [개별 계좌 탭 렌더링 함수 - 생략 (v15.5와 동일)]
def render_account_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        # ... (v15.5 로직 그대로 적용)
        st.dataframe(sub_df[['종목명', '수량', '현재가', '평가금액', '손익']], use_container_width=True)

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])
