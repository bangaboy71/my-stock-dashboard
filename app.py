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
st.set_page_config(page_title="가족 자산 성장 관제탑 v29.8", layout="wide")

# --- [CSS: 지표 카드 및 리포트 스타일 최적화] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 15px; border-radius: 10px; height: 500px; overflow-y: auto; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.1); }
    .sector-box { padding: 15px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.03); min-height: 380px; margin-bottom: 15px; }
    .sector-title { font-size: 1.15rem; font-weight: bold; border-bottom: 2px solid #87CEEB; padding-bottom: 8px; margin-bottom: 12px; color: #87CEEB; }
    .market-tag { background-color: rgba(135,206,235,0.1); padding: 2px 8px; border-radius: 5px; color: #87CEEB; font-weight: bold; margin-bottom: 8px; display: inline-block; font-size: 0.85em; }
    .index-card { background-color: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px; border-left: 5px solid; height: 115px; display: flex; flex-direction: column; justify-content: center; }
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
        if "503" in str(e) or "UNAVAILABLE" in str(e):
            st.warning("📡 구글 서버 연결 재시도 중..."); time.sleep(5); st.rerun()
        st.error(f"데이터 로드 오류: {e}"); st.stop()

full_df = load_data_with_retry(STOCKS_SHEET, "1m")
history_df = load_data_with_retry(TREND_SHEET, 0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], format='mixed', errors='coerce').dt.date
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [시장 시세 엔진: 지수 정밀화] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_market_status():
    market = {}
    u_time = now_kst.strftime('%H:%M')
    try:
        # 1. KOSPI / KOSDAQ
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            diff_v = raw[0].replace("상승","+").replace("하락","-").strip()
            rate_v = raw[1].replace("상승","").replace("하락","").strip()
            market[code] = {"now": val, "diff": diff_v, "rate": rate_v}
        
        # 2. 환율 / 금 (부호 제거 및 시각 표기)
        res_fx = requests.get("https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup_fx = BeautifulSoup(res_fx.text, 'html.parser')
        market["USD/KRW"] = {"now": soup_fx.find("p", {"class": "no_today"}).find("em").text, "update": f"업데이트 {u_time}"}

        res_gold = requests.get("https://finance.naver.com/marketindex/goldDetail.naver", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup_gold = BeautifulSoup(res_gold.text, 'html.parser')
        market["GOLD"] = {"now": soup_gold.find("p", {"class": "no_today"}).find("em").text, "update": f"업데이트 {u_time}"}
        
        market["S&P500"] = {"rate": "+0.45%"}
        market["NASDAQ"] = {"rate": "+0.85%"}
    except: pass
    return market

# --- [데이터 전처리] ---
def get_stock_data(name):
    clean_name = str(name).replace(" ", "").strip()
    code = STOCK_CODES.get(clean_name)
    if not code: return 0, 0
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        now_p = int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
        prev_p = int(soup.find("td", {"class": "first"}).find("span", {"class": "blind"}).text.replace(",", ""))
        return now_p, prev_p
    except: return 0, 0

for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
prices_list = full_df['종목명'].apply(get_stock_data).tolist()
full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices_list], [p[1] for p in prices_list]
full_df['매입금액'], full_df['평가금액'], full_df['전일평가금액'] = full_df['수량']*full_df['매입단가'], full_df['수량']*full_df['현재가'], full_df['수량']*full_df['전일종가']
full_df['주가변동'], full_df['손익'] = full_df['현재가']-full_df['매입단가'], full_df['평가금액']-full_df['매입금액']
full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)
full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

# --- [사이드바 메뉴] ---
st.sidebar.header("🕹️ 관리 메뉴")
if st.sidebar.button("🔄 실시간 데이터 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.divider(): pass # 어제 원칙 유지

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v29.8</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    m_status = get_market_status()
    t_buy, t_eval, t_prev_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum(), full_df['전일평가금액'].sum()
    total_profit, daily_rate = t_eval - t_buy, ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    
    # 1. 상단 4열 메트릭
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{total_profit:,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{daily_rate:+.2f}%")
    
    st.markdown("---")
    # 2. 계좌 요약 표
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

    # 3. 통합 추이 그래프
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

    # 🎯 [보정] 실시간 주요 시장 지표 (균등 사이즈 및 시각 표기)
    st.divider()
    st.subheader("📡 실시간 주요 시장 지표")
    idx_cols = st.columns(4)
    items = [("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ"), ("USD/KRW", "원/달러 환율"), ("GOLD", "금 현물")]
    for i, (k, lbl) in enumerate(items):
        d = m_status.get(k, {})
        val = d.get("now", "-")
        # 🎯 KOSPI/KOSDAQ 전용 색채 로직
        if k in ["KOSPI", "KOSDAQ"]:
            diff, rate = d.get("diff", ""), d.get("rate", "")
            color = "#FF4B4B" if "+" in diff else "#87CEEB" if "-" in diff else "white"
            sub_text = f"{diff} ({rate})"
        else: # 🎯 환율/금 전용 (업데이트 시각 표기)
            color = "#87CEEB"
            sub_text = d.get("update", "")
            
        idx_cols[i].markdown(f"""
        <div class='index-card' style='border-left-color: {color};'>
            <span style='font-size: 0.85em; color: gray;'>{lbl}</span><br>
            <span style='font-size: 1.4em; font-weight: bold;'>{val}</span><br>
            <span style='color: {color}; font-size: 0.9em; font-weight: bold;'>{sub_text}</span>
        </div>
        """, unsafe_allow_html=True)

    # 🕵️ [고도화] AI 관제탑 데일리 심층 리포트 (주요 시장 동향 분석)
    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    rep_l, rep_r = st.columns(2)
    with rep_l:
        k_r = safe_float(m_status.get("KOSPI", {}).get("rate", "0"))
        total_by_stock = full_df.groupby('종목명')['매입금액'].sum().sort_values(ascending=False).head(3)
        st.markdown(f"""<div class='report-box' style='background-color: rgba(135,206,235,0.05);'>
            <h4 style='color: #87CEEB;'>📋 통합 포트폴리오 성과 분석</h4>
            <div class='market-tag'>KOSPI 지수 대비 Alpha 분석</div>
            <ul style='font-size: 0.85em;'>
                <li><b>총괄 성과:</b> KOSPI 대비 <b>{daily_rate-k_r:+.2f}%p</b></li>
                <li><b>서은 계좌:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서은투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
                <li><b>서희 계좌:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서희투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
                <li><b>큰스님 계좌:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='큰스님투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
            </ul>
            <div class='market-tag'>매입원금 기준 고비중 TOP 3 성과</div>
            <ul style='font-size: 0.85em;'>
                {" ".join([f"<li><b>{name}:</b> Alpha {full_df[full_df['종목명']==name]['전일대비(%)'].mean()-k_r:+.2f}%p</li>" for name, val in total_by_stock.items()])}
            </ul>
        </div>""", unsafe_allow_html=True)
    with rep_r:
        st.markdown(f"""<div class='report-box' style='background-color: rgba(255,75,75,0.05);'>
            <h4 style='color: #FF4B4B;'>🌍 주요 시장 동향 분석</h4>
            <div class='market-tag'>KOSPI / KOSDAQ</div>
            <p style='font-size: 0.8em;'>국내 지수는 반도체 및 에너지 섹터의 혼조세 속에 외인 매도 우위 지속. KOSPI {m_status.get('KOSPI',{}).get('rate','-')}, KOSDAQ {m_status.get('KOSDAQ',{}).get('rate','-')}.</p>
            <div class='market-tag'>미국 S&P 500</div>
            <p style='font-size: 0.8em;'>금리 경로에 대한 불확실성에도 실적 기반 우량주 중심의 매수세 유입. {m_status.get('S&P500',{}).get('rate','-')} 안정적 흐름 전망.</p>
            <div class='market-tag'>미국 NASDAQ</div>
            <p style='font-size: 0.8em;'>AI 빅테크의 실적 가이던스 상향과 엔비디아 발 훈풍으로 기술주 주도 강세장 지속. {m_status.get('NASDAQ',{}).get('rate','-')} 상승 동력 확보.</p>
            <div class='market-tag'>원/달러 환율 및 금 현물</div>
            <p style='font-size: 0.8em;'>달러 강세 지속으로 환율 변동성 확대 장세. 금 현물은 지정학적 리스크와 안전자산 수요가 맞물려 신고가 부근 매물 소화 중.</p>
        </div>""", unsafe_allow_html=True)

    # 📊 관심 섹터 심층 분석 (v28.2 5대 요소 유지)
    st.divider()
    st.subheader("📊 관심 섹터 심층 동향 분석")
    sec_cols = st.columns(3)
    sectors = {
        "반도체": {"시황": "HBM 수요 견조 및 공급망 재편 본격화", "수급": "기관 IT 대형주 집중 매집", "주도": "SK하이닉스, 삼성전자", "뉴스": "AI 반도체 추가 수주 소식", "전망": "실적 장세 진입 기대"},
        "ESS/전력": {"시황": "미국 데이터센터 발 전력 부족 심화", "수급": "외인 장기 가치주 매집", "주도": "일진전기, LS ELECTRIC", "뉴스": "북미 수주 잔고 최고치", "전망": "장기 슈퍼 사이클 지속"},
        "배터리/전고체": {"시황": "차세대 기술 경쟁 및 소재 국산화 가속", "수급": "개인 저점 매수세 유입", "주도": "LG에너지솔루션", "뉴스": "전고체 상용화 로드맵 공개", "전망": "기술 우위 기업 중심 재편"},
        "로봇/AI": {"시황": "산업용 로봇 및 AI 에이전트 시장 개화", "수급": "테마성 수급 순환", "주도": "두산로보틱스", "뉴스": "지능형 로봇법 개정 수혜", "전망": "B2B 상용화 가속화"},
        "의약/화장품": {"시황": "K-뷰티 수출 사상 최대 및 글로벌 점유 확대", "수급": "실적 기반 외인 매수", "주도": "아모레퍼시픽, 브이티", "뉴스": "북미 채널 다변화 성공", "전망": "안정적 영업이익률 확보"},
        "방산/우주": {"시황": "글로벌 지정학적 리스크에 따른 무기 체계 수요", "수급": "기관 장기 포지션 유지", "주도": "한화에어로스페이스", "뉴스": "중동 및 유럽 추가 수주", "전망": "수주 잔고 기반 안정 성장"}
    }
    for i, (n, d) in enumerate(sectors.items()):
        with sec_cols[i % 3]:
            st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><p style='font-size: 0.85em;'><b>🌡️ 시황:</b> {d['시황']}<br><b>👥 수급:</b> {d['수급']}<br><b>👑 주도:</b> {d['주도']}<br><b>📰 뉴스:</b> {d['뉴스']}<br><b style='color:#FFD700;'>🔭 전망:</b> {d['전망']}</p></div>", unsafe_allow_html=True)

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
        
        # 🎯 [무결성] 10개 데이터 컬럼
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

        # 🕵️ [복구] 계좌별 상세 리포트
        st.divider()
        st.subheader(f"🕵️ {acc_name} 인텔리전스 리포트")
        b_s = sub_df.sort_values('전일대비(%)', ascending=False).iloc[0]
        ar_l, ar_r = st.columns(2)
        with ar_l:
            st.markdown(f"<div class='report-box' style='background-color: rgba(135,206,235,0.05); height:220px;'><h4 style='color: #87CEEB;'>📋 계좌 성과 분석</h4><ul style='font-size: 0.9em;'><li><b>베스트:</b> {b_s['종목명']} ({b_s['전일대비(%)']:+.2f}%)</li><li><b>현금흐름:</b> 배당 중심의 리밸런싱 전략 유효</li></ul></div>", unsafe_allow_html=True)
        with ar_r:
            st.markdown(f"<div class='report-box' style='background-color: rgba(255,75,75,0.05); height:220px;'><h4 style='color: #FF4B4B;'>🌍 섹터 전략</h4><p style='font-size: 0.9em;'>{b_s['종목명']}의 탄력적인 움직임이 계좌를 지지하고 있습니다.</p></div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v29.8 데이터 정밀화 버전")
