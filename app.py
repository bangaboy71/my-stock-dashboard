import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 연결 (v36.5 베이스라인 기반 고도화)
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.8", layout="wide")

# --- [CSS: 수익표 색채 및 리서치 레이아웃 패치] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 350px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(135,206,235,0.2); background-color: rgba(135,206,235,0.03); min-height: 250px; margin-bottom: 20px; }
    .sector-title { font-size: 1.2rem; font-weight: bold; border-bottom: 3px solid #87CEEB; padding-bottom: 10px; margin-bottom: 15px; color: #87CEEB; }
    
    /* 🎯 딥다이브 카드: 2열 레이아웃 */
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 25px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.3rem; margin-bottom: 20px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 12px; }
    .insight-flex { display: flex; gap: 30px; align-items: flex-start; }
    .insight-left { flex: 1.3; }
    .insight-right { flex: 1; background: rgba(255,215,0,0.04); padding: 20px; border-radius: 10px; border-left: 5px solid #FFD700; }
    
    .research-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
    .research-table th { text-align: left; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
    .research-table td { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .target-val { color: #FFD700; font-weight: bold; }
    
    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.2rem; border: 2px solid; text-align: center; background-color: rgba(0,0,0,0.2); }
    .up-style { color: #FF4B4B; border-color: #FF4B4B; }
    .down-style { color: #87CEEB; border-color: #87CEEB; }
    
    .acc-flash-container { background: rgba(255,215,0,0.05); padding: 20px; border-radius: 10px; border: 1px dashed #FFD700; margin-top: 25px; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 데이터 엔진] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

# 연구 자료 (시사점 포함)
RESEARCH_DATA = {
    "삼성전자": {"desc": "2026년 영업이익 185조원 목표의 압도적 모멘텀.", "metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("PER", "15.2배", "9.1배"), ("시가배당률", "1.9%", "4.5~6.0%")], "implications": ["HBM3E 양산 본격화 및 파운드리 수익성 개선", "특별 배당 포함 시 연 6% 수준의 환원 기대", "AI 서버 중심 메모리 수요 폭증에 따른 체질 개선"]},
    "KT&G": {"desc": "ROE 15% 달성 및 자사주 소각을 통한 밸류업 구간 진입.", "metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("PBR", "1.25배", "1.40배"), ("정규 DPS", "6,000원", "6,400~6,600원")], "implications": ["해외 궐련 수출 확대 및 NGP 성장 동력 확보", "2027년까지 발행주식 20% 소각 진행", "글로벌 신공장 가동을 통한 공급망 강화"]},
    "테스": {"desc": "반도체 선단공정 장비 국산화 및 수익성 점프 예상.", "metrics": [("영업이익률", "10.7%", "19.0%"), ("ROE", "6.2%", "14.5%"), ("PER", "18.5배", "11.2배"), ("정규 DPS", "500원", "700~900원")], "implications": ["선단 공정 장비 수요 회복에 따른 이익률 개선", "2026년 ROE 14.5% 달성 전망의 성장 가치주", "안정적 재무 구조 기반의 배당 확대 기조"]},
    # (기타 종목 생략 - v36.7과 동일하게 유지됨)
}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def get_market_indices():
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            market[code] = {"now": val, "diff": raw[0].replace("상승","+").replace("하락","-"), "rate": raw[1], "style": "up-style" if "+" in raw[0] or "상승" in raw[0] else "down-style"}
    except: market = {"KOSPI": {"now": "-", "diff": "-", "rate": "-", "style": ""}, "KOSDAQ": {"now": "-", "diff": "-", "rate": "-", "style": ""}}
    return market

def get_stock_data(name):
    code = STOCK_CODES.get(str(name).replace(" ", ""))
    if not code: return 0, 0
    try:
        res = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        now_p = int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
        prev_p = int(soup.find("td", {"class": "first"}).find("span", {"class": "blind"}).text.replace(",", ""))
        return now_p, prev_p
    except: return 0, 0

# --- [3. 데이터 로드 및 전일 대비 지표 산출] ---
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['전일평가금액'] = full_df['수량'] * full_df['전일종가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비손익'] = full_df['평가금액'] - full_df['전일평가금액']
    full_df['전일대비변동률'] = (full_df['전일대비손익'] / full_df['전일평가금액'].replace(0, float('nan')) * 100).fillna(0)

# --- [4. 맞춤형 색채 맵핑 함수] ---
def style_summary(df):
    def apply_color(row):
        # 평가금액 색채: 평가금액 vs 매입금액
        eval_color = '#FF4B4B' if row['평가금액'] > row['매입금액'] else '#87CEEB' if row['평가금액'] < row['매입금액'] else 'white'
        # 기타 변동 지표 색채
        profit_color = '#FF4B4B' if row['손익'] > 0 else '#87CEEB' if row['손익'] < 0 else 'white'
        daily_color = '#FF4B4B' if row['전일대비손익'] > 0 else '#87CEEB' if row['전일대비손익'] < 0 else 'white'
        
        return [
            '', # 계좌명
            '', # 매입금액
            f'color: {eval_color}', # 평가금액 (요청 반영)
            f'color: {profit_color}', # 손익
            f'color: {daily_color}', # 전일대비손익
            f'color: {daily_color}', # 전일대비변동률
            f'color: {profit_color}'  # 누적수익률
        ]
    return df.style.apply(apply_color, axis=1)

def style_holdings(df):
    def apply_color(row):
        # 현재가 색채: 현재가 vs 매입단가 (요청 반영)
        price_color = '#FF4B4B' if row['현재가'] > row['매입단가'] else '#87CEEB' if row['현재가'] < row['매입단가'] else 'white'
        # 기타 지표
        daily_color = '#FF4B4B' if row['전일대비손익'] > 0 else '#87CEEB' if row['전일대비손익'] < 0 else 'white'
        total_color = '#FF4B4B' if row['누적수익률'] > 0 else '#87CEEB' if row['누적수익률'] < 0 else 'white'
        
        return [
            '', '', '', '', # 종목명, 수량, 매입단가, 매입금액
            f'color: {price_color}', # 현재가 (요청 반영)
            '', # 평가금액
            f'color: {daily_color}', # 전일대비손익
            f'color: {daily_color}', # 전일대비변동률
            f'color: {total_color}'   # 누적수익률
        ]
    return df.style.apply(apply_color, axis=1)

# --- [5. UI 구성] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v36.8</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy, t_prev = full_df['평가금액'].sum(), full_df['매입금액'].sum(), full_df['전일평가금액'].sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("총 누적 손익", f"{t_eval-t_buy:+,.0f}원", f"{t_eval-t_prev:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{(t_eval/t_prev-1)*100 if t_prev>0 else 0:+.2f}%")
    
    st.divider()
    st.subheader("투자 주체별 성과 요약")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum', '전일대비손익':'sum'}).reset_index()
    sum_acc['누적수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    sum_acc['전일대비변동률'] = (sum_acc['전일대비손익'] / (sum_acc['평가금액'] - sum_acc['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    
    # 🎯 [조정] 전일대비변동률을 누적수익률 좌측으로 이동
    sum_acc = sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비손익', '전일대비변동률', '누적수익률']]
    
    st.dataframe(style_summary(sum_acc).format({
        '매입금액':'{:,.0f}원', '평가금액':'{:,.0f}원', '손익':'{:+,.0f}원', 
        '전일대비손익':'{:+,.0f}원', '전일대비변동률':'{:+.2f}%', '누적수익률':'{:+.2f}%'
    }), use_container_width=True, hide_index=True)

    # (이후 KOSPI 그래프, 리포트, 섹터 리포트 v36.5 원형 유지)

# [투자 주체별 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        # 상단 메트릭
        a_buy, a_eval, a_prev = sub_df['매입금액'].sum(), sub_df['평가금액'].sum(), sub_df['전일평가금액'].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원")
        c2.metric("매입원금", f"{a_buy:,.0f}원")
        c3.metric("총 누적 손익", f"{a_eval-a_buy:+,.0f}원", f"{a_eval-a_prev:+,.0f}원")
        c4.metric("누적 수익률", f"{(a_eval/a_buy-1)*100:.2f}%", f"{(a_eval/a_prev-1)*100 if a_prev>0 else 0:+.2f}%")
        
        # 🎯 [수정] 보유종목 상세 표 (현재가 색채 맵핑 적용)
        st.dataframe(style_holdings(sub_df[[
            '종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '전일대비손익', '전일대비변동률', '누적수익률'
        ]]).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '매입금액': '{:,.0f}원', '현재가': '{:,.0f}원', 
            '평가금액': '{:,.0f}원', '전일대비손익': '{:+,.0f}원', '전일대비변동률': '{:+.2f}%', '누적수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        # (이후 딥다이브, 그래프, 뉴스 피드 v36.7 원형 유지)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")
