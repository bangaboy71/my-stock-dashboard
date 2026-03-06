import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v22.1", layout="wide")

# --- [시트 및 시간 설정] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

# --- [헬퍼 함수: 색상 지정] ---
def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# --- [데이터 로드 엔진] ---
try:
    # 종목 현황은 1분마다, 히스토리는 필요시 로드
    full_df = conn.read(worksheet=STOCKS_SHEET, ttl="1m")
    history_df = conn.read(worksheet=TREND_SHEET, ttl=0)
except Exception as e:
    st.error(f"데이터 로드 오류: 구글 시트 연결을 확인해주세요. ({e})")
    st.stop()

# --- [시장 지수 및 시세 엔진] ---
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", 
    "현대글로비스": "086280", "현대차2우B": "005387", 
    "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", 
    "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"
}

def get_stable_price(name):
    clean_name = str(name).strip().replace(" ", "")
    code = STOCK_CODES.get(clean_name)
    if not code: return 0
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        return int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
    except: return 0

def get_market_status():
    """지수 정밀 수집 (v20.8의 부호 및 텍스트 보정 로직)"""
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            now_val = soup.find("em", {"id": "now_value"}).text
            change_area = soup.find("span", {"id": "change_value_and_rate"})
            raw = change_area.text.strip().split()
            
            # 불필요한 '상승/하락' 텍스트 제거
            diff = raw[0].replace("상승","").replace("하락","").strip()
            rate = raw[1].replace("상승","").replace("하락","").strip()
            
            # 부호 판별 및 강제 부여
            if 'red02' in str(change_area) or '+' in diff:
                diff, rate = "+" + diff.replace("+", ""), "+" + rate.replace("+", "")
            elif 'nv01' in str(change_area) or '-' in diff:
                diff, rate = "-" + diff.replace("-", ""), "-" + rate.replace("-", "")
                
            market[code] = {"now": now_val, "diff": diff, "rate": rate}
    except: pass
    return market

# --- [🎯 수급 및 테마 엔진: 30분 캐시 적용] ---
@st.cache_data(ttl=1800)
def get_cached_market_radar():
    """인포스탁 스타일 테마와 순매수 상위 데이터를 30분마다 갱신"""
    radar = {"trades": {"외인매수": [], "기관매수": [], "외인매도": [], "기관매도": []}, "themes": []}
    fetch_time = get_now_kst().strftime('%H:%M:%S')
    
    headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15'}
    
    try:
        # 1. 테마 데이터
        t_res = requests.get("https://finance.naver.com/sise/theme.naver", headers=headers, timeout=5)
        t_soup = BeautifulSoup(t_res.text, 'html.parser')
        rows = t_soup.find_all("table", {"class": "type_1"})[0].find_all("tr")[2:12]
        for row in rows:
            cols = row.find_all("td")
            if len(cols) > 1:
                radar["themes"].append({"name": cols[0].text.strip(), "rate": cols[1].text.strip()})
        
        # 2. 수급 데이터 (순매수 상위)
        s_res = requests.get("https://finance.naver.com/sise/sise_deal_rank.naver", headers=headers, timeout=5)
        s_soup = BeautifulSoup(s_res.text, 'html.parser')
        tables = s_soup.find_all("table", {"class": "type_5"})
        keys = ["외인매수", "기관매수", "외인매도", "기관매도"]
        for i, table in enumerate(tables[:4]):
            radar["trades"][keys[i]] = [a.text for a in table.find_all("a", {"class": "tltle"})[:10]]
            
    except: pass
    return radar, fetch_time

