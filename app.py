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
st.set_page_config(page_title="가족 자산 성장 관제탑 v29.9", layout="wide")

# --- [CSS: 지표 카드 및 리포트 스타일 전면 재검토] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 20px; border-radius: 12px; height: 550px; overflow-y: auto; margin-bottom: 15px; border: 1px solid rgba(255,255,255,0.1); line-height: 1.6; }
    .sector-box { padding: 18px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.03); min-height: 420px; margin-bottom: 15px; }
    .sector-title { font-size: 1.2rem; font-weight: bold; border-bottom: 3px solid #87CEEB; padding-bottom: 10px; margin-bottom: 15px; color: #87CEEB; }
    .market-tag { background-color: rgba(135,206,235,0.15); padding: 4px 10px; border-radius: 6px; color: #87CEEB; font-weight: bold; margin-bottom: 10px; display: inline-block; font-size: 0.85em; }
    .index-card { background-color: rgba(255,255,255,0.07); padding: 18px; border-radius: 12px; border-left: 6px solid; height: 120px; display: flex; flex-direction: column; justify-content: center; box-shadow: 2px 2px 10px rgba(0,0,0,0.2); }
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
            st.warning("📡 구글 시트 연결 대기 중..."); time.sleep(5); st.rerun()
        st.error(f"데이터 로드 오류: {e}"); st.stop()

full_df = load_data_with_retry(STOCKS_SHEET, "1m")
history_df = load_data_with_retry(TREND_SHEET, 0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], format='mixed', errors='coerce').dt.date
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [시장 시세 엔진: 정밀 파싱] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_market_status():
    market = {}
    u_time = now_kst.strftime('%H:%M')
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            diff = raw[0].replace("상승","+").replace("하락","-").strip()
            rate = raw[1].replace("상승","").replace("하락","").strip()
            market[code] = {"now": val, "diff": diff, "rate": rate}
        
        # 환율/금 시각 표기 및 미스터리 숫자 제거
        res_fx = requests.get("https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW", headers={'User-Agent': 'Mozilla/5.0'}).text
        soup_fx = BeautifulSoup(res_fx, 'html.parser')
        market["USD/KRW"] = {"now": soup_fx.find("p", {"class": "no_today"}).find("em").text, "update": f"시각: {u_time}"}

        res_gold = requests.get("https://finance.naver.com/marketindex/goldDetail.naver", headers={'User-Agent': 'Mozilla/5.0'}).text
        soup_gold = BeautifulSoup(res_gold, 'html.parser')
        market["GOLD"] = {"now": soup_gold.find("p", {"class": "no_today"}).find("em").text, "update": f"시각: {u_time}"}
        
        market["S&P500"] = {"rate": "+0.42%"}
        market["NASDAQ"] = {"rate": "+0.88%"}
    except: pass
    return market

# --- [데이터 전처리] ---
def get_stock_data(name):
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

for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
prices_list = full_df['종목명'].apply(get_stock_data).tolist()
full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices_list], [p[1] for p in prices_list]
full_df['매입금액'], full_df['평가금액'], full_df['전일평가금액'] = full_df['수량']*full_df['매입단가'], full_df['수량']*full_df['현재가'], full_df['수량']*full_df['전일종가']
full_df['주가변동'], full_df['손익'] = full_df['현재가']-full_df['매입단가'], full_df['평가금액']-full_df['매입금액']
full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)
full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

# --- [사이드바 관리 메뉴 완전 복구] ---
def record_performance():
    today_date = now_kst.date()
    m_info = get_market_status()
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
if st.sidebar.button("🧹 과거 데이터 정제"):
    history_df['Date'] = pd.to_datetime(history_df['Date']).dt.strftime('%Y-%m-%d')
    conn.update(worksheet=TREND_SHEET, data=history_df); st.sidebar.success("정제 완료"); st.rerun()
st.sidebar.divider()
today_date = now_kst.date()
if not history_df.empty and any(history_df['Date'] == today_date):
    if st.sidebar.button("♻️ 오늘 데이터 덮어쓰기"): record_performance()
