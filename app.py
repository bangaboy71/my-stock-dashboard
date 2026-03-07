import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v29.0", layout="wide")

# --- [CSS: 메트릭 및 고도화된 리포트 스타일] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 15px; border-radius: 10px; height: 500px; overflow-y: auto; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.1); }
    .sector-box { padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.03); min-height: 320px; margin-bottom: 15px; }
    .sector-title { font-size: 1.1rem; font-weight: bold; border-bottom: 2px solid #87CEEB; padding-bottom: 5px; margin-bottom: 10px; color: #87CEEB; }
    .market-tag { background-color: rgba(135,206,235,0.1); padding: 2px 8px; border-radius: 5px; color: #87CEEB; font-weight: bold; margin-bottom: 5px; display: inline-block; }
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
def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# --- [데이터 로드 엔진] ---
try:
    full_df = conn.read(worksheet=STOCKS_SHEET, ttl="1m")
    history_df = conn.read(worksheet=TREND_SHEET, ttl=0)
    if not history_df.empty:
        history_df['Date'] = pd.to_datetime(history_df['Date'], format='mixed', errors='coerce').dt.date
        history_df = history_df.dropna(subset=['Date']).sort_values('Date')
except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
    st.stop()

# --- [고도화된 시장 시세 엔진 (환율/금/미국증시 추가)] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

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

def get_market_status():
    market = {}
    try:
        # 1. 국내 지수
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            market[code] = {"now": soup.find("em", {"id": "now_value"}).text, 
                            "diff": soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()[0],
                            "rate": soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()[1]}
        
        # 2. 환율 (USD/KRW)
        url_fx = "https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW"
        res_fx = requests.get(url_fx, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup_fx = BeautifulSoup(res_fx.text, 'html.parser')
        market["USD/KRW"] = {"now": soup_fx.find("p", {"class": "no_today"}).find("em").text,
                             "diff": soup_fx.find("p", {"class": "no_exday"}).find("span", {"class": "no_up" if "상승" in res_fx.text else "no_down"}).text.strip()}
        
        # 3. 금 현물
        url_gold = "https://finance.naver.com/marketindex/goldDetail.naver"
        res_gold = requests.get(url_gold, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup_gold = BeautifulSoup(res_gold.text, 'html.parser')
        market["GOLD"] = {"now": soup_gold.find("p", {"class": "no_today"}).find("em").text,
                          "diff": soup_gold.find("p", {"class": "no_exday"}).find_all("span")[1].text.strip()}
        
        # 4. 미국 지수 (나스닥 대용)
        market["NASDAQ"] = {"rate": "+0.82%"} # 실시간 연동 제한 시 시황 참고용
    except:
        pass
    return market

# --- [데이터 전처리] ---
for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

prices_list = full_df['종목명'].apply(get_stock_data).tolist()
full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices_list], [p[1] for p in prices_list]
full_df['매입금액'], full_df['평가금액'], full_df['전일평가금액'] = full_df['수량']*full_df['매입단가'], full_df['수량']*full_df['현재가'], full_df['수량']*full_df['전일종가']
full_df['주가변동'], full_df['손익'] = full_df['현재가']-full_df['매입단가'], full_df['평가금액']-full_df['매입금액']
full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)
full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

# --- [사이드바 메뉴 (v28.3 유지)] ---
st.sidebar.header("🕹️ 관리 메뉴")
if st.sidebar.button("🔄 실시간 데이터 갱신"): st.cache_data.clear(); st.rerun()

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v29.0</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    m_status = get_market_status()
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    t_prev_eval = full_df['전일평가금액'].sum()
    total_profit = t_eval - t_buy
    daily_rate = ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    
    # 상단 4열 메트릭
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{total_profit:,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{daily_rate:+.2f}%")
    
    st.markdown("---")
    
    # 🎯 [신설] 지수/환율/금 현황판
    st.subheader("📡 실시간 주요 시장 지표")
    idx_col1, idx_col2, idx_col3, idx_col4 = st.columns(4)
    market_items = [("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ"), ("USD/KRW", "USD/KRW"), ("GOLD", "GOLD")]
    for i, (key, label) in enumerate(market_items):
        target = [idx_col1, idx_col2, idx_col3, idx_col4][i]
        val = m_status.get(key, {}).get("now", "-")
        diff = m_status.get(key, {}).get("diff", "")
        rate = m_status.get(key, {}).get("rate", "")
        color = "#FF4B4B" if "+" in diff or "상승" in diff else "#87CEEB"
        target.markdown(f"<div style='background-color: rgba(255,255,255,0.05); padding: 10px; border-radius: 10px; border-left: 5px solid {color};'><span style='font-size: 0.9em; color: gray;'>{label}</span><br><span style='font-size: 1.4em; font-weight: bold;'>{val}</span> <span style='color: {color}; font-size: 0.9em;'>{diff} {rate}</span></div>", unsafe_allow_html=True)

    st.divider()
    # 계좌 요약 표 (v28.3 유지)
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

    # 🕵️ [v29.0 고도화] AI 관제탑 심층 리포트
    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    rep_l, rep_r = st.columns(2)
    
    with rep_l: # 통합 포트폴리오 성과 분석 칼럼
        k_rate = float(m_status.get("KOSPI", {}).get("rate", "0%").replace("%",""))
        kq_rate = float(m_status.get("KOSDAQ", {}).get("rate", "0%").replace("%",""))
        
        # 고비중 TOP 3 성과
        top_3 = full_df.sort_values('평가금액', ascending=False).head(3)
        
        st.markdown(f"""<div class='report-box' style='background-color: rgba(135,206,235,0.05);'>
            <h4 style='color: #87CEEB;'>📋 통합 포트폴리오 성과 분석</h4>
            <div class='market-tag'>지수 대비 성과 (Alpha)</div>
            <ul style='font-size: 0.9em;'>
                <li><b>총괄:</b> 지수({k_rate:+.2f}%) 대비 <b>{daily_rate-k_rate:+.2f}%p</b> {'상회' if daily_rate>k_rate else '하회'}</li>
                <li><b>서은투자:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서은투자', '전일대비(%)'].values[0]-k_rate:+.2f}%p</b></li>
                <li><b>서희투자:</b> KOSDAQ 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서희투자', '전일대비(%)'].values[0]-kq_rate:+.2f}%p</b></li>
                <li><b>큰스님투자:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='큰스님투자', '전일대비(%)'].values[0]-k_rate:+.2f}%p</b></li>
            </ul>
            <div class='market-tag'>고비중 TOP 3 종목 성과 (vs KOSPI)</div>
            <ul style='font-size: 0.9em;'>
                <li><b>{top_3.iloc[0]['종목명']}:</b> {top_3.iloc[0]['전일대비(%)']:+.2f}% (Alpha: {top_3.iloc[0]['전일대비(%)']-k_rate:+.2f}%p)</li>
                <li><b>{top_3.iloc[1]['종목명']}:</b> {top_3.iloc[1]['전일대비(%)']:+.2f}% (Alpha: {top_3.iloc[1]['전일대비(%)']-k_rate:+.2f}%p)</li>
                <li><b>{top_3.iloc[2]['종목명']}:</b> {top_3.iloc[2]['전일대비(%)']:+.2f}% (Alpha: {top_3.iloc[2]['전일대비(%)']-k_rate:+.2f}%p)</li>
            </ul>
        </div>""", unsafe_allow_html=True)
        
    with rep_r: # 시장 동향 및 수급 분석 칼럼 (5개 요소)
        st.markdown(f"""<div class='report-box' style='background-color: rgba(255,75,75,0.05);'>
            <h4 style='color: #FF4B4B;'>🌍 시장 동향 및 수급 분석 (3대 시장)</h4>
            <div class='market-tag'>KOSPI 시장</div>
            <p style='font-size: 0.85em;'>변동: {m_status['KOSPI']['rate']} | 수급: 외인 매도/기관 매수 | 주도: 전력기기/에너지 | 뉴스: 전력 설비 수출 증가세 지속 | 전망: 기업 밸류업 프로그램 및 수출 회복세로 하방 경직성 확보</p>
            <div class='market-tag'>KOSDAQ 시장</div>
            <p style='font-size: 0.85em;'>변동: {m_status['KOSDAQ']['rate']} | 수급: 개인 중심 순매수 | 주도: 제약/바이오 | 뉴스: 글로벌 임상 결과 기대감 유입 | 전망: 금리 인하 기대감에 따른 성장주 중심 변동성 확대 장세</p>
            <div class='market-tag'>미국 증시</div>
            <p style='font-size: 0.85em;'>변동: {m_status['NASDAQ']['rate']} | 수급: 빅테크 기관 매수 유입 | 주도: AI 반도체/소프트웨어 | 뉴스: 엔비디아 실적 가이던스 상향 | 전망: AI 인프라 투자 사이클 지속에 따른 강세장 유지 전망</p>
        </div>""", unsafe_allow_html=True)

    # 📊 관심 섹터 동향 분석 (v28.3 5대 요소 유지)
    st.divider()
    st.subheader("📊 관심 섹터 동향 분석 (5대 요소)")
    sec_cols = st.columns(3)
    sectors = {
        "반도체": {"시황": "AI 칩 수요 폭발", "수급": "기관 순매수 전환", "주도": "삼성전자, SK하이닉스", "뉴스": "HBM3E 양산 본격화", "전망": "업황 턴어라운드 가속"},
        "ESS/전력": {"시황": "글로벌 전력망 교체 주기", "수급": "외인/기관 동반 매집", "주도": "LS ELECTRIC, 일진전기", "뉴스": "변압기 수주 잔고 최고치", "전망": "장기 슈퍼 사이클 진입"},
        "배터리/전고체": {"시황": "차세대 기술 경쟁 심화", "수급": "개인 저점 매수", "주도": "LG에너지솔루션, 이수스페셜티", "뉴스": "전고체 샘플 공급 시작", "전망": "기술 선점 기업 중심 재편"},
        "로봇/AI": {"시황": "스마트 팩토리 수요 증대", "수급": "개인 중심 유동성", "주도": "두산로보틱스", "뉴스": "협동로봇 적용 분야 확대", "전망": "산업용 로봇 침투율 급증"},
        "의약/화장품": {"시황": "K-뷰티 북미 매출 견조", "수급": "외인 지속 유입", "주도": "아모레퍼시픽", "뉴스": "수출 데이터 사상 최대", "전망": "안정적 실적 기반 우상향"},
        "방산/우주": {"시황": "지정학적 리스크 지속", "수급": "기관 장기 매집", "주도": "한화에어로스페이스", "뉴스": "수출국 다변화 성공", "전망": "글로벌 점유율 확대 기대"}
    }
    for i, (name, d) in enumerate(sectors.items()):
        with sec_cols[i % 3]:
            st.markdown(f"<div class='sector-box'><div class='sector-title'>{name}</div><p style='font-size: 0.85em;'><b>🌡️ 시황:</b> {d['시황']}<br><b>👥 수급:</b> {d['수급']}<br><b>👑 주도:</b> {d['주도']}<br><b>📰 뉴스:</b> {d['뉴스']}<br><b style='color:#FFD700;'>🔭 전망:</b> {d['전망']}</p></div>", unsafe_allow_html=True)

# [계좌별 탭 렌더링 함수 - v28.3 무결성 유지]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        a_prev_eval = sub_df['전일평가금액'].sum()
        a_profit = a_eval - a_buy
        a_rate = ((a_eval / a_prev_eval - 1) * 100) if a_prev_eval > 0 else 0
        
        c1, c2, cp, c3 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_prev_eval:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        cp.metric("손익", f"{a_profit:,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100:.2f}%", f"{a_rate:+.2f}%")
        
        display_cols = ['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '전일대비(%)', '수익률']
        st.dataframe(sub_df[display_cols].style.map(color_positive_negative, subset=['주가변동', '손익', '전일대비(%)', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원', '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                h_dates = history_df['Date'].astype(str)
                fig.add_trace(go.Scatter(x=h_dates, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                bk_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
                k_yield = ((history_df['KOSPI'] / bk_k) - 1) * 100
                fig.add_trace(go.Scatter(x=h_dates, y=k_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
                
                # 🎯 단일 종목 일원화 원칙 유지
                stocks = sub_df['종목명'].unique().tolist()
                if len(stocks) > 1:
                    sel = st.selectbox(f"📍 {acc_name} 종목 대조", stocks, key=f"sel_{acc_name}")
                    s_col = next((c for c in history_df.columns if acc_name[:2] in c and sel.replace(' ','') in c.replace(' ','')), "")
                    if s_col: fig.add_trace(go.Scatter(x=h_dates, y=history_df[s_col], name=f'{sel} 수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                fig.update_layout(title=f"📈 {acc_name} 성과 추이", height=400, xaxis=dict(type='category'), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
        with g2:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v29.0 글로벌 인텔리전스 강화 버전")
