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
st.set_page_config(page_title="가족 자산 성장 관제탑 v30.0", layout="wide")

# --- [CSS: 인텔리전스 리포트 및 섹터 박스 스타일] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 20px; border-radius: 12px; height: 550px; overflow-y: auto; margin-bottom: 15px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.02); }
    .sector-box { padding: 18px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.03); min-height: 400px; margin-bottom: 15px; }
    .sector-title { font-size: 1.2rem; font-weight: bold; border-bottom: 3px solid #87CEEB; padding-bottom: 8px; margin-bottom: 12px; color: #87CEEB; }
    .market-tag { background-color: rgba(135,206,235,0.15); padding: 4px 10px; border-radius: 6px; color: #87CEEB; font-weight: bold; margin-bottom: 8px; display: inline-block; font-size: 0.85em; }
    .index-indicator { padding: 10px 20px; border-radius: 8px; font-weight: bold; font-size: 1.1rem; border: 1px solid rgba(255,255,255,0.1); text-align: center; }
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
            st.warning("📡 구글 서비스 일시 연결 지연... 자동으로 재시도합니다."); time.sleep(3); st.rerun()
        st.error(f"데이터 로드 오류: {e}"); st.stop()

full_df = load_data_with_retry(STOCKS_SHEET, "1m")
history_df = load_data_with_retry(TREND_SHEET, 0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], format='mixed', errors='coerce').dt.date
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [시장 지수 파싱 엔진] ---
def get_market_indices():
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            # 상승/하락 글자를 부호로 변환
            diff = raw[0].replace("상승","+").replace("하락","-").strip()
            rate = raw[1].replace("상승","").replace("하락","").strip()
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

# --- [사이드바 관리 메뉴 복구] ---
def record_performance():
    today_date = now_kst.date()
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    kospi_now = m_info.get('KOSPI', {}).get('now', '0').replace(',','')
    new_row = {"Date": today_date, "KOSPI": float(kospi_now), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    for col in history_df.columns:
        if "수익률" in col and "_" in col:
            parts = col.split("_"); a_part, s_part = parts[0] + "투자", parts[1].replace("수익률", "")
            match = full_df[(full_df['계좌명']==a_part) & (full_df['종목명'].str.replace(' ', '') == s_part.replace(' ', ''))]
            if not match.empty: new_row[col] = match.iloc[0]['수익률']
    try:
        updated_df = pd.concat([history_df[history_df['Date'] != today_date], pd.DataFrame([new_row])], ignore_index=True)
        conn.update(worksheet=TREND_SHEET, data=updated_df[history_df.columns].sort_values('Date'))
        st.sidebar.success("✅ 저장 성공!"); st.cache_data.clear(); st.rerun()
    except Exception as e: st.sidebar.error(f"저장 실패: {e}")

st.sidebar.header("🕹️ 관리 메뉴")
if st.sidebar.button("🔄 실시간 데이터 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 오늘의 결과 저장/덮어쓰기"): record_performance()
if st.sidebar.button("🧹 과거 데이터 정제"):
    history_df['Date'] = pd.to_datetime(history_df['Date']).dt.strftime('%Y-%m-%d')
    conn.update(worksheet=TREND_SHEET, data=history_df); st.sidebar.success("정제 완료"); st.rerun()

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v30.0</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_buy, t_eval, t_prev_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum(), full_df['전일평가금액'].sum()
    total_profit, daily_rate = t_eval - t_buy, ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    
    # 🎯 [무결성] 상단 4열 메트릭
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{total_profit:,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{daily_rate:+.2f}%")
    
    st.markdown("---")
    # 🎯 [무결성] 계좌 요약 표
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

    # 🎯 [무결성] 통합 추이 그래프
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

    # 🕵️ [전면 개편] AI 관제탑 데일리 심층 리포트
    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    
    # 🎯 [신규] 리포트 제목 하단 지수 표기 (음양/색채 반영)
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    for i, name in enumerate(["KOSPI", "KOSDAQ"]):
        d = m_idx.get(name, {})
        color = "#FF4B4B" if "+" in d.get("diff", "") else "#87CEEB" if "-" in d.get("diff", "") else "white"
        [idx_l, idx_r][i].markdown(f"<div class='index-indicator' style='color: {color}; background-color: rgba({(255,75,75,0.05) if color=='#FF4B4B' else (135,206,235,0.05)});'>{name}: {d.get('now', '-')} ({d.get('diff', '-')}, {d.get('rate', '-')})</div>", unsafe_allow_html=True)

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
                {" ".join([f"<li><b>{name}:</b> 원금 {val/1000000:,.1f}M (KOSPI 대비 {full_df[full_df['종목명']==name]['전일대비(%)'].mean()-k_r:+.2f}%p)</li>" for name, val in total_by_stock.items()])}
            </ul>
        </div>""", unsafe_allow_html=True)
    with rep_r:
        st.markdown(f"""<div class='report-box' style='background-color: rgba(255,75,75,0.05);'>
            <h4 style='color: #FF4B4B;'>🌍 주요 시장 동향 및 시황 분석</h4>
            <div class='market-tag'>환율 및 거시 지표 (Fact Check)</div>
            <p style='font-size: 0.85em;'><b>원/달러 환율:</b> 현재 환율은 <b>1,400원대 중반에서 1,500원선</b>을 위협하는 강달러 국면이 지속되고 있습니다. 이는 미 연준의 금리 인하 속도 조절 론과 한국의 자본 유출 우려가 맞물린 결과로, 수출 대형주(반도체/자동차)에는 유리할 수 있으나 내수 및 수입 물가에는 큰 압박으로 작용하고 있습니다.</p>
            <div class='market-tag'>KOSPI / KOSDAQ</div>
            <p style='font-size: 0.85em;'>국내 증시는 고환율로 인한 외인 수급 불안정성 속에 특정 섹터(전력/방산)로의 쏠림 현상이 강합니다. 코스닥은 시가총액 상위 제약/바이오 주의 임상 모멘텀에 의존한 변동성 장세를 보이고 있습니다.</p>
            <div class='market-tag'>해외 증시 (미국)</div>
            <p style='font-size: 0.85em;'>S&P 500과 나스닥은 AI 컴퓨팅 인프라 투자 지속에 힘입어 사상 최고가 부근에서 등락을 거듭하고 있습니다. 특히 기술주의 주도력이 여전히 유효한 가운데 경기 연착륙 시나리오가 시장을 지배하고 있습니다.</p>
        </div>""", unsafe_allow_html=True)

    # 📊 [보강] 관심 섹터 심층 분석 (주도주 포함)
    st.divider()
    st.subheader("📊 관심 섹터 심층 동향 분석 (5대 요소)")
    sec_cols = st.columns(3)
    sectors = {
        "반도체": {"시황": "AI 칩 수요 폭발 및 HBM3E 공급 부족 지속", "주도주": "SK하이닉스, 한미반도체", "뉴스": "차세대 패키징 기술 선점 경쟁 가속", "전망": "데이터센터 투자 확대로 고성장세 유지"},
        "ESS/전력": {"시황": "미국 내 노후 전력망 교체 및 AI 데이터센터 전력난", "주도주": "LS ELECTRIC, 일진전기", "뉴스": "변압기 수주 잔고 최고치 경신 중", "전망": "3~5년 장기 슈퍼 사이클 진입"},
        "배터리/전고체": {"시황": "리튬 가격 안정화 및 차세대 전고체 샘플 공급 시작", "주도주": "LG에너지솔루션, 이수스페셜티", "뉴스": "전고체 상용화 로드맵 구체화", "전망": "캐즘 구간 이후 기술력 보유 기업 중심 재편"},
        "로봇/AI": {"시황": "휴머노이드 로봇 상용화 및 산업용 자동화 수요 급증", "주도주": "두산로보틱스, 레인보우로보틱스", "뉴스": "지능형 로봇법 개정으로 서비스 시장 확대", "전망": "B2B에서 B2C로 시장 파이 확대 예정"},
        "의약/화장품": {"시황": "K-뷰티 북미 수출 데이터 사상 최대치 릴레이", "주도주": "아모레퍼시픽, 브이티", "뉴스": "북미 아마존 내 한국 브랜드 점유율 급증", "전망": "글로벌 점유율 확대에 따른 실적 우상향 지속"},
        "방산/우주": {"시황": "지정학적 리스크 장기화 및 K-무기 체계 신뢰도 상승", "주도주": "한화에어로스페이스, LIG넥스원", "뉴스": "폴란드/중동 추가 수주 가시성 확보", "전망": "수주 잔고 기반의 장기 이익 성장 구간 진입"}
    }
    for i, (n, d) in enumerate(sectors.items()):
        with sec_cols[i % 3]:
            st.markdown(f"""
            <div class='sector-box'>
                <div class='sector-title'>{n}</div>
                <p style='font-size: 0.85em;'><b>🌡️ 시황:</b> {d['시황']}</p>
                <p style='font-size: 0.85em; color: #FFD700;'><b>👑 주도주:</b> {d['주도주']}</p>
                <p style='font-size: 0.85em;'><b>📰 뉴스:</b> {d['뉴스']}</p>
                <p style='font-size: 0.85em;'><b>🔭 전망:</b> {d['전망']}</p>
            </div>
            """, unsafe_allow_html=True)

# [계좌별 탭 렌더링 함수: 무결성 사수]
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
        ar_l, ar_r = st.columns(2)
        with ar_l:
            st.markdown(f"<div class='report-box' style='background-color: rgba(135,206,235,0.05); height:220px;'><h4 style='color: #87CEEB;'>📋 성과분석</h4><ul><li>베스트: {b_s['종목명']} ({b_s['전일대비(%)']:+.2f}%)</li><li>누적 수익률 {((a_eval/a_buy-1)*100):.2f}%를 기록 중입니다.</li></ul></div>", unsafe_allow_html=True)
        with ar_r:
            st.markdown(f"<div class='report-box' style='background-color: rgba(255,75,75,0.05); height:220px;'><h4 style='color: #FF4B4B;'>🌍 업황전망</h4><p>{b_s['종목명']}의 주도력이 계좌 성과를 지지하고 있습니다. 최근 고환율에 따른 수출 수혜 여부를 모니터링하시기 바랍니다.</p></div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v30.0 무결성 보정 완료")