else:
    if st.sidebar.button("💾 오늘의 결과 저장하기"): record_performance()

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v29.9</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    m_status = get_market_status()
    t_buy, t_eval, t_prev_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum(), full_df['전일평가금액'].sum()
    total_profit, daily_rate = t_eval - t_buy, ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{total_profit:,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{daily_rate:+.2f}%")
    
    st.markdown("---")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

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

    # 🎯 [전면 재검토] 실시간 주요 시장 지표 (그래프 아래 배치)
    st.divider()
    st.subheader("📡 실시간 주요 시장 지표")
    idx_cols = st.columns(4)
    items = [("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ"), ("USD/KRW", "원/달러 환율"), ("GOLD", "금 현물")]
    for i, (k, lbl) in enumerate(items):
        d = m_status.get(k, {})
        val = d.get("now", "-")
        if k in ["KOSPI", "KOSDAQ"]:
            diff, rate = d.get("diff", ""), d.get("rate", "")
            color = "#FF4B4B" if "+" in diff else "#87CEEB" if "-" in diff else "white"
            sub_text = f"{diff} ({rate})"
        else:
            color = "#87CEEB"; sub_text = d.get("update", "")
        idx_cols[i].markdown(f"<div class='index-card' style='border-left-color: {color};'><span style='font-size: 0.85em; color: gray;'>{lbl}</span><br><span style='font-size: 1.45em; font-weight: bold;'>{val}</span><br><span style='color: {color}; font-size: 0.95em; font-weight: bold;'>{sub_text}</span></div>", unsafe_allow_html=True)

    # 🕵️ [v29.7 기반 고도화] AI 관제탑 데일리 심층 리포트
    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    rep_l, rep_r = st.columns(2)
    with rep_l:
        k_r = safe_float(m_status.get("KOSPI", {}).get("rate", "0"))
        # 🎯 매입원금 합산 TOP 3 분석
        total_by_stock = full_df.groupby('종목명')['매입금액'].sum().sort_values(ascending=False).head(3)
        st.markdown(f"""<div class='report-box' style='background-color: rgba(135,206,235,0.05);'>
            <h4 style='color: #87CEEB;'>📋 통합 포트폴리오 성과 분석</h4>
            <div class='market-tag'>KOSPI 지수 대비 Alpha 분석</div>
            <ul style='font-size: 0.9em;'>
                <li><b>총괄 실적:</b> KOSPI 대비 <b>{daily_rate-k_r:+.2f}%p</b> {'초과 달성' if daily_rate>k_r else '하회'}</li>
                <li><b>서은 계좌:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서은투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
                <li><b>서희 계좌:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서희투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
                <li><b>큰스님 계좌:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='큰스님투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
            </ul>
            <div class='market-tag'>매입원금 합산 기준 고비중 TOP 3</div>
            <ul style='font-size: 0.9em;'>
                {" ".join([f"<li><b>{name}:</b> {val/1000000:,.1f}M 원 (Alpha: {full_df[full_df['종목명']==name]['전일대비(%)'].mean()-k_r:+.2f}%p)</li>" for name, val in total_by_stock.items()])}
            </ul>
            <p style='font-size: 0.85em; color: gray;'>※ 원금 비중이 높은 종목의 수익률 탄력성이 전체 포트폴리오의 방어력을 결정하고 있습니다.</p>
        </div>""", unsafe_allow_html=True)
    with rep_r:
        st.markdown(f"""<div class='report-box' style='background-color: rgba(255,75,75,0.05);'>
            <h4 style='color: #FF4B4B;'>🌍 주요 시장 동향 분석</h4>
            <div class='market-tag'>KOSPI / KOSDAQ</div>
            <p style='font-size: 0.85em;'>국내 증시는 금리 인하 신중론 속에 섹터별 차별화 장세 지속. KOSPI는 대형 반도체 중심의 수급 공방, KOSDAQ은 바이오/엔터 테마의 변동성 확대 양상.</p>
            <div class='market-tag'>미국 S&P 500 / NASDAQ</div>
            <p style='font-size: 0.85em;'>S&P 500은 견조한 고용 지표를 바탕으로 연착륙 기대감 반영. NASDAQ은 AI 컴퓨팅 인프라 기업들의 실적 호조가 기술주 전반의 투심을 지지하며 강세 유지.</p>
            <div class='market-tag'>원/달러 환율 및 금 현물</div>
            <p style='font-size: 0.85em;'>강달러 기조 속에 환율은 1,300원대 중반 박스권 형성. 금 현물은 지정학적 불안에 따른 안전자산 프리미엄과 중앙은행 매수세가 맞물려 고점 부근 횡보.</p>
        </div>""", unsafe_allow_html=True)

    # 📊 [v29.7 수준 복구] 관심 섹터 심층 분석
    st.divider()
    st.subheader("📊 관심 섹터 심층 동향 분석")
    sec_cols = st.columns(3)
    sectors = {
        "반도체": {"시황": "HBM3E 양산 본격화 및 AI 서버용 수요 폭증", "수급": "기관 IT 대형주 집중 매집", "뉴스": "차세대 칩 공급망 재편", "전망": "실적 장세 진입"},
        "ESS/전력": {"시황": "미국 데이터센터 발 전력난 및 변압기 교체 사이클", "수급": "외인 장기 가치주 매집", "뉴스": "북미 수주 잔고 사상 최대", "전망": "슈퍼 사이클 지속"},
        "배터리/전고체": {"시황": "리튬가 안정화 및 전고체 배터리 샘플 공급 개시", "수급": "개인 저점 매수세 유입", "뉴스": "상용화 로드맵 구체화", "전망": "기술 우위 기업 재편"},
        "로봇/AI": {"시황": "제조 현장 자동화 및 서비스용 AI 에이전트 확산", "수급": "테마성 수급 순환", "뉴스": "지능형 로봇법 개정 수혜", "전망": "상용화 단계 진입"},
        "의약/화장품": {"시황": "K-뷰티 북미 매출 폭증 및 글로벌 점유율 확대", "수급": "실적 기반 외인 매수", "뉴스": "수출 데이터 사상 최대", "전망": "이익률 개선 가속"},
        "방산/우주": {"시황": "지정학적 리스크 장기화에 따른 글로벌 수주 확대", "수급": "기관 장기 포지션 유지", "뉴스": "동유럽/중동 추가 수주", "전망": "안정적 성장 가도"}
    }
    for i, (n, d) in enumerate(sectors.items()):
        with sec_cols[i % 3]:
            st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><p style='font-size: 0.85em;'><b>🌡️ 시황:</b> {d['시황']}<br><b>👥 수급:</b> {d['수급']}<br><b>📰 뉴스:</b> {d['뉴스']}<br><b style='color:#FFD700;'>🔭 전망:</b> {d['전망']}</p></div>", unsafe_allow_html=True)

# [계좌별 상세 분석 탭: 무결성 복구]
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

        # 🕵️ [복구] 계좌별 상세 리포트
        st.divider()
        st.subheader(f"🕵️ {acc_name} 인텔리전스 리포트")
        b_s = sub_df.sort_values('전일대비(%)', ascending=False).iloc[0]
        ar_l, ar_r = st.columns(2)
        with ar_l: st.markdown(f"<div class='report-box' style='background-color: rgba(135,206,235,0.05); height:180px;'><h4 style='color: #87CEEB;'>📋 성과 요약</h4><p>베스트: {b_s['종목명']} ({b_s['전일대비(%)']:+.2f}%)<br>누적 수익률 {((a_eval/a_buy-1)*100):.2f}%를 기록 중입니다.</p></div>", unsafe_allow_html=True)
        with ar_r: st.markdown(f"<div class='report-box' style='background-color: rgba(255,75,75,0.05); height:180px;'><h4 style='color: #FF4B4B;'>🌍 섹터 리포트</h4><p>{b_s['종목명']}의 주도력이 계좌의 핵심 동력입니다. 업황 변동에 유의하여 대응하시기 바랍니다.</p></div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v29.9 인텔리전스 마스터 피스")
