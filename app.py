import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import plotly.express as px
import io

# 1. 설정 및 구글 시트 연결
st.set_page_config(page_title="가족 투자 대시보드 v11.1", layout="wide")

conn = st.connection("gsheets", type=GSheetsConnection)

try:
    full_df = conn.read(ttl="1m")
except Exception as e:
    st.error(f"구글 시트를 읽어오지 못했습니다: {e}")
    st.stop()

# 종목 코드 매핑
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220",
    "현대글로비스": "086280", "현대차2우B": "005387",
    "KODEX200타겟위클리커버드콜": "498400", 
    "에스티팜": "237690", "테스": "095610", "일진전기": "103590",
    "SK스퀘어": "402340"
}

# 시세 크롤링 함수 (이름 청소 기능 포함)
def get_naver_price(name):
    clean_name = str(name).strip().replace(" ", "") # 공백 제거
    code = STOCK_CODES.get(clean_name)
    if not code: return 0
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        price = soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text
        return int(price.replace(",", ""))
    except: return 0

# 표 색상 스타일 함수 (플러스 빨강, 마이너스 파랑)
def color_positive_negative(val):
    if isinstance(val, (int, float)):
        color = 'red' if val > 0 else 'blue' if val < 0 else 'black'
        return f'color: {color}'
    return ''

# 2. 메인 UI 및 데이터 처리
st.markdown(f"<h1 style='text-align: center; color: #002060;'>🌐 가족 투자 실시간 클라우드 대시보드</h1>", unsafe_allow_html=True)

target = st.sidebar.selectbox("📂 계좌 선택", full_df['계좌명'].unique())

if st.sidebar.button("🔄 시세/데이터 강제 새로고침"):
    st.cache_data.clear()
    st.rerun()

# --- 데이터 계산 로직 시작 ---
df = full_df[full_df['계좌명'] == target].copy()

with st.spinner('데이터를 분석 중입니다...'):
    # [중요] 글자 타입을 숫자로 강제 변환 (에러 방지)
    df['수량'] = pd.to_numeric(df['수량'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    df['매입단가'] = pd.to_numeric(df['매입단가'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    
    # 시세 및 금액 계산
    df['현재가'] = df['종목명'].apply(get_naver_price)
    df['매입금액'] = df['수량'] * df['매입단가']
    df['평가금액'] = df['수량'] * df['현재가']
    df['손익'] = df['평가금액'] - df['매입금액']
    
    # 수익률 계산 ($$ROI = \frac{Profit}{Buy} \times 100$$)
    df['수익률'] = (df['손익'] / df['매입금액']) * 100
    df['수익률'] = df['수익률'].fillna(0)

# 3. 화면 출력 (여기서부터 색상 적용)
t_buy, t_eval = df['매입금액'].sum(), df['평가금액'].sum()
t_pl, t_roi = t_eval - t_buy, (t_eval/t_buy - 1)*100 if t_buy > 0 else 0

c1, c2, c3 = st.columns(3)
# delta_color="normal"을 쓰면 기본 빨강/파랑으로 표시됩니다.
c1.metric("총 평가액", f"{t_eval:,.0f}원", f"{t_pl:+,.0f}원")
c2.metric("총 매입금액", f"{t_buy:,.0f}원")
c3.metric("누적 수익률", f"{t_roi:.2f}%", f"{t_roi:+.2f}%")

# 차트 섹션
st.markdown("---")
col_l, col_r = st.columns(2)
with col_l:
    st.subheader("🍩 종목별 자산 비중")
    fig = px.pie(df, values='평가금액', names='종목명', hole=0.4, color_discrete_sequence=px.colors.sequential.Blues_r)
    st.plotly_chart(fig, use_container_width=True)
with col_r:
    st.subheader("📈 종목별 수익률 현황")
    # 0을 기준으로 빨강/파랑이 갈리는 막대 차트
    fig_bar = px.bar(df.sort_values('수익률'), x='수익률', y='종목명', orientation='h',
                     color='수익률', color_continuous_scale='RdBu_r', 
                     range_color=[-max(abs(df['수익률'])+1), max(abs(df['수익률'])+1)])
    st.plotly_chart(fig_bar, use_container_width=True)

# 상세 표 (스타일 적용)
st.subheader(f"📑 {target} 상세 내역")
st.dataframe(
    df[['종목명', '수량', '매입단가', '현재가', '평가금액', '손익', '수익률']].style
    .applymap(color_positive_negative, subset=['손익', '수익률'])
    .format({'매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'}),
    hide_index=True, use_container_width=True
)

st.info(f"💡 업데이트: {datetime.now().strftime('%H:%M:%S')}")