# --- [성과 기록 함수] ---
def record_performance(overwrite=False):
    today_str = now_kst.strftime('%Y-%m-%d')
    m_info = get_market_status()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    kospi_now = m_info.get('KOSPI', {}).get('now', '0').replace(',','')
    new_row = {"Date": today_str, "KOSPI": float(kospi_now), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    try:
        updated_df = history_df[history_df['Date'].astype(str) != today_str].copy() if overwrite else history_df.copy()
        updated_df = pd.concat([updated_df, pd.DataFrame([new_row])], ignore_index=True)
        conn.update(worksheet=TREND_SHEET, data=updated_df)
        st.sidebar.success(f"✅ {today_str} 성과 저장 완료!")
        st.cache_data.clear(); st.rerun()
    except Exception as e: st.sidebar.error(f"❌ 기록 실패: {e}")

# 데이터 가공
for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
full_df['현재가'] = full_df['종목명'].apply(get_stable_price)
full_df['주가변동'] = full_df['현재가'] - full_df['매입단가']
full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
full_df['평가금액'] = full_df['수량'] * full_df['현재가']
full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
full_df['수익률'] = (full_df['손익'] / full_df['매입금액'] * 100).fillna(0)

# --- 사이드바 ---
st.sidebar.header("🕹️ 관리 메뉴")
if st.sidebar.button("🔄 즉시 새로고침 (캐시 무시)"):
    st.cache_data.clear(); st.rerun()
st.sidebar.divider()
today_str = now_kst.strftime('%Y-%m-%d')
today_exists = today_str in history_df['Date'].astype(str).values if not history_df.empty else False
if today_exists:
    st.sidebar.warning("⚠️ 이미 기록됨")
    if st.sidebar.button("♻️ 오늘 데이터 덮어쓰기"): record_performance(overwrite=True)
else:
    if st.sidebar.button("💾 오늘의 결과 저장하기"): record_performance(overwrite=False)

# --- UI 메인 섹션 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [Tab 0] 총괄 현황 ---
with tabs[0]:
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    t_profit, t_roi = t_eval - t_buy, (t_eval/t_buy-1)*100 if t_buy>0 else 0
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_profit:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("통합 누적 수익률", f"{t_roi:.2f}%")

    st.markdown("---")
    st.subheader("📑 계좌별 자산 요약")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '누적 수익률']).format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적 수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

    # 📊 성과 추이 차트
    if not history_df.empty:
        st.divider()
        col_g1, col_g2 = st.columns([2, 1])
        with col_g1:
            history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
            history_df = history_df.dropna(subset=['Date']).sort_values('Date')
            fig_t = go.Figure()
            bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
            fig_t.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI', line=dict(dash='dash', color='gray')))
            acc_c = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
            for c, clr in acc_c.items():
                if c in history_df.columns:
                    nv = 100 + history_df[c] - history_df[c].iloc[0]
                    fig_t.add_trace(go.Scatter(x=history_df['Date'], y=nv, name=c.replace('수익률',''), line=dict(color=clr, width=3), mode='lines+markers'))
            fig_t.update_layout(title="수익률 추이", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig_t, use_container_width=True)
        with col_g2:
            fig_pie = go.Figure(data=[go.Pie(labels=sum_acc['계좌명'], values=sum_acc['평가금액'], hole=.3, marker_colors=['#FF4B4B', '#87CEEB', '#00FF00'], textinfo='percent+label')])
            fig_pie.update_layout(title="계좌 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)

    # --- [수급 및 테마 레이더 섹션] ---
    st.divider()
    radar_data, fetch_time = get_cached_market_radar()
    my_stocks = full_df['종목명'].unique()
    m_info = get_market_status()

    st.subheader(f"🕵️ AI 실시간 마켓 레이더 (수집 시점: {fetch_time})")
    
    # 지수와 테마 배치
    c_idx1, c_idx2, c_theme = st.columns([1, 1, 2])
    with c_idx1:
        v = m_info.get('KOSPI', {})
        color = "#FF4B4B" if "+" in v.get('rate','') else "#87CEEB"
        st.markdown(f"**KOSPI: {v.get('now','-')}** <br> <span style='color:{color}; font-weight:bold;'>{v.get('diff','')} ({v.get('rate','')})</span>", unsafe_allow_html=True)
    with c_idx2:
        v = m_info.get('KOSDAQ', {})
        color = "#FF4B4B" if "+" in v.get('rate','') else "#87CEEB"
        st.markdown(f"**KOSDAQ: {v.get('now','-')}** <br> <span style='color:{color}; font-weight:bold;'>{v.get('diff','')} ({v.get('rate','')})</span>", unsafe_allow_html=True)
    with c_theme:
        st.markdown("**🔥 실시간 주도 테마 TOP 5**")
        theme_txt = " | ".join([f"{t['name']} ({t['rate']})" for t in radar_data["themes"][:5]])
        st.info(theme_txt if theme_txt else "장중 테마 데이터를 분석 중입니다.")

    def highlight_radar(top_list, my_stocks, color):
        if not top_list: return "데이터 수집 중..."
        res = []
        for i, s in enumerate(top_list):
            if s in my_stocks: res.append(f"{i+1}. <span style='color:{color}; font-weight:bold;'>{s} (보유)</span>")
            else: res.append(f"{i+1}. {s}")
        return "<br>".join(res)

    st.markdown("---")
    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
    col_t1.write("🟢 **외인 매수 TOP 10**"); col_t1.markdown(highlight_radar(radar_data["trades"]['외인매수'], my_stocks, "#FF4B4B"), unsafe_allow_html=True)
    col_t2.write("🔵 **외인 매도 TOP 10**"); col_t2.markdown(highlight_radar(radar_data["trades"]['외인매도'], my_stocks, "#87CEEB"), unsafe_allow_html=True)
    col_t3.write("🟢 **기관 매수 TOP 10**"); col_t3.markdown(highlight_radar(radar_data["trades"]['기관매수'], my_stocks, "#FF4B4B"), unsafe_allow_html=True)
    col_t4.write("🔵 **기관 매도 TOP 10**"); col_t4.markdown(highlight_radar(radar_data["trades"]['기관매도'], my_stocks, "#87CEEB"), unsafe_allow_html=True)

# --- [계좌별 상세 분석 탭] ---
def render_account_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_buy:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100 if a_buy>0 else 0:.2f}%")
        
        display_cols = ['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '수익률']
        st.dataframe(sub_df[display_cols].style.map(color_positive_negative, subset=['주가변동', '손익', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원', '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)
        
        st.divider()
        col_low1, col_low2 = st.columns([1, 2])
        with col_low1:
            if not sub_df.empty:
                fig_stock_pie = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
                fig_stock_pie.update_layout(title=f"종목 비중", height=350, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
                st.plotly_chart(fig_stock_pie, use_container_width=True)
        with col_low2:
            st.subheader(f"🔍 AI 맞춤 진단")
            top_stock = sub_df.sort_values('평가금액', ascending=False).iloc[0]['종목명'] if not sub_df.empty else "없음"
            st.success(f"{acc_name} 계좌의 핵심 종목은 **{top_stock}**입니다.")

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v22.1 인포스탁 스타일 통합 분석")
