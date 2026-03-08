import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import re

# 1. 설정 및 연결 (v31.6 원형 100% 사수)
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.0", layout="wide")

# --- [CSS: v31.6 스타일 및 연구 자료 전용 UI 패치] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 750px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.04); min-height: 500px; margin-bottom: 20px; }
    .sector-title { font-size: 1.3rem; font-weight: bold; border-bottom: 4px solid #87CEEB; padding-bottom: 12px; margin-bottom: 15px; color: #87CEEB; }
    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.2rem; border: 2px solid; text-align: center; box-shadow: 4px 4px 15px rgba(0,0,0,0.3); background-color: rgba(0,0,0,0.2); }
    .up-style { color: #FF4B4B; border-color: #FF4B4B; background-color: rgba(255, 75, 75, 0.05); }
    .down-style { color: #87CEEB; border-color: #87CEEB; background-color: rgba(135, 206, 235, 0.05); }
    
    /* 🎯 연구 자료 전용 딥다이브 카드 */
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.2); margin-bottom: 25px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.25rem; margin-bottom: 15px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 10px; }
    .research-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.95rem; }
    .research-table th { text-align: left; padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
    .research-table td { padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .target-val { color: #FFD700; font-weight: bold; }
    
    .acc-flash-container { background: rgba(255,215,0,0.05); padding: 15px; border-radius: 10px; border: 1px dashed #FFD700; margin-top: 20px; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 핵심 데이터 엔진: 연구 자료 통합] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

# 업로드된 시트 기반 연구 데이터 (보통주 + ETF)
RESEARCH_DATA = {
    "삼성전자": {"desc": "2026년 영업이익 185조원 목표의 압도적 모멘텀.", "metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("PER", "15.2배", "9.1배"), ("시가배당률", "1.9%", "4.5~6.0%")]},
    "KT&G": {"desc": "ROE 15% 달성 및 자사주 소각을 통한 밸류업 구간 진입.", "metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("PBR", "1.25배", "1.40배"), ("정규 DPS", "6,000원", "6,400~6,600원")]},
    "LG에너지솔루션": {"desc": "이차전지 수익성 개선 및 2026년 영업이익 4.8조 타겟.", "metrics": [("영업이익률", "6.5%", "10.6%"), ("ROE", "5.2%", "11.5%"), ("PER", "65.0배", "32.0배"), ("시가배당률", "0.35%", "0.5~0.8%")]},
    "현대글로비스": {"desc": "물류 효율 극대화 및 DPS 8,000원 시대를 향한 성장.", "metrics": [("영업이익률", "6.2%", "6.7%"), ("ROE", "12.8%", "14.5%"), ("PER", "9.2배", "8.1배"), ("정규 DPS", "6,300원", "7,500~8,000원")]},
    "에스티팜": {"desc": "RNA 치료제 CDMO 모멘텀으로 영업이익 0.12조 달성 전망.", "metrics": [("영업이익률", "14.3%", "20.7%"), ("ROE", "8.5%", "18.2%"), ("PER", "45.0배", "22.5배"), ("시가배당률", "0.5%", "0.8~1.2%")]},
    "테스": {"desc": "반도체 선단공정 수혜로 2026년 이익률 19% 점프 예상.", "metrics": [("영업이익률", "10.7%", "19.0%"), ("ROE", "6.2%", "14.5%"), ("PER", "18.5배", "11.2배"), ("정규 DPS", "500원", "700~900원")]},
    "일진전기": {"desc": "북미 전력 인프라 교체 주기에 따른 ROE 22.5% 타겟.", "metrics": [("영업이익률", "6.2%", "8.6%"), ("ROE", "15.2%", "22.5%"), ("PER", "18.0배", "12.5배"), ("시가배당률", "1.5%", "2.0~2.5%")]},
    "SK스퀘어": {"desc": "지주사 할인율 45% 축소 및 자사주 소각 최대 0.8조 목표.", "metrics": [("ROE", "4.5%", "9.8%"), ("PBR", "0.45배", "0.65배"), ("NAV 할인율", "65.0%", "45.0%"), ("자사주 소각", "0.2조", "0.5~0.8조")]},
    "현대차2우B": {"desc": "배당 성향 25% 유지 및 은퇴 포트폴리오의 강력한 현금원.", "metrics": [("영업이익률", "6.2%", "7.0%"), ("ROE", "13.0%", "15.5%"), ("시가배당률", "5.7%", "6.4%"), ("정규 DPS", "13,600원", "14,500~15,500원")]},
    "KODEX200타겟위클리커버드콜": {"desc": "주 단위 콜옵션 매도로 연 15% 시가분배율을 지향하는 은퇴 특화 도구.", "metrics": [("옵션 프리미엄", "연 15.0%", "연 15.0%"), ("월 분배금", "100~120원", "110~130원"), ("연환산 수익률", "12~15%", "15.0% 이상"), ("시가분배율", "연 12.5%", "연 15.0%")]}
}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

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

# (get_market_indices, get_acc_news 등 v35.6 파싱 기능 유지)
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
            market[code] = {"now": val, "diff": diff, "rate": rate, "style": "up-style" if "+" in diff else "down-style"}
    except: market = {"KOSPI": {"now": "-", "diff": "-", "rate": "-", "style": ""}, "KOSDAQ": {"now": "-", "diff": "-", "rate": "-", "style": ""}}
    return market

# --- [3. 데이터 로드 및 전처리] ---
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'], full_df['평가금액'] = full_df['수량'] * full_df['매입단가'], full_df['수량'] * full_df['현재가']
    full_df['전일평가금액'] = full_df['수량'] * full_df['전일종가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [4. 사이드바 마스터 메뉴] ---
st.sidebar.header("🕹️ 관제탑 마스터 메뉴")
if st.sidebar.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 오늘의 결과 저장/덮어쓰기"):
    today = now_kst.date()
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    new_row = {"Date": today, "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    conn.update(worksheet="trend", data=pd.concat([history_df[history_df['Date']!=today], pd.DataFrame([new_row])]).sort_values('Date'))
    st.sidebar.success(f"✅ 저장 완료"); st.rerun()

# --- [5. UI 메인 구성] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v36.0</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy, t_prev = full_df['평가금액'].sum(), full_df['매입금액'].sum(), full_df['전일평가금액'].sum()
    d_rate = ((t_eval / t_prev - 1) * 100) if t_prev > 0 else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("총 손익", f"{t_eval-t_buy:+,.0f}원", f"{t_eval-t_prev:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{d_rate:+.2f}%")
    
    st.markdown("---")
    if not history_df.empty:
        fig = go.Figure()
        h_dates = history_df['Date'].dt.date.astype(str)
        bk_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        k_yield = ((history_df['KOSPI'] / bk_k) - 1) * 100
        fig.add_trace(go.Scatter(x=h_dates, y=k_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns:
                fig.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig.update_layout(title="📈 가족 자산 통합 수익률 추이 (vs KOSPI)", xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white", height=450)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    idx_l.markdown(f"<div class='index-indicator {m_idx['KOSPI']['style']}'>KOSPI: {m_idx['KOSPI']['now']} ({m_idx['KOSPI']['diff']}, {m_idx['KOSPI']['rate']})</div>", unsafe_allow_html=True)
    idx_r.markdown(f"<div class='index-indicator {m_idx['KOSDAQ']['style']}'>KOSDAQ: {m_idx['KOSDAQ']['now']} ({m_idx['KOSDAQ']['diff']}, {m_idx['KOSDAQ']['rate']})</div>", unsafe_allow_html=True)
    
    rep_l, rep_r = st.columns(2)
    with rep_l: st.markdown("<div class='report-box'><h4 style='color:#87CEEB;'>🇰🇷 국내 시장 분석</h4><p>국내 증시는 코스피 5,000선 시대를 열며 선진국형 증시로 탈바꿈 중입니다.</p></div>", unsafe_allow_html=True)
    with rep_r: st.markdown("<div class='report-box'><h4 style='color:#FF4B4B;'>🌍 글로벌 매크로 분석</h4><p>나스닥 AI 랠리와 고환율 환경이 수출 대형주의 이익 체력을 뒷받침하고 있습니다.</p></div>", unsafe_allow_html=True)

# [계좌별 상세 분석 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        a_buy, a_eval, a_prev = sub_df['매입금액'].sum(), sub_df['평가금액'].sum(), sub_df['전일평가금액'].sum()
        a_daily_rate = ((a_eval / a_prev - 1) * 100) if a_prev > 0 else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원")
        c2.metric("매입원금", f"{a_buy:,.0f}원")
        c3.metric("총 손익", f"{a_eval-a_buy:+,.0f}원", f"{a_eval-a_prev:+,.0f}원")
        c4.metric("수익률", f"{(a_eval/a_buy-1)*100:.2f}%", f"{a_daily_rate:+.2f}%")
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '손익', '수익률']].style.map(lambda x: 'color: #FF4B4B' if x > 0 else 'color: #87CEEB', subset=['손익', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        
        # 🎯 [핵심] 연구 자료 기반 딥다이브 카드 표출
        res = RESEARCH_DATA.get(sel.replace(" ", ""))
        if res:
            rows = "".join([f"<tr><td>{m[0]}</td><td>{m[1]}</td><td class='target-val'>{m[2]}</td></tr>" for m in res['metrics']])
            st.markdown(f"""
            <div class='insight-card'>
                <div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브 (2026 Target 연구 자료 반영)</div>
                <p style='font-size: 0.9rem; color: rgba(255,255,255,0.8); margin-bottom: 15px;'>{res['desc']}</p>
                <table class='research-table'>
                    <thead><tr><th>분석 지표</th><th>2025년 (추정/실적)</th><th>2026년 (Target)</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
            """, unsafe_allow_html=True)

        g_left, g_right = st.columns([2, 1])
        with g_left:
            if not history_df.empty and history_col in history_df.columns:
                fig_acc = go.Figure()
                h_dt = history_df['Date'].dt.date.astype(str)
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                if len(sub_df) > 1:
                    s_c = next((c for c in history_df.columns if acc_name[:2] in c and sel.replace(' ','') in c.replace(' ','')), "")
                    if s_c: fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[s_c], mode='lines', name=f'{sel} 수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                fig_acc.update_layout(title=f"📈 {acc_name} 성과 추이", height=400, xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig_acc, use_container_width=True)
        with g_right:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v36.0 가디언 리서치 에디션")
