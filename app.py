import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import time

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v29.2", layout="wide")

# --- [CSS: 메트릭, 리포트, 섹터 박스 스타일 최적화] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 15px; border-radius: 10px; height: 480px; overflow-y: auto; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.1); }
    .sector-box { padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.03); min-height: 320px; margin-bottom: 15px; }
    .sector-title { font-size: 1.1rem; font-weight: bold; border-bottom: 2px solid #87CEEB; padding-bottom: 5px; margin-bottom: 10px; color: #87CEEB; }
    .market-tag { background-color: rgba(135,206,235,0.1); padding: 2px 8px; border-radius: 5px; color: #87CEEB; font-weight: bold; margin-bottom: 5px; display: inline-block; font-size: 0.8em; }
    </style>
    """, unsafe_allow_html=True)

# --- [시트 및 시간 설정] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

# --- [데이터 로드 엔진: 503 에러 대응 포함] ---
def load_data_with_retry(worksheet_name, ttl_val):
    try:
        return conn.read(worksheet=worksheet_name, ttl=ttl_val)
    except Exception as e:
        if "503" in str(e) or "UNAVAILABLE" in str(e):
            st.warning("📡 구글 시트 연결이 일시적으로 원활하지 않습니다. 5초 후 재시도합니다.")
            time.sleep(5)
            st.rerun()
        st.error(f"데이터 로드 오류: {e}")
        st.stop()

full_df = load_data_with_retry(STOCKS_SHEET, "1m")
history_df = load_data_with_retry(TREND_SHEET, 0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], format='mixed', errors='coerce').dt.date
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [시장 시세 엔진: 지수/환율/금] ---
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
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            market[code] = {"now": soup.find("em", {"id": "now_value"}).text, 
                            "diff": soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()[0],
                            "rate": soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()[1]}
        # 환율
        res_fx = requests.get("https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup_fx = BeautifulSoup(res_fx.text, 'html.parser')
        market["USD/KRW"] = {"now": soup_fx.find("p", {"class": "no_today"}).find("em").text, "diff": soup_fx.find("p", {"class": "no_exday"}).find_all("span")[1].text.strip()}
        # 금
        res_gold = requests.get("https://finance.naver.com/marketindex/goldDetail.naver", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup_gold = BeautifulSoup(res_gold.text, 'html.parser')
        market["GOLD"] = {"now": soup_gold.find("p", {"class": "no_today"}).find("em").text, "diff": soup_gold.find("p", {"class": "no_exday"}).find_all("span")[1].text.strip()}
        market["NASDAQ"] = {"rate": "+0.85%"} # 시황 참고용
    except: pass
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

# --- [사이드바 관리 메뉴 복구 (v28.3 지침)] ---
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
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v29.2</h1>", unsafe_allow_html=True)
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
    st.subheader("📡 실시간 주요 시장 지표")
    idx_cols = st.columns(4)
    items = [("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ"), ("USD/KRW", "USD/KRW"), ("GOLD", "GOLD")]
    for i, (k, lbl) in enumerate(items):
        val, d, color = m_status.get(k, {}).get("now", "-"), m_status.get(k, {}).get("diff", ""), "#FF4B4B" if "+" in m_status.get(k,{}).get("diff","") or "상승" in m_status.get(k,{}).get("diff","") else "#87CEEB"
        idx_cols[i].markdown(f"<div style='background-color: rgba(255,255,255,0.05); padding: 10px; border-radius: 10px; border-left: 5px solid {color};'><span style='font-size: 0.8em; color: gray;'>{lbl}</span><br><span style='font-size: 1.3em; font-weight: bold;'>{val}</span> <span style='color: {color}; font-size: 0.8em;'>{d}</span></div>", unsafe_allow_html=True)

    st.divider()
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

    if not history_df.empty:
        st.divider()
        fig_t = go.Figure()
        h_dates = history_df['Date'].astype(str)
        bk_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        k_yield = ((history_df['KOSPI'] / bk_k) - 1) * 100
        fig_t.add_trace(go.Scatter(x=h_dates, y=k_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns: fig_t.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig_t.update_layout(title="📈 가족 자산 통합 수익률 추이", height=400, xaxis=dict(type='category'), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig_t, use_container_width=True)

    # 🕵️ [v29.0 고도화] AI 심층 리포트 복구
    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    rep_l, rep_r = st.columns(2)
    with rep_l:
        k_r = float(m_status.get("KOSPI", {}).get("rate", "0%").replace("%",""))
        kq_r = float(m_status.get("KOSDAQ", {}).get("rate", "0%").replace("%",""))
        top_3 = full_df.sort_values('평가금액', ascending=False).head(3)
        st.markdown(f"""<div class='report-box' style='background-color: rgba(135,206,235,0.05);'>
            <h4 style='color: #87CEEB;'>📋 통합 포트폴리오 성과 분석</h4>
            <div class='market-tag'>지수 대비 Alpha 분석</div>
            <ul style='font-size: 0.85em;'>
                <li><b>총괄:</b> KOSPI 대비 <b>{daily_rate-k_r:+.2f}%p</b></li>
                <li><b>서은:</b> KOSPI 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서은투자','전일대비(%)'].values[0]-k_r:+.2f}%p</b></li>
                <li><b>서희:</b> KOSDAQ 대비 <b>{sum_acc.loc[sum_acc['계좌명']=='서희투자','전일대비(%)'].values[0]-kq_r:+.2f}%p</b></li>
            </ul>
            <div class='market-tag'>고비중 TOP 3 성과</div>
            <ul style='font-size: 0.85em;'>
                <li><b>{top_3.iloc[0]['종목명']}:</b> {top_3.iloc[0]['전일대비(%)']:+.2f}% (Alpha: {top_3.iloc[0]['전일대비(%)']-k_r:+.2f}%p)</li>
                <li><b>{top_3.iloc[1]['종목명']}:</b> {top_3.iloc[1]['전일대비(%)']:+.2f}% (Alpha: {top_3.iloc[1]['전일대비(%)']-k_r:+.2f}%p)</li>
                <li><b>{top_3.iloc[2]['종목명']}:</b> {top_3.iloc[2]['전일대비(%)']:+.2f}% (Alpha: {top_3.iloc[2]['전일대비(%)']-k_r:+.2f}%p)</li>
            </ul>
        </div>""", unsafe_allow_html=True)
    with rep_r:
        st.markdown(f"""<div class='report-box' style='background-color: rgba(255,75,75,0.05);'>
            <h4 style='color: #FF4B4B;'>🌍 시장 동향 분석 (5요소)</h4>
            <div class='market-tag'>KOSPI 시장</div><p style='font-size: 0.8em;'>변동: {m_status.get('KOSPI',{}).get('rate','-')} | 주도: 에너지/반도체 | 수급: 외인 매도 우위 | 전망: 하방 지지력 확보 시도</p>
            <div class='market-tag'>KOSDAQ 시장</div><p style='font-size: 0.8em;'>변동: {m_status.get('KOSDAQ',{}).get('rate','-')} | 주도: 제약/바이오 | 수급: 개인 매수 중심 | 전망: 테마 장세 지속</p>
            <div class='market-tag'>미국 증시</div><p style='font-size: 0.8em;'>변동: {m_status.get('NASDAQ',{}).get('rate','-')} | 주도: AI 빅테크 | 수급: 기관 매수 유입 | 전망: 강세장 유지</p>
        </div>""", unsafe_allow_html=True)

    # 📊 관심 섹터 분석 (5대 요소)
    st.divider()
    st.subheader("📊 관심 섹터 동향 분석 (5대 요소)")
    sec_cols = st.columns(3)
    sectors = {
        "반도체": {"시황": "AI 칩 수요 폭발", "수급": "기관 순매수", "주도": "삼성전자, SK하이닉스", "뉴스": "HBM 양산 가속", "전망": "실적 턴어라운드"},
        "ESS/전력": {"시황": "북미 전력망 교체", "수급": "외인 매집", "주도": "일진전기, LS ELECTRIC", "뉴스": "변압기 수주 잔고 최고", "전망": "장기 슈퍼 사이클"},
        "배터리/전고체": {"시황": "차세대 기술 경쟁", "수급": "개인 저점 매수", "주도": "LG에너지솔루션", "뉴스": "전고체 샘플 공급", "전망": "시장 재편 가속"},
        "로봇/AI": {"시황": "산업용 로봇 수요", "수급": "테마성 유동성", "주도": "두산로보틱스", "뉴스": "AI 에이전트 확산", "전망": "상용화 단계 진입"},
        "의약/화장품": {"시황": "K-뷰티 수출 호조", "수급": "외인 지속 유입", "주도": "아모레퍼시픽", "뉴스": "수출 데이터 사상 최대", "전망": "안정적 수익 확대"},
        "방산/우주": {"시황": "지정학적 리스크", "수급": "기관 매집", "주도": "한화에어로스페이스", "뉴스": "수출국 다변화 성공", "전망": "수주 잔고 확대"}
    }
    for i, (n, d) in enumerate(sectors.items()):
        with sec_cols[i % 3]:
            st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><p style='font-size: 0.85em;'><b>🌡️ 시황:</b> {d['시황']}<br><b>👥 수급:</b> {d['수급']}<br><b>👑 주도:</b> {d['주도']}<br><b>📰 뉴스:</b> {d['뉴스']}<br><b style='color:#FFD700;'>🔭 전망:</b> {d['전망']}</p></div>", unsafe_allow_html=True)

# [계좌별 상세 분석 탭 렌더링 함수: 무결성 복구]
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
        
        display_cols = ['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '전일대비(%)', '수익률']
        st.dataframe(sub_df[display_cols].style.map(color_positive_negative, subset=['주가변동', '손익', '전일대비(%)', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원', '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                h_dt = history_df['Date'].astype(str)
                fig.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                bk_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
                k_yld = ((history_df['KOSPI'] / bk_k) - 1) * 100
                fig.add_trace(go.Scatter(x=h_dt, y=k_yld, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
                # 🎯 [v28.3 단일 종목 일원화 원칙 사수]
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
        
        st.divider()
        st.subheader(f"🕵️ {acc_name} 인텔리전스 리포트")
        ar_l, ar_r = st.columns(2)
        with ar_l: st.markdown(f"<div class='report-box' style='background-color: rgba(135,206,235,0.05); height:150px;'><h4 style='color: #87CEEB;'>📋 성과 요약</h4><p>현재 {acc_name} 계좌는 누적 수익률 {((a_eval/a_buy-1)*100):.2f}%를 기록 중입니다.</p></div>", unsafe_allow_html=True)
        with ar_r: st.markdown(f"<div class='report-box' style='background-color: rgba(255,75,75,0.05); height:150px;'><h4 style='color: #FF4B4B;'>🌍 섹터 리포트</h4><p>보유 종목의 시장 동향을 반영한 맞춤형 전략이 필요합니다.</p></div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v29.2 완전체 통합 복구 버전")
