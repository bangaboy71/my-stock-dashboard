import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 연결 (v36.5 베이스라인 계승)
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.6", layout="wide")

# --- [CSS: 수익표 색채 및 레이아웃 패치] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 750px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.04); min-height: 300px; margin-bottom: 20px; }
    .sector-title { font-size: 1.3rem; font-weight: bold; border-bottom: 4px solid #87CEEB; padding-bottom: 12px; margin-bottom: 15px; color: #87CEEB; }
    
    /* 🎯 딥다이브 카드: 2열 레이아웃 */
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 25px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.25rem; margin-bottom: 15px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 10px; }
    .insight-flex { display: flex; gap: 30px; align-items: flex-start; }
    .insight-left { flex: 1.2; }
    .insight-right { flex: 1; background: rgba(255,215,0,0.03); padding: 20px; border-radius: 10px; border-left: 5px solid #FFD700; }
    
    .research-table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
    .research-table th { text-align: left; padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
    .research-table td { padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .target-val { color: #FFD700; font-weight: bold; }
    
    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.2rem; border: 2px solid; text-align: center; background-color: rgba(0,0,0,0.2); }
    .up-style { color: #FF4B4B; border-color: #FF4B4B; background-color: rgba(255, 75, 75, 0.05); }
    .down-style { color: #87CEEB; border-color: #87CEEB; background-color: rgba(135, 206, 235, 0.05); }
    
    .acc-flash-container { background: rgba(255,215,0,0.05); padding: 15px; border-radius: 10px; border: 1px dashed #FFD700; margin-top: 20px; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; cursor: pointer; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 데이터 엔진] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def color_delta(val):
    if isinstance(val, (int, float)):
        color = '#FF4B4B' if val > 0 else '#87CEEB' if val < 0 else 'white'
        return f'color: {color}'
    return ''

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

# --- [3. 데이터 로드 및 지표 산출] ---
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    
    # 지표 계산
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['전일평가금액'] = full_df['수량'] * full_df['전일종가']
    
    full_df['누적손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['누적수익률'] = (full_df['누적손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    
    # 🎯 추가: 전일 대비 변동 지표
    full_df['전일대비손익'] = full_df['평가금액'] - full_df['전일평가금액']
    full_df['전일대비변동률'] = (full_df['전일대비손익'] / full_df['전일평가금액'].replace(0, float('nan')) * 100).fillna(0)

# --- [UI 구성] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v36.6</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy, t_prev = full_df['평가금액'].sum(), full_df['매입금액'].sum(), full_df['전일평가금액'].sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("총 누적 손익", f"{t_eval-t_buy:+,.0f}원", f"{t_eval-t_prev:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{(t_eval/t_prev-1)*100 if t_prev>0 else 0:+.2f}%")
    
    st.markdown("---")
    # 🎯 [수정] 총괄탭 투자 주체별 요약 표 (전일 대비 지표 추가)
    st.subheader("투자 주체별 성과 요약")
    sum_acc = full_df.groupby('계좌명').agg({
        '매입금액': 'sum', 
        '평가금액': 'sum', 
        '누적손익': 'sum',
        '전일대비손익': 'sum'
    }).reset_index()
    sum_acc['누적수익률'] = (sum_acc['누적손익'] / sum_acc['매입금액'] * 100).fillna(0)
    sum_acc['전일대비변동률'] = (sum_acc['전일대비손익'] / (sum_acc['평가금액'] - sum_acc['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    
    st.dataframe(sum_acc.style.map(color_delta, subset=['누적손익', '누적수익률', '전일대비손익', '전일대비변동률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', 
        '누적손익': '{:+,.0f}원', '누적수익률': '{:+.2f}%',
        '전일대비손익': '{:+,.0f}원', '전일대비변동률': '{:+.2f}%'
    }), use_container_width=True, hide_index=True)

    # (이후 KOSPI 그래프 및 섹터 리포트 로직 유지)

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
        
        # 🎯 [수정] 계좌별 보유종목 표 (매입/평가액 및 전일 변동 추가)
        st.dataframe(sub_df[[
            '종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', 
            '전일대비손익', '전일대비변동률', '누적수익률'
        ]].style.map(color_delta, subset=['전일대비손익', '전일대비변동률', '누적수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '매입금액': '{:,.0f}원', 
            '현재가': '{:,.0f}원', '평가금액': '{:,.0f}원', 
            '전일대비손익': '{:+,.0f}원', '전일대비변동률': '{:+.2f}%', '누적수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        # (이후 딥다이브 레이아웃 및 뉴스 피드 로직 유지)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")
