import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v27.7", layout="wide")

# --- [CSS: 메트릭 폰트 크기 및 가독성 조정] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
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

# --- [시장 시세 엔진] ---
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
            now_val = soup.find("em", {"id": "now_value"}).text
            change_area = soup.find("span", {"id": "change_value_and_rate"})
            raw = change_area.text.strip().split()
            diff, rate = raw[0].replace("상승","").replace("하락","").strip(), raw[1].replace("상승","").replace("하락","").strip()
            market[code] = {"now": now_val, "diff": diff, "rate": rate}
    except:
        market["KOSPI"] = {"now": "0", "diff": "0", "rate": "0.00%"}
        market["KOSDAQ"] = {"now": "0", "diff": "0", "rate": "0.00%"}
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

# --- [성과 기록 및 정제 함수] ---
def sanitize_and_update_history():
    try:
        sanitized_df = history_df.copy()
        sanitized_df['Date'] = pd.to_datetime(sanitized_df['Date']).dt.strftime('%Y-%m-%d')
        conn.update(worksheet=TREND_SHEET, data=sanitized_df)
        st.sidebar.success("✨ 날짜 정제 완료!"); st.cache_data.clear(); st.rerun()
    except Exception as e: st.sidebar.error(f"정제 실패: {e}")

def record_performance():
    today_date = now_kst.date()
    m_info = get_market_status()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    def get_stock_yield(acc, stock):
        row = full_df[(full_df['계좌명']==acc) & (full_df['종목명'].str.replace(' ', '') == stock.replace(' ', ''))]
        return row.iloc[0]['수익률'] if not row.empty else None
    kospi_now = m_info.get('KOSPI', {}).get('now', '0').replace(',','')
    new_row = {"Date": today_date, "KOSPI": float(kospi_now), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    for col in history_df.columns:
        if "수익률" in col and "_" in col:
            parts = col.split("_"); acc_part, stock_part = parts[0] + "투자", parts[1].replace("수익률", "")
            y = get_stock_yield(acc_part, stock_part)
            if y is not None: new_row[col] = y
    try:
        updated_df = pd.concat([history_df[history_df['Date'] != today_date], pd.DataFrame([new_row])], ignore_index=True)
        updated_df = updated_df[history_df.columns].sort_values('Date')
        conn.update(worksheet=TREND_SHEET, data=updated_df)
        st.sidebar.success("✅ 저장 성공!"); st.cache_data.clear(); st.rerun()
    except Exception as e: st.sidebar.error(f"저장 실패: {e}")

# --- [복구 완료: 사이드바 메뉴] ---
st.sidebar.header("🕹️ 관리 메뉴")
if st.sidebar.button("🔄 실시간 데이터 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("🧹 과거 데이터 정제하기"): sanitize_and_update_history()
st.sidebar.divider()
today_date = now_kst.date()
today_exists = any(history_df['Date'] == today_date) if not history_df.empty else False
if today_exists:
    if st.sidebar.button("♻️ 오늘 데이터 덮어쓰기"): record_performance()
else:
    if st.sidebar.button("💾 오늘의 결과 저장하기"): record_performance()

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v27.7</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    m_info = get_market_status()
    t_buy, t_eval, t_prev_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum(), full_df['전일평가금액'].sum()
    total_daily_rate = ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    total_profit = t_eval - t_buy
    
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{total_profit:,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{total_daily_rate:+.2f}%")
    
    st.markdown("---")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

    if not history_df.empty:
        st.divider()
        fig_t = go.Figure()
        history_dates = history_df['Date'].astype(str)
        bk_kospi = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        kospi_yield = ((history_df['KOSPI'] / bk_kospi) - 1) * 100
        fig_t.add_trace(go.Scatter(x=history_dates, y=kospi_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns:
                fig_t.add_trace(go.Scatter(x=history_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig_t.update_layout(title="📈 가족 자산 통합 수익률 추이", height=400, xaxis=dict(type='category'), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig_t, use_container_width=True)

    # 🕵️ AI 리포트 (v27.6 복구 로직)
    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 분석 리포트")
    idx_c1, idx_c2 = st.columns(2)
    for idx, col in zip(["KOSPI", "KOSDAQ"], [idx_c1, idx_c2]):
        val, diff, rate = m_info[idx]["now"], m_info[idx]["diff"], m_info[idx]["rate"]
        color = "#FF4B4B" if "+" in diff or float(rate.replace('%','')) > 0 else "#87CEEB"
        col.markdown(f"<div style='background-color: rgba(255,255,255,0.05); padding: 10px; border-radius: 10px; border-left: 5px solid {color};'><span style='font-size: 0.9em; color: gray;'>{idx} 지수</span><br><span style='font-size: 1.5em; font-weight: bold;'>{val}</span> <span style='color: {color};'> {diff} ({rate})</span></div>", unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    best_s = full_df.sort_values('전일대비(%)', ascending=False).iloc[0]
    worst_s = full_df.sort_values('전일대비(%)', ascending=True).iloc[0]
    
    rep_l, rep_r = st.columns(2)
    with rep_l:
        st.markdown(f"""<div style='background-color: rgba(135,206,235,0.05); padding: 15px; border-radius: 10px; height: 350px;'><h4 style='color: #87CEEB;'>📋 포트폴리오 성과 및 특이사항</h4><ul style='font-size: 0.95em;'><li><b>지수 대비 성과:</b> KOSPI 대비 <b>{total_daily_rate - float(m_info['KOSPI']['rate'].replace('%','')) :+.2f}%p</b> {'초과 수익' if total_daily_rate > float(m_info['KOSPI']['rate'].replace('%','')) else '하회'}</li><li><b>오늘의 특징:</b> {best_s['종목명']}({best_s['전일대비(%)']:+.2f}%)의 상승세가 전체 수익률을 방어하고 있습니다.</li></ul></div>""", unsafe_allow_html=True)
    with rep_r:
        st.markdown(f"""<div style='background-color: rgba(255,75,75,0.05); padding: 15px; border-radius: 10px; height: 350px;'><h4 style='color: #FF4B4B;'>🌍 시장 동향 리포트</h4><ul style='font-size: 0.95em;'><li><b>섹터 동향:</b> 지정학적 리스크 및 유가 변동성에 따른 에너지/방산 섹터의 주도력이 유지되고 있습니다.</li></ul></div>""", unsafe_allow_html=True)

# [계좌별 상세 분석 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        a_buy, a_eval, a_prev_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum(), sub_df['전일평가금액'].sum()
        a_daily_rate = ((a_eval / a_prev_eval - 1) * 100) if a_prev_eval > 0 else 0
        acc_profit = a_eval - a_buy
        
        c1, c2, c_profit, c3 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_prev_eval:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        c_profit.metric("손익", f"{acc_profit:,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100 if a_buy>0 else 0:.2f}%", f"{a_daily_rate:+.2f}%")
        
        display_cols = ['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '전일대비(%)', '수익률']
        st.dataframe(sub_df[display_cols].style.map(color_positive_negative, subset=['주가변동', '손익', '전일대비(%)', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원', '매입금액': '{:,.0f}원', 
            '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)
        
        st.divider()
        g_col1, g_col2 = st.columns([2, 1])
        with g_col1:
            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                h_dates = history_df['Date'].astype(str)
                fig.add_trace(go.Scatter(x=h_dates, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                bk_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
                k_yield = ((history_df['KOSPI'] / bk_k) - 1) * 100
                fig.add_trace(go.Scatter(x=h_dates, y=k_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
                fig.update_layout(title=f"📈 {acc_name} 성과 추이", height=400, xaxis=dict(type='category'), yaxis=dict(ticksuffix="%"), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
        with g_col2:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v27.7 사이드바 복구 및 UI 최종 보정")
