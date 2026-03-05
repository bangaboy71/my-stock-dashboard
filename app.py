import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time
import plotly.express as px
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 통합 자산 관제탑 v14.0", layout="wide")

# --- [기존 GID 설정 유지] ---
STOCKS_GID = "301897027"
TREND_GID = "1055700982"

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

# --- [신규] 통합 시장 시세 엔진 (KRX + NXT) ---
def get_combined_price(name):
    clean_name = str(name).strip().replace(" ", "")
    code = STOCK_CODES.get(clean_name)
    if not code: return 0
    
    now = datetime.now().time()
    
    # NXT 프리마켓/애프터마켓 시간대 체크 (08:00~20:00 내외)
    # 실제 구현 시에는 NXT 정보를 제공하는 포털(네이버/다음 등)의 ATS 통합 시세 영역을 탐색합니다.
    # 여기서는 2026년 표준화된 통합 시세 경로를 가정합니다.
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. 정규장 시세 추출
        price_text = soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text
        current_price = int(price_text.replace(",", ""))
        
        # 2. [고도화] NXT/시간외 시세 체크
        # 장중(09:00-15:30)이 아닐 경우, 페이지 내 '시간외 단일가' 또는 'ATS 시세' 영역을 추가 탐색
        if now < time(9, 0) or now > time(15, 30):
            # 네이버 금융의 '시간외 단일가' 영역 추출 (NXT 통합 반영 가정)
            ov_section = soup.find("div", {"class": "aside_invest_info"})
            if ov_section:
                # 2026년 기준 NXT 시세 탭이 별도로 존재하거나 통합 표기됨
                # 여기서는 예시로 '시간외' 텍스트를 포함한 가격 탐색
                ov_price = ov_section.find("em").text.replace(",", "")
                if ov_price.isdigit():
                    return int(ov_price)
                    
        return current_price
    except:
        return 0

# --- [기존 로직 및 UI 유지] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

with st.spinner('NXT 통합 시세를 분석 중입니다...'):
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    # NXT 시세 엔진 적용
    full_df['현재가'] = full_df['종목명'].apply(get_combined_price)
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

# --- [UI 렌더링: 어제와 동일한 4단 탭 구조] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 가족 통합 자산 관제탑 (NXT 통합)</h1>", unsafe_allow_html=True)

# 현재 시장 상태 표시 (사이드바)
now_time = datetime.now().time()
if time(8, 0) <= now_time < time(9, 0):
    st.sidebar.warning("🌙 NXT 프리마켓 거래 중")
elif time(9, 0) <= now_time <= time(15, 30):
    st.sidebar.success("☀️ 정규 시장 거래 중")
elif time(15, 50) <= now_time <= time(20, 0):
    st.sidebar.warning("🌙 NXT 애프터마켓 거래 중")
else:
    st.sidebar.info("💤 시장 마감 (NXT 포함)")

tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# ... (이하 총괄 탭 및 개별 계좌 탭 렌더링 로직은 v13.8과 동일)
# [생략된 부분은 v13.8의 render_account_tab 및 총괄 로직을 그대로 사용합니다]
