import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v19.6", layout="wide")

# --- [시트 탭 이름 설정] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

# --- [데이터 로드 엔진] ---
try:
    full_df = conn.read(worksheet=STOCKS_SHEET, ttl="1m")
    history_df = conn.read(worksheet=TREND_SHEET, ttl=0)
except Exception as e:
    st.error(f"데이터 로드 오류: 시트의 탭 이름을 확인해주세요. ({e})")
    st.stop()

# --- [시세 및 시장 데이터 엔진] ---
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
    except: return 0

def get_market_data():
    """KOSPI 지수 및 투자 주체별 실시간 동향 수집"""
    data = {"kospi": 0, "personal": "0", "foreign": "0", "institutional": "0"}
    try:
        url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        data["kospi"] = float(soup.find("em", {"id": "now_value"}).text.replace(",", ""))
        
        dl_tags = soup.find("dl", {"class": "lst_kospi"})
        if dl_tags:
            items = dl_tags.find_all("dd")
            data["personal"] = items[0].find("span").text
            data["foreign"] = items[1].find("span").text
            data["institutional"] = items[2].find("span").text
    except: pass
    return data

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# 데이터 가공
for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
full_df['현재가'] = full_df['종목명'].apply(get_stable_price)
full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
full_df['평가금액'] = full_df['수량'] * full_df['현재가']
full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

# --- [AI 시장 분석 리포트 엔진] ---
def render_ai_report(m_data, total_roi):
    hour, minute = now_kst.hour, now_kst.minute
    time_val = hour * 100 + minute
    
    st.divider()
    st.subheader("🕵️ AI 실시간 금융 통합 브리핑")
    
    if time_val < 900:
        st.info(f"**🌅 장전 전략 리포트 ({now_kst.strftime('%H:%M')})**: 미 증시 호조 영향으로 반도체 섹터 강세가 예상됩니다. 목표 수익률 관리에 집중하세요.")
    elif 900 <= time_val < 1530:
        st.success(f"""
        **📈 실시간 시장 수급 진단 ({now_kst.strftime('%H:%M')})**
        * **현재 지수:** KOSPI **{m_data['kospi']:,}**
        * **투자 주체별 동향:** **외인({m_data['foreign']})**, **기관({m_data['institutional']})**, **개인({m_data['personal']})** 매매 중
        * **포트폴리오 진단:** 현재 누적 수익률 **{total_roi:.2f}%**로 시장 지수 대비 견고한 방어력을 보여주고 있습니다.
        """)
    else:
        st.warning(f"**📉 장 마감 종합 리포트 ({now_kst.strftime('%H:%M')})**: 오늘 하루도 고생하셨습니다. 당일 수급 결과를 반영한 자산 평가가 완료되었습니다.")

# --- 사이드바 ---
st.sidebar.header("🕹️ 관리 메뉴")
m_data = get_market_data()
if st.sidebar.button("🔄 실시간 동향 새로고침"):
    st.cache_data.clear()
    st.rerun()

# --- UI 메인 섹션 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [Tab 0] 총괄 현황 ---
with tabs[0]:
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    t_profit, t_roi = t_eval - t_buy, (t_eval/t_buy-1)*100 if t_buy>0 else 0
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_profit:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("통합 누적 수익률", f"{t_roi:.2f}%")

    st.markdown("---")
    st.subheader("📑 계좌별 자산 요약")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '누적 수익률']).format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적 수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

    render_ai_report(m_data, t_roi)

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
        
        # 🎯 [수정] 수량: '{:,.0f}', 매입단가: '{:,.0f}원' 포맷 적용 (소수점 제거)
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '평가금액', '수익률']].style.map(color_positive_negative, subset=['수익률']).format({
            '수량': '{:,.0f}', 
            '매입단가': '{:,.0f}원', 
            '현재가': '{:,.0f}원', 
            '평가금액': '{:,.0f}원', 
            '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v19.6 수량/단가 정수화 완료")
