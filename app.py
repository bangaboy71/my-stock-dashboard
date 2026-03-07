import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import time
import re

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v30.4", layout="wide")

# --- [CSS: 지수 시인성 및 리포트 레이아웃 최적화] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 850px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.12); background-color: rgba(255,255,255,0.04); min-height: 550px; margin-bottom: 20px; }
    .sector-title { font-size: 1.3rem; font-weight: bold; border-bottom: 4px solid #87CEEB; padding-bottom: 12px; margin-bottom: 15px; color: #87CEEB; }
    .market-tag { background-color: rgba(135,206,235,0.2); padding: 5px 12px; border-radius: 6px; color: #87CEEB; font-weight: bold; margin-bottom: 10px; display: inline-block; font-size: 0.9em; }
    .leader-tag { background-color: rgba(255,215,0,0.15); border: 1px solid rgba(255,215,0,0.4); padding: 6px 12px; border-radius: 6px; color: #FFD700; font-weight: bold; margin-bottom: 12px; display: inline-block; font-size: 0.9em; }
    
    /* 지수 표시판: 음양 색채 반영 (상승: 붉은색 배경, 하락: 푸른색 배경) */
    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.3rem; border: 2px solid; text-align: center; }
    .up-style { background-color: rgba(255, 75, 75, 0.2); color: #FF4B4B; border-color: #FF4B4B; }
    .down-style { background-color: rgba(135, 206, 235, 0.2); color: #87CEEB; border-color: #87CEEB; }
    </style>
    """, unsafe_allow_html=True)

# --- [시트 및 시간 설정] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"
def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

# --- [시장 지수 파싱 엔진] ---
def get_market_indices():
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            diff = raw[0].replace("상승","+").replace("하락","-").strip()
            rate = raw[1].replace("상승","").replace("하락","").strip()
            cls = "up-style" if "+" in diff else "down-style" if "-" in diff else ""
            market[code] = {"now": val, "diff": diff, "rate": rate, "style": cls}
    except:
        market = {"KOSPI": {"now": "-", "diff": "-", "rate": "-", "style": ""}, "KOSDAQ": {"now": "-", "diff": "-", "rate": "-", "style": ""}}
    return market

# --- [데이터 로드 및 전처리] ---
full_df = conn.read(worksheet=STOCKS_SHEET, ttl="1m")
history_df = conn.read(worksheet=TREND_SHEET, ttl=0)

def get_stock_data(name):
    STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}
    code = STOCK_CODES.get(str(name).replace(" ", ""))
    if not code: return 0, 0
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
        now_p = int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
        prev_p = int(soup.find("td", {"class": "first"}).find("span", {"class": "blind"}).text.replace(",", ""))
        return now_p, prev_p
    except: return 0, 0

for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
prices = full_df['종목명'].apply(get_stock_data).tolist()
full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
full_df['매입금액'], full_df['평가금액'], full_df['전일평가금액'] = full_df['수량']*full_df['매입단가'], full_df['수량']*full_df['현재가'], full_df['수량']*full_df['전일종가']
full_df['주가변동'], full_df['손익'] = full_df['현재가']-full_df['매입단가'], full_df['평가금액']-full_df['매입금액']
full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)
full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

# --- [사이드바 관리 메뉴] ---
def record_performance():
    today = now_kst.date()
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    new_row = {"Date": today, "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    updated_df = pd.concat([history_df, pd.DataFrame([new_row])], ignore_index=True)
    conn.update(worksheet=TREND_SHEET, data=updated_df); st.sidebar.success("✅ 저장 완료!"); st.cache_data.clear(); st.rerun()

st.sidebar.header("🕹️ 관리 메뉴")
if st.sidebar.button("🔄 실시간 데이터 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 오늘의 결과 저장/덮어쓰기"): record_performance()

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v30.4</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원")
    m2.metric("총 매입금액", f"{t_buy:,.0f}원")
    m3.metric("총 손익", f"{t_eval-t_buy:+,.0f}원")
    m4.metric("누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%")

    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    idx_l.markdown(f"<div class='index-indicator {m_idx['KOSPI']['style']}'>KOSPI: {m_idx['KOSPI']['now']} ({m_idx['KOSPI']['diff']}, {m_idx['KOSPI']['rate']})</div>", unsafe_allow_html=True)
    idx_r.markdown(f"<div class='index-indicator {m_idx['KOSDAQ']['style']}'>KOSDAQ: {m_idx['KOSDAQ']['now']} ({m_idx['KOSDAQ']['diff']}, {m_idx['KOSDAQ']['rate']})</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    rep_l, rep_r = st.columns(2)
    with rep_l:
        st.markdown(f"""<div class='report-box'>
            <h4 style='color: #87CEEB;'>🇰🇷 국내 시장 상세 분석</h4>
            <div class='market-tag'>데일리 시장 총평</div>
            <p>2026년 3월 7일 현재, 국내 증시는 고환율(1,450원 이상)과 미 중간선거(11월 예정) 불확실성 속에서 <b>수익성 기반 압축 장세</b>를 보이고 있습니다. 외국인 자금 이탈이 관찰되나 기관의 저가 매수세가 지수 하단을 방어하려는 시도가 강합니다.</p>
            <div class='market-tag'>KOSPI 시장 진단</div>
            <p>코스피는 삼성전자와 SK하이닉스 등 시총 상위주가 미국 나스닥 기술주 조정의 직접적 영향을 받으며 <b>2,550~2,650선 박스권</b> 지지력을 테스트 중입니다. 5,000선은 여전히 장기적 과제이나 밸류업 대형주 중심의 하방 경직성은 견조합니다.</p>
            <div class='market-tag'>KOSDAQ 시장 진단</div>
            <p>코스닥은 800선 중반에서 제약/바이오 대장주들의 임상 모멘텀이 지수를 견인 중입니다. 2차전지는 바닥 확인 과정에 있으며, 로봇/AI 섹터로의 유동성 유입이 뚜렷합니다.</p>
        </div>""", unsafe_allow_html=True)
    
    with rep_r:
        st.markdown(f"""<div class='report-box'>
            <h4 style='color: #FF4B4B;'>🌍 글로벌 시장 및 매크로 분석</h4>
            <div class='market-tag'>미국 증시: 기술주 중심 변동성 확대</div>
            <p>뉴욕 증시는 나스닥 기술주 중심의 차익 실현 매물 출회로 하락 마감했습니다. AI 관련 실질 실적 검증 단계에 진입하며 밸류에이션 재평가가 진행 중입니다.</p>
            <div class='market-tag'>원/달러 환율 및 중간선거 변수</div>
            <p>환율은 <b>1,400원 중후반대</b>를 기록 중입니다. 2026년 11월 예정된 <b>미국 중간선거</b>는 행정부 무역 기조의 변곡점이 될 수 있어 자동차/로봇 섹터의 정책 리스크 관리가 필요합니다.</p>
            <div class='market-tag'>가족 자산 대응 전략</div>
            <p>수출 대장주(현대차 등)와 경기 방어적 고배당주(KT&G 등)의 비중을 조절하여 고환율 국면에서의 현금 흐름 안정성을 확보해야 합니다.</p>
        </div>""", unsafe_allow_html=True)

    st.divider()
    st.subheader("📊 관심 섹터 인텔리전스 (주도 대장주)")
    sec_cols = st.columns(3)
    sectors = {
        "반도체 / IT": {"주도주": "삼성전자, SK하이닉스, 한미반도체, 이수페타시스, DB하이텍", "전망": "AI 인프라 투자의 수익화 단계 진입으로 실적 기대."},
        "모빌리티 / 로봇": {"주도주": "현대차, 기아 (KOSPI), 두산로보틱스, 레인보우로보틱스, HLB (KOSDAQ 3)", "전망": "지능형 로봇법 개정에 따른 서비스 로봇 시장 개방 수혜."},
        "전력 / ESS": {"주도주": "LS ELECTRIC, 일진전기, 현대일렉트릭", "전망": "미국 노후 전력망 교체 및 AI 데이터센터 건설 수혜 지속."}
    }
    for i, (n, d) in enumerate(sectors.items()):
        with sec_cols[i % 3]:
            st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><div class='leader-tag'>👑 주도주: {d['주도주']}</div><p style='font-size: 0.85em;'><b>🔭 전망:</b> {d['전망']}</p></div>", unsafe_allow_html=True)

# 계좌별 탭 (v28.3 지침 준수)
render_account_tab = lambda acc, tab: tab.dataframe(full_df[full_df['계좌명']==acc], hide_index=True)
render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v30.4 복구 버전")
