import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import time
import yfinance as yf

# --- [v40.50 전역 설정: 이름표 및 테이블 규격] ---
GLOBAL_RENAME_MAP = {
    '전일대비손익': '전일대비(원)', 
    '전일대비변동율': '전일대비(%)'
}
GLOBAL_DISPLAY_COLS = ['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '손익', '전일대비(원)', '전일대비(%)', '누적수익률']

# 1. 설정 및 UI 스타일
st.set_page_config(page_title="가족 자산 성장 관제탑 v40.50", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 350px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .stDataFrame thead tr th { text-align: center !important; } /* 헤더 중앙 정렬 */
    </style>
    """, unsafe_allow_html=True)

# 🎯 종목 분석 데이터 & 코드 (전달해주신 RESEARCH_DATA, STOCK_CODES 유지)
RESEARCH_DATA = {
    "삼성전자": {"metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("특별 DPS", "500원", "3.5~7천원")], "implications": ["HBM3E 양산 본격화", "특별 배당 기반 강력 환원"]},
    "KT&G": {"metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("자사주 소각", "0.9조", "0.5~1.1조")], "implications": ["NGP 성장 동력 확보", "자사주 소각 가속화"]},
    "테스": {"metrics": [("영업이익률", "10.7%", "19.0%"), ("ROE", "6.2%", "14.5%"), ("정규 DPS", "500원", "700~900원")], "implications": ["선단공정 장비 수요 폭증", "ROE 14.5% 달성 전망"]},
    "LG에너지솔루션": {"metrics": [("수주잔고", "450조", "520조+"), ("영업이익률", "5.2%", "8.5%"), ("4680 양산", "준비", "본격화")], "implications": ["4680 배터리 테슬라 공급 개시", "ESS 부문 매출 비중 확대"]},
    "현대글로비스": {"metrics": [("PCTC 선복량", "90척", "110척"), ("영업이익률", "6.5%", "7.2%"), ("배당성향", "25%", "35%")], "implications": ["완성차 해상운송 1위 굳히기", "수소 물류 인프라 선점"]},
    "현대차2우B": {"metrics": [("배당수익률", "7.5%", "9.2%"), ("하이브리드 비중", "12%", "20%"), ("ROE", "11%", "13%")], "implications": ["분기 배당 및 자사주 매입 강화", "믹스 개선을 통한 수익성 방어"]},
    "KODEX200타겟위클리커버드콜": {"metrics": [("목표 분배율", "연 12%", "월 1%↑"), ("옵션 프리미엄", "안정", "최적화"), ("지수 추종", "95%", "98%")], "implications": ["매주 옵션 매도를 통한 현금 흐름", "횡보장에서 코스피 대비 초과 수익"]},
    "에스티팜": {"metrics": [("올리고 매출", "2.1천억", "3.5천억"), ("영업이익률", "12%", "18%"), ("공장 가동률", "70%", "95%")], "implications": ["mRNA 원료 공급 글로벌 확장", "제2 올리고동 본격 가동 효과"]},
    "일진전기": {"metrics": [("초고압 변압기", "수주잔고↑", "북미 점유율↑"), ("영업이익률", "7%", "10%"), ("ROE", "14%", "18%")], "implications": ["미국 전력망 교체 사이클 수혜", "변압기 증설 라인 가동 개시"]},
    "SK스퀘어": {"metrics": [("NAV 할인율", "65%", "45%"), ("하이닉스 지분", "20.1%", "가치 재평가"), ("주주환원", "0.3조", "0.6조")], "implications": ["자사주 소각 등 적극적 가치 제고", "반도체 포트폴리오 중심 성장"]}
}

STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "테스": "095610", "LG에너지솔루션": "373220",
    "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400",
    "에스티팜": "237690", "일진전기": "103590", "SK스퀘어": "402340"
}

# --- [엔진 함수: 지수, 데이터 수집] ---
def get_market_status():
    data = {
        "KOSPI": {"val": "-", "pct": "0.00%", "color": "#ffffff"},
        "KOSDAQ": {"val": "-", "pct": "0.00%", "color": "#ffffff"},
        "USD/KRW": {"val": "-", "pct": "0원", "color": "#ffffff"},
        "VOLUME": {"val": "-", "pct": "천주", "color": "#ffffff"}
    }
    header = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers=header, timeout=5)
            res.encoding = 'euc-kr'
            soup = BeautifulSoup(res.text, 'html.parser')
            now_el = soup.select_one("#now_value")
            if now_el: data[code]["val"] = now_el.get_text(strip=True)
            diff_el = soup.select_one("#change_value_and_rate")
            if diff_el:
                raw_txt = "".join([w for w in diff_el.get_text(" ", strip=True) if w not in ["상승", "하락", "보합"]])
                if "+" in raw_txt: data[code]["color"] = "#FF4B4B"
                elif "-" in raw_txt: data[code]["color"] = "#87CEEB"
                data[code]["pct"] = raw_txt.strip()
            if code == "KOSPI":
                vol_el = soup.select_one("#quant")
                if vol_el: data["VOLUME"]["val"], data["VOLUME"]["pct"] = vol_el.get_text(strip=True), "천주"
        # 환율
        ex_res = requests.get("https://finance.naver.com/marketindex/", headers=header, timeout=5)
        ex_soup = BeautifulSoup(ex_res.text, 'html.parser')
        ex_val = ex_soup.select_one("span.value")
        if ex_val:
            data["USD/KRW"]["val"] = ex_val.get_text(strip=True)
            ex_blind = ex_soup.select_one("div.head_info > span.blind").get_text()
            data["USD/KRW"]["color"] = "#FF4B4B" if "상승" in ex_blind else "#87CEEB" if "하락" in ex_blind else "#ffffff"
            data["USD/KRW"]["pct"] = ("+" if "상승" in ex_blind else "-" if "하락" in ex_blind else "") + ex_soup.select_one("span.change").get_text(strip=True) + "원"
    except: pass
    return data

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

def get_stock_news(name):
    code = STOCK_CODES.get(str(name).replace(" ", ""))
    if not code: return []
    news_list = []
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        titles, infos, dates = soup.find_all('td', class_='title'), soup.find_all('td', class_='info'), soup.find_all('td', class_='date')
        for i in range(min(len(titles), 6)):
            d_str = dates[i].get_text(strip=True)
            is_recent = ("전" in d_str) or ((datetime.now() - datetime.strptime(d_str, '%Y.%m.%d %H:%M')).total_seconds() < 86400 if "." in d_str else False)
            news_list.append({'title': titles[i].find('a').get_text(strip=True), 'link': "https://finance.naver.com" + titles[i].find('a')['href'], 'info': infos[i].get_text(strip=True), 'date': d_str, 'is_recent': is_recent})
    except: pass
    return news_list

def find_matching_col(df, account, stock=None):
    prefix = account.replace("투자", "").replace(" ", "")
    target = f"{prefix}{stock}수익률" if stock else f"{prefix}수익률"
    for col in df.columns:
        if target.replace(" ", "") in str(col).replace(" ", ""): return col
    return None

# --- [데이터 로드] ---
conn = st.connection("gsheets", type=GSheetsConnection)
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

if not full_df.empty:
    full_df.columns = [c.strip() for c in full_df.columns]
    num_cols = ['수량', '매입단가', '52주최고가', '매입후최고가', '목표가']
    for c in num_cols: full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'], full_df['평가금액'] = full_df['수량'] * full_df['매입단가'], full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비변동율'] = (full_df['전일대비손익'] / (full_df['평가금액'] - full_df['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    full_df['목표대비상승여력'] = full_df.apply(lambda x: ((x['목표가']/x['현재가']-1)*100) if x['현재가']>0 and x['목표가']>0 else 0, axis=1)
    full_df['보유일수'] = (datetime.now() - pd.to_datetime(full_df.get('최초매입일', datetime.now())).dt.tz_localize(None)).dt.days.fillna(365).astype(int).clip(lower=1)

# --- [메인 UI] ---
st.markdown("<h2 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v40.50</h2>", unsafe_allow_html=True)

# HUD 렌더링
m_status = get_market_status()
hud_cols = st.columns(4)
for i, (title, key) in enumerate(zip(["KOSPI", "KOSDAQ", "USD/KRW", "MARKET VOL"], ["KOSPI", "KOSDAQ", "USD/KRW", "VOLUME"])):
    d = m_status[key]
    hud_cols[i].markdown(f"<div style='text-align: center; padding: 15px; border-radius: 12px; background: rgba(255,255,255,0.03); border: 1px solid {d['color']}44;'><div style='color: #aaa; font-size: 0.85rem;'>{title}</div><div style='color: {d['color']}; font-size: 1.8rem; font-weight: bold;'>{d['val']}</div><div style='color: {d['color']}; font-size: 1.0rem;'>{d['pct']}</div></div>", unsafe_allow_html=True)

tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy = full_df['평가금액'].sum(), full_df['매입금액'].sum()
    t_prev_eval = (full_df['수량'] * full_df['전일종가']).sum()
    t_change_amt, t_change_pct = t_eval - t_prev_eval, ((t_eval - t_prev_eval)/t_prev_eval*100 if t_prev_eval !=0 else 0)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", delta=f"{t_change_amt:+,.0f}원 ({t_change_pct:+.2f}%)")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원"); m3.metric("총 누적 손익", f"{t_eval-t_buy:+,.0f}원"); m4.metric("통합 수익률", f"{(t_eval/t_buy-1)*100:+.2f}%")
    st.divider()
    # 하이브리드 정렬 테이블 (수치 우측 고정)
    total_plot_df = full_df.rename(columns=GLOBAL_RENAME_MAP)
    st.dataframe(total_plot_df[GLOBAL_DISPLAY_COLS].style.apply(lambda x: ['color: #FF4B4B' if (i >= 6 and val > 0) else 'color: #87CEEB' if (i >= 6 and val < 0) else '' for i, val in enumerate(x)], axis=1).format({'수량': '{:,.0f}', '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(원)': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

# [계좌탭 공통 함수]
def render_account_tab(acc_name, tab_obj, history_col_key):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        a_diff = sub_df['전일대비손익'].sum()
        a_pct = (a_diff / (a_eval - a_diff) * 100) if (a_eval - a_diff) != 0 else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", delta=f"{a_diff:+,.0f}원 ({a_pct:+.2f}%)")
        c2.metric("매입액", f"{a_buy:,.0f}원"); c3.metric("손익", f"{a_eval-a_buy:+,.0f}원"); c4.metric("수익률", f"{(a_eval/a_buy-1)*100:+.2f}%")
        
        # 테이블 출력
        plot_df = sub_df.rename(columns=GLOBAL_RENAME_MAP)
        st.dataframe(plot_df[GLOBAL_DISPLAY_COLS].style.apply(lambda x: ['color: #FF4B4B' if (i >= 6 and val > 0) else 'color: #87CEEB' if (i >= 6 and val < 0) else '' for i, val in enumerate(x)], axis=1).format({'수량': '{:,.0f}', '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(원)': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)
        st.divider()
        sel = st.selectbox(f"📍 {acc_name} 종목 분석", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        s_row = sub_df[sub_df['종목명'] == sel].iloc[0]
        
        # 중앙 모니터 & 리스크 시스템 (HTML 로직 유지)
        col_res, col_strat = st.columns([1, 1])
        # ... (전달해주신 HTML 전략 모니터 및 리스크 경보 코드 삽입부) ...
        
        # [v40.25 자산 성장 막대 차트]
        g_left, g_right = st.columns([2, 1])
        with g_left: # 성과 추이 차트
            if not history_df.empty:
                fig_acc = go.Figure()
                fig_acc.add_trace(go.Scatter(x=history_df['Date'].dt.date, y=history_df['KOSPI_Relative'], name='KOSPI', line=dict(dash='dash')))
                st.plotly_chart(fig_acc, use_container_width=True)
        with g_right: # 성장 막대 차트
            acc_total_eval = sub_df['평가금액'].sum()
            chart_df = sub_df[['종목명', '매입금액', '평가금액', '누적수익률']].copy()
            chart_df['Display_Name'] = chart_df['종목명'].apply(lambda x: x[:9] + ".." if len(x) > 9 else x)
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(y=chart_df['Display_Name'], x=chart_df['매입금액'], orientation='h', name='매입', marker_color='rgba(170,170,170,0.3)'))
            fig_bar.add_trace(go.Bar(y=chart_df['Display_Name'], x=chart_df['평가금액'], orientation='h', name='평가', marker_color='#FF4B4B', text=[f"{int(v/acc_total_eval*100)}% ({r:+.1f}%)" for v,r in zip(chart_df['평가금액'], chart_df['누적수익률'])], textposition='outside'))
            fig_bar.update_layout(height=400, showlegend=False, margin=dict(r=140), xaxis=dict(range=[0, chart_df['평가금액'].max()*1.25]))
            st.plotly_chart(fig_bar, use_container_width=True)
            
        # 뉴스 섹션
        st.divider()
        st.html(f"<b>📰 {sel} 실시간 주요 뉴스</b>")
        for n in get_stock_news(sel):
            badge = "<span style='color:#FFD700;'>[NEW]</span> " if n['is_recent'] else ""
            st.markdown(f"{badge}<a href='{n['link']}'>{n['title']}</a> <small>{n['info']} | {n['date']}</small>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
