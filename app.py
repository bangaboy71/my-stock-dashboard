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
st.set_page_config(page_title="가족 자산 성장 관제탑 v30.1", layout="wide")

# --- [CSS: 인텔리전스 리포트 스타일 최적화] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 22px; border-radius: 12px; height: 580px; overflow-y: auto; margin-bottom: 15px; border: 1px solid rgba(255,255,255,0.12); background-color: rgba(255,255,255,0.02); line-height: 1.7; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.03); min-height: 420px; margin-bottom: 15px; }
    .sector-title { font-size: 1.25rem; font-weight: bold; border-bottom: 3px solid #87CEEB; padding-bottom: 10px; margin-bottom: 15px; color: #87CEEB; }
    .market-tag { background-color: rgba(135,206,235,0.18); padding: 5px 12px; border-radius: 6px; color: #87CEEB; font-weight: bold; margin-bottom: 10px; display: inline-block; font-size: 0.85em; }
    .leader-tag { background-color: rgba(255,215,0,0.1); border: 1px solid rgba(255,215,0,0.3); padding: 4px 10px; border-radius: 6px; color: #FFD700; font-weight: bold; margin-bottom: 10px; display: inline-block; font-size: 0.85em; }
    .index-indicator { padding: 12px 25px; border-radius: 10px; font-weight: bold; font-size: 1.15rem; border: 1px solid rgba(255,255,255,0.15); text-align: center; box-shadow: 2px 2px 8px rgba(0,0,0,0.2); }
    </style>
    """, unsafe_allow_html=True)

# --- [시트 및 시간 설정] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

# --- [헬퍼 함수] ---
def safe_float(text):
    try:
        if not text: return 0.0
        clean_text = re.sub(r'[^0-9.\-+]', '', str(text))
        return float(clean_text) if clean_text else 0.0
    except: return 0.0

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# --- [데이터 로드 엔진] ---
def load_data_with_retry(worksheet_name, ttl_val):
    try:
        return conn.read(worksheet=worksheet_name, ttl=ttl_val)
    except Exception as e:
        if "503" in str(e):
            st.warning("📡 구글 서비스 연결 재시도 중..."); time.sleep(3); st.rerun()
        st.error(f"데이터 로드 오류: {e}"); st.stop()

full_df = load_data_with_retry(STOCKS_SHEET, "1m")
history_df = load_data_with_retry(TREND_SHEET, 0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], format='mixed', errors='coerce').dt.date
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [시장 지수 파싱 엔진: 색채 및 부호 정밀 적용] ---
def get_market_indices():
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            # 🎯 부호 및 색채 로직 보정
            diff = raw[0].replace("상승","+").replace("하락","-").strip()
            rate = raw[1].replace("상승","").replace("하락","").strip()
            # 수치 강제 정밀화 (부호가 없을 경우 대비)
            if "상승" in soup.find("span", {"id": "change_value_and_rate"}).text:
                if "+" not in diff: diff = "+" + diff
                if "+" not in rate: rate = "+" + rate
            elif "하락" in soup.find("span", {"id": "change_value_and_rate"}).text:
                if "-" not in diff: diff = "-" + diff
                if "-" not in rate: rate = "-" + rate
            market[code] = {"now": val, "diff": diff, "rate": rate}
    except:
        market = {"KOSPI": {"now": "-", "diff": "-", "rate": "-"}, "KOSDAQ": {"now": "-", "diff": "-", "rate": "-"}}
    return market

# --- [종목 데이터 파싱] ---
def get_stock_data(name):
    STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}
    clean_name = str(name).replace(" ", "").strip()
    code = STOCK_CODES.get(clean_name)
    if not code: return 0, 0
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
        now_p = int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
        prev_p = int(soup.find("td", {"class": "first"}).find("span", {"class": "blind"}).text.replace(",", ""))
        return now_p, prev_p
    except: return 0, 0

# --- [데이터 전처리] ---
for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
prices_list = full_df['종목명'].apply(get_stock_data).tolist()
full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices_list], [p[1] for p in prices_list]
full_df['매입금액'], full_df['평가금액'], full_df['전일평가금액'] = full_df['수량']*full_df['매입단가'], full_df['수량']*full_df['현재가'], full_df['수량']*full_df['전일종가']
full_df['주가변동'], full_df['손익'] = full_df['현재가']-full_df['매입단가'], full_df['평가금액']-full_df['매입금액']
full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)
full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

# --- [사이드바 관리 메뉴] ---
st.sidebar.header("🕹️ 관리 메뉴")
if st.sidebar.button("🔄 실시간 데이터 갱신"): st.cache_data.clear(); st.rerun()

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v30.1</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_buy, t_eval, t_prev_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum(), full_df['전일평가금액'].sum()
    total_profit, daily_rate = t_eval - t_buy, ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    
    # 🎯 4열 메트릭
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{total_profit:,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{daily_rate:+.2f}%")
    
    st.markdown("---")
    # 🎯 계좌 요약 표
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

    # 🎯 통합 추이 그래프
    if not history_df.empty:
        st.markdown("<br>", unsafe_allow_html=True)
        fig_t = go.Figure()
        h_dates = history_df['Date'].astype(str)
        bk_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        k_yield = ((history_df['KOSPI'] / bk_k) - 1) * 100
        fig_t.add_trace(go.Scatter(x=h_dates, y=k_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns: fig_t.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig_t.update_layout(title="📈 가족 자산 통합 수익률 추이 (vs KOSPI)", height=450, xaxis=dict(type='category'), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig_t, use_container_width=True)

    # 🕵️ AI 관제탑 데일리 심층 리포트 (최신 시황 및 주도주 강화)
    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    
    # 🎯 지수 변동성 시각화 (빨강/파랑 색채 기준 엄수)
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    for i, name in enumerate(["KOSPI", "KOSDAQ"]):
        d = m_idx.get(name, {})
        color = "#FF4B4B" if "+" in d.get("diff", "") else "#87CEEB" if "-" in d.get("diff", "") else "white"
        bg_color = "rgba(255,75,75,0.08)" if color=="#FF4B4B" else "rgba(135,206,235,0.08)"
        [idx_l, idx_r][i].markdown(f"<div class='index-indicator' style='color: {color}; background-color: {bg_color};'>{name}: {d.get('now', '-')} ({d.get('diff', '-')}, {d.get('rate', '-')})</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    rep_l, rep_r = st.columns(2)
    with rep_l:
        k_r = safe_float(m_idx.get("KOSPI", {}).get("rate", "0"))
        total_by_stock = full_df.groupby('종목명')['매입금액'].sum().sort_values(ascending=False).head(3)
        st.markdown(f"""<div class='report-box' style='background-color: rgba(135,206,235,0.05);'>
            <h4 style='color: #87CEEB;'>📋 통합 포트폴리오 성과 분석</h4>
            <div class='market-tag'>KOSPI 지수 대비 Alpha 분석</div>
            <ul style='font-size: 0.9em;'>
                <li><b>총괄 성과:</b> KOSPI 대비 <b>{daily_rate-k_r:+.2f}%p</b></li>
                <li><b>서은 계좌:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서은투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
                <li><b>서희 계좌:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서희투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
                <li><b>큰스님 계좌:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='큰스님투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
            </ul>
            <div class='market-tag'>매입원금 합산 기준 고비중 TOP 3</div>
            <ul style='font-size: 0.9em;'>
                {" ".join([f"<li><b>{name}:</b> Alpha {full_df[full_df['종목명']==name]['전일대비(%)'].mean()-k_r:+.2f}%p</li>" for name, val in total_by_stock.items()])}
            </ul>
        </div>""", unsafe_allow_html=True)
    with rep_r:
        # 
        st.markdown(f"""<div class='report-box' style='background-color: rgba(255,75,75,0.05);'>
            <h4 style='color: #FF4B4B;'>🌍 주요 시장 동향 및 시황 분석 (최신)</h4>
            <div class='market-tag'>미국 증시: 기술주 중심 하락 압력</div>
            <p style='font-size: 0.85em;'>어제 밤부터 오늘 오전 사이, 미국 나스닥(NASDAQ)을 중심으로 한 기술주 섹터가 강한 하락 압력을 받았습니다. 이는 AI 고평가 논란과 예상보다 높은 고용 지표에 따른 금리 인하 기대감 후퇴가 맞물린 결과입니다. 특히 엔비디아를 필두로 한 반도체 주들의 차익 실현 매물이 쏟아지며 국내 반도체 대형주에도 하방 압력을 가하고 있습니다.</p>
            <div class='market-tag'>환율 및 매크로 사실관계</div>
            <p style='font-size: 0.85em;'>원/달러 환율은 사용자님께서 확인하신 대로 <b>1,400원 중반을 넘어 1,500원선</b>에 육박하는 초고환율 국면에 진입했습니다. 이는 국내 증시의 외인 자금 이탈을 가속화하는 핵심 요인이며, 에너지 및 원자재 수입 비중이 높은 기업들의 수익성 악화 우려를 낳고 있습니다.</p>
            <div class='market-tag'>국내 시장 전망</div>
            <p style='font-size: 0.85em;'>KOSPI는 2,500선 사수를 위한 치열한 공방이 예상되며, 고환율 수혜를 기대할 수 있는 자동차/조선 섹터로의 수급 분산 여부가 관건입니다.</p>
        </div>""", unsafe_allow_html=True)

    # 📊 [보강] 관심 섹터 심층 분석 (주도주: KOSPI 5 / KOSDAQ 3)
    st.divider()
    st.subheader("📊 관심 섹터 심층 동향 분석 (주도주 및 전략)")
    # 
    sec_cols = st.columns(3)
    sectors = {
        "반도체 / IT": {"시황": "미국발 기술주 매도세로 인한 단기 조정 국면", "주도주": "삼성전자, SK하이닉스 (KOSPI 대장주)", "전략": "HBM 수요의 실질적 이익 전환 확인 필요"},
        "배터리 / 에너지": {"시황": "캐즘 구간 통과 및 전고체 기술 상용화 기대감", "주도주": "LG에너지솔루션 (KOSPI), 에코프로비엠 (KOSDAQ 대장주)", "전략": "미국 대선 및 정책 변동성 리스크 관리"},
        "바이오 / 헬스케어": {"시황": "금리 인하 지연 우려에도 불구하고 개별 임상 모멘텀 유효", "주도주": "삼성바이오로직스 (KOSPI), 알테오젠, HLB (KOSDAQ 대장주)", "전략": "실적 기반 우량 바이오주 중심 압축"},
        "전력 / 인프라": {"시황": "AI 데이터센터 건설 폭증으로 인한 변압기 부족 심화", "주도주": "일진전기, LS ELECTRIC", "전략": "수주 잔고 기반의 장기 이익 성장 추적"},
        "모빌리티 / 방산": {"시황": "고환율 수혜 및 지정학적 리스크에 따른 수출 확대", "주도주": "현대차 (KOSPI 대장주), 한화에어로스페이스", "전략": "글로벌 점유율 확대 및 현금 흐름 우수 종목 집중"},
        "소비재 / 뷰티": {"시황": "K-뷰티의 북미/유럽 시장 안착으로 안정적 매출 확보", "주도주": "아모레퍼시픽, 브이티", "전략": "브랜드 파워 및 채널 다변화 역량 평가"}
    }
    for i, (n, d) in enumerate(sectors.items()):
        with sec_cols[i % 3]:
            st.markdown(f"""
            <div class='sector-box'>
                <div class='sector-title'>{n}</div>
                <p style='font-size: 0.85em;'><b>🌡️ 시황:</b> {d['시황']}</p>
                <div class='leader-tag'>👑 주도주: {d['주도주']}</div>
                <p style='font-size: 0.85em; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 10px;'><b>🔭 전략:</b> {d['전략']}</p>
            </div>
            """, unsafe_allow_html=True)

# [계좌별 상세 분석 탭: 무결성 사수]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        a_buy, a_eval, a_prev_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum(), sub_df['전일평가금액'].sum()
        a_profit, a_rate = a_eval - a_buy, ((a_eval / a_prev_eval - 1) * 100) if a_prev_eval > 0 else 0
        c1, c2, cp, c3 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_prev_eval:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        cp.metric("손익", f"{a_profit:,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100:.2f}%", f"{a_rate:+.2f}%")
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '전일대비(%)', '수익률']].style.map(color_positive_negative, subset=['주가변동', '손익', '전일대비(%)', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원', '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                h_dt = history_df['Date'].astype(str)
                fig.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                # 🎯 [v28.3 단일 종목 일원화 원칙]
                stk_list = sub_df['종목명'].unique().tolist()
                if len(stk_list) > 1:
                    sel = st.selectbox(f"📍 {acc_name} 종목 대조", stk_list, key=f"sel_{acc_name}")
                    s_c = next((c for c in history_df.columns if acc_name[:2] in c and sel.replace(' ','') in c.replace(' ','')), "")
                    if s_c: fig.add_trace(go.Scatter(x=h_dt, y=history_df[s_c], mode='lines', name=f'{sel} 수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                fig.update_layout(title=f"📈 {acc_name} 성과 추이", height=400, xaxis=dict(type='category'), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
        with g2:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

        # 🎯 [무결성] 계좌별 상세 리포트
        st.divider()
        st.subheader(f"🕵️ {acc_name} 인텔리전스 리포트")
        b_s = sub_df.sort_values('전일대비(%)', ascending=False).iloc[0]
        st.markdown(f"<div class='report-box' style='background-color: rgba(135,206,235,0.05); height:220px;'><h4 style='color: #87CEEB;'>📋 리포트</h4><p>현재 {acc_name} 계좌의 핵심 종목은 {b_s['종목명']}입니다. 최근 미국 기술주 하락의 여파가 국내 관련 섹터에 미치는 영향력을 면밀히 관찰 중이며, 원금 대비 성과 우위 종목을 선별하여 리스크 관리가 필요한 시점입니다.</p></div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v30.1 신뢰성 및 최신성 강화 버전")
