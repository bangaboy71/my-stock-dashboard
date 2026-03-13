import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import time
import yfinance as yf

# 1. 설정 및 UI 스타일
# 🎯 탭 이름에 v40.99 낙인을 찍어 수정 여부를 즉시 확인할 수 있게 했습니다.
st.set_page_config(page_title="🚀 4단계 등급 적용 완료 v40.99", layout="wide")

# --- [v40.96: 현금흐름 4단계 등급 판정 함수] ---
def get_cashflow_grade(amount):
    if amount >= 1000000: return "💎 Diamond"
    elif amount >= 300000: return "🥇 Gold"
    elif amount >= 100000: return "🥈 Silver"
    else: return "🥉 Bronze"

# --- [전역 설정: 이름표 및 표시 컬럼] ---
GLOBAL_RENAME_MAP = {
    '전일대비손익': '전일대비(원)', 
    '전일대비변동율': '전일대비(%)'
}

GLOBAL_DISPLAY_COLS = ['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '손익', '전일대비(원)', '전일대비(%)', '누적수익률']

# --- [데이터 및 크롤링 엔진: 종목 코드 및 연구 데이터] ---
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "테스": "095610",
    "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387",
    "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690",
    "일진전기": "103590", "SK스퀘어": "402340"
}

DIVIDEND_SCHEDULE = {
    "삼성전자": [5, 8, 11, 4], "KT&G": [5, 8, 11, 4], "현대차2우B": [5, 8, 11, 4],
    "현대글로비스": [4, 8], "테스": [4], "에스티팜": [4], "일진전기": [4],
    "KODEX200타겟위클리커버드콜": list(range(1, 13))
}

RESEARCH_DATA = {
    "삼성전자": {"metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("특별 DPS", "500원", "3.5~7천원")], "implications": ["HBM3E 양산 본격화", "특별 배당 기반 강력 환원"]},
    "KT&G": {"metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("자사주 소각", "0.9조", "0.5~1.1조")], "implications": ["NGP 성장 동력 확보", "자사주 소각 가속화"]},
    "테스": {"metrics": [("영업이익률", "10.7%", "19.0%"), ("ROE", "6.2%", "14.5%"), ("정규 DPS", "500원", "700~900원")], "implications": ["선단공정 장비 수요 폭증", "ROE 14.5% 달성 전망"]},
    "현대글로비스": {"metrics": [("PCTC 선복량", "90척", "110척"), ("영업이익률", "6.5%", "7.2%"), ("배당성향", "25%", "35%")], "implications": ["완성차 해상운송 1위 굳히기", "수소 물류 인프라 선점"]},
    "현대차2우B": {"metrics": [("배당수익률", "7.5%", "9.2%"), ("하이브리드 비중", "12%", "20%"), ("ROE", "11%", "13%")], "implications": ["분기 배당 및 자사주 매입 강화", "믹스 개선을 통한 수익성 방어"]},
    "KODEX200타겟위클리커버드콜": {"metrics": [("목표 분배율", "연 12%", "월 1%↑"), ("옵션 프리미엄", "안정", "최적화"), ("지수 추종", "95%", "98%")], "implications": ["매주 옵션 매도를 통한 현금 흐름", "횡보장에서 코스피 대비 초과 수익"]},
    "에스티팜": {"metrics": [("올리고 매출", "2.1천억", "3.5천억"), ("영업이익률", "12%", "18%"), ("공장 가동률", "70%", "95%")], "implications": ["mRNA 원료 공급 글로벌 확장", "제2 올리고동 본격 가동 효과"]},
    "일진전기": {"metrics": [("초고압 변압기", "수주잔고↑", "북미 점유율↑"), ("영업이익률", "7%", "10%"), ("ROE", "14%", "18%")], "implications": ["미국 전력망 교체 사이클 수혜", "변압기 증설 라인 가동 개시"]}
}

st.markdown("""<style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 350px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    </style>""", unsafe_allow_html=True)

# --- [헬퍼 함수: 시장지수, 가격, 뉴스, 검색] ---
def get_market_status():
    data = {"KOSPI": {"val": "-", "pct": "0.00%", "color": "#ffffff"}, "KOSDAQ": {"val": "-", "pct": "0.00%", "color": "#ffffff"}, "USD/KRW": {"val": "-", "pct": "0원", "color": "#ffffff"}, "VOLUME": {"val": "-", "pct": "천주", "color": "#ffffff"}}
    header = {'User-Agent': 'Mozilla/5.0'}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            res = requests.get(f"https://finance.naver.com/sise/sise_index.naver?code={code}", headers=header, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            data[code]["val"] = soup.select_one("#now_value").get_text(strip=True)
            diff = soup.select_one("#change_value_and_rate").get_text(" ", strip=True)
            for w in ["상승", "하락", "보합"]: diff = diff.replace(w, "")
            data[code]["color"] = "#FF4B4B" if "+" in diff else "#87CEEB" if "-" in diff else "#ffffff"
            data[code]["pct"] = diff
            if code == "KOSPI": data["VOLUME"]["val"] = soup.select_one("#quant").get_text(strip=True)
        ex_res = requests.get("https://finance.naver.com/marketindex/", headers=header, timeout=5)
        ex_soup = BeautifulSoup(ex_res.text, 'html.parser')
        data["USD/KRW"]["val"] = ex_soup.select_one("span.value").get_text(strip=True)
        data["USD/KRW"]["pct"] = ex_soup.select_one("span.change").get_text(strip=True) + "원"
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
            date_str = dates[i].get_text(strip=True)
            is_recent = "전" in date_str or (datetime.now() - datetime.strptime(date_str, '%Y.%m.%d %H:%M')).total_seconds() < 86400 if ":" in date_str else False
            news_list.append({'title': titles[i].find('a').get_text(strip=True), 'link': "https://finance.naver.com" + titles[i].find('a')['href'], 'info': infos[i].get_text(strip=True), 'date': date_str, 'is_recent': is_recent})
    except: pass
    return news_list

def find_matching_col(df, account, stock=None):
    prefix = account.replace("투자", "").replace(" ", "")
    target = f"{prefix}{stock}수익률".replace(" ", "") if stock else f"{prefix}수익률".replace(" ", "")
    for col in df.columns:
        if target.lower() in str(col).replace(" ", "").lower(): return col
    return None

# --- [3. 데이터 로드 및 통합 정제 (v40.98 최적화)] ---
conn = st.connection("gsheets", type=GSheetsConnection)
try:
    full_df = conn.read(worksheet="종목 현황", ttl="1m")
    history_df = conn.read(worksheet="trend", ttl=0)
except: st.error("⚠️ 시트 연결 실패"); st.stop()

if not full_df.empty:
    full_df.columns = [c.strip() for c in full_df.columns]
    num_cols = ['수량', '매입단가', '52주최고가', '매입후최고가', '목표가', '주당 배당금', '목표수익률']
    for c in num_cols:
        if c in full_df.columns: full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', '').str.replace('%', ''), errors='coerce').fillna(0)
        elif c == '목표수익률': full_df['목표수익률'] = 10.0
    
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'], full_df['평가금액'] = full_df['수량']*full_df['매입단가'], full_df['수량']*full_df['현재가']
    full_df['손익'], full_df['전일대비손익'] = full_df['평가금액']-full_df['매입금액'], full_df['평가금액']-(full_df['수량']*full_df['전일종가'])
    full_df['예상배당금'] = full_df['수량'] * full_df['주당 배당금']
    full_df['누적수익률'] = (full_df['손익']/full_df['매입금액'].replace(0, float('nan'))*100).fillna(0)
    full_df['전일대비변동율'] = (full_df['전일대비손익'] / (full_df['평가금액'] - full_df['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    full_df['목표대비상승여력'] = full_df.apply(lambda x: ((x['목표가']/x['현재가']-1)*100) if x['현재가']>0 and x['목표가']>0 else 0, axis=1)
    if '최초매입일' in full_df.columns:
        full_df['최초매입일'] = pd.to_datetime(full_df['최초매입일'], errors='coerce')
        full_df['보유일수'] = (datetime.now().replace(hour=0,minute=0,second=0,microsecond=0) - full_df['최초매입일'].dt.tz_localize(None)).dt.days.fillna(365).astype(int).clip(lower=1)
    else: full_df['보유일수'] = 365

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    history_df = history_df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)
    base_row = history_df[history_df['Date'] == pd.Timestamp("2026-03-03")]
    history_df['KOSPI_Relative'] = (history_df['KOSPI'] / (base_row['KOSPI'].values[0] if not base_row.empty else history_df['KOSPI'].iloc[0]) - 1) * 100

# --- [4. 메인 UI 렌더링] ---
st.markdown(f"<h2 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 <span style='font-size: 1.2rem; opacity: 0.7;'>v40.99</span></h2>", unsafe_allow_html=True)

m_status = get_market_status()
h_cols = st.columns(4)
for i, k in enumerate(["KOSPI", "KOSDAQ", "USD/KRW", "VOLUME"]):
    with h_cols[i]:
        d = m_status[k]
        st.markdown(f"<div style='text-align: center; padding: 15px; border-radius: 12px; background: rgba(255,255,255,0.03); border: 1px solid {d['color']}44;'><div style='color: #aaa; font-size: 0.85rem;'>{k}</div><div style='color: {d['color']}; font-size: 1.8rem; font-weight: bold;'>{d['val']}</div><div style='color: {d['color']}; font-size: 1.0rem;'>{d['pct']}</div></div>", unsafe_allow_html=True)

tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy = full_df['평가금액'].sum(), full_df['매입금액'].sum()
    t_prev_eval = (full_df['수량'] * full_df['전일종가']).sum()
    t_diff, t_pct = t_eval - t_prev_eval, (t_eval/t_prev_eval-1)*100 if t_prev_eval!=0 else 0
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", delta=f"{t_diff:+,.0f}원 ({t_pct:+.2f}%)")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("총 누적 손익", f"{t_eval-t_buy:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100:+.2f}%")

    st.divider()
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum', '전일대비손익':'sum'}).reset_index()
    sum_acc['누적수익률'] = (sum_acc['손익']/sum_acc['매입금액']*100).fillna(0)
    st.dataframe(sum_acc.rename(columns=GLOBAL_RENAME_MAP).style.format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

    st.divider()
    t_div = full_df['예상배당금'].sum()
    m_tax = (t_div * (1 - 0.154)) / 12
    t_grade = get_cashflow_grade(m_tax) # 🎯 4단계 적용
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("연간 예상 총 배당금", f"{t_div:,.0f}원")
    d2.metric("세후 월 평균 수령액", f"{m_tax:,.0f}원")
    d3.metric("포트 배당수익률", f"{(t_div/t_eval*100):.2f}%" if t_eval!=0 else "0%")
    d4.metric("통합 현금흐름 등급", t_grade)

# [계좌별 탭 렌더링 함수]
def render_account_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        a_eval, a_buy = sub_df['평가금액'].sum(), sub_df['매입금액'].sum()
        a_div = sub_df['예상배당금'].sum()
        m_tax = (a_div * (1 - 0.154)) / 12
        a_grade = get_cashflow_grade(m_tax) # 🎯 4단계 적용

        # 계좌 메트릭
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("계좌 평가액", f"{a_eval:,.0f}원")
        c2.metric("세후 월 수령액", f"{m_tax:,.0f}원")
        c3.metric("계좌 수익률", f"{(a_eval/a_buy-1)*100:+.2f}%" if a_buy!=0 else "0%")
        c4.metric("계좌 등급", a_grade)

        # (203행 근처의 st.dataframe 줄을 아래로 교체)
        
        # 🎯 안전한 컬럼 선택 로직 적용
        available_cols = [c for c in GLOBAL_DISPLAY_COLS if c in plot_df.columns]
        st.dataframe(plot_df[available_cols].style.format({
            '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', 
            '현재가': '{:,.0f}원', '매입단가': '{:,.0f}원',
            '전일대비(원)': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        # 🎯 [Wide 배치] 현금흐름 차트 + 자산 비중 차트
        g_l, g_r = st.columns(2)
        with g_l:
            m_data = {m: 0 for m in range(1, 13)}
            for _, r in sub_df.iterrows():
                for m in DIVIDEND_SCHEDULE.get(r['종목명'], [4]): m_data[m] += (r['예상배당금']/len(DIVIDEND_SCHEDULE.get(r['종목명'], [4])))
            fig_div = go.Figure(go.Bar(x=[f"{m}월" for m in range(1, 13)], y=list(m_data.values()), marker_color='rgba(255, 215, 0, 0.6)', text=[f"{v/10000:.1f}만" if v>0 else "" for v in m_data.values()], textposition='outside'))
            fig_div.update_layout(title="📅 월별 배당 예측", height=280, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
            st.plotly_chart(fig_div, use_container_width=True)
        with g_r:
            fig_asset = go.Figure(go.Bar(y=sub_df['종목명'].apply(lambda x: x[:9]), x=sub_df['평가금액'], orientation='h', marker_color='#87CEEB'))
            fig_asset.update_layout(title="📊 자산 비중", height=280, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
            st.plotly_chart(fig_asset, use_container_width=True)

        st.divider()
        # --- [종목 분석 및 성과 추이] ---
        sel = st.selectbox(f"📍 {acc_name} 종목 분석", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        s_row = sub_df[sub_df['종목명'] == sel].iloc[0]
        
        # 🎯 성과 추이 차트 (v40.94 레이아웃 보정)
        if not history_df.empty:
            fig_acc = go.Figure()
            h_dt = history_df['Date'].dt.date.astype(str)
            goal_val = float(s_row.get('목표수익률', 10.0))
            indiv_target = int(goal_val * 1000) / 1000 # 🎯 소수점 3자리 버림
            
            # KOSPI, 목표선, 계좌수익률, 종목수익률(9자리 제한)
            fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df['KOSPI_Relative'], name='KOSPI', line=dict(dash='dash', color='rgba(255,255,255,0.2)')))
            fig_acc.add_trace(go.Scatter(x=h_dt, y=[indiv_target]*len(h_dt), name='목표 수익률', line=dict(color='#FFD700', dash='dot')))
            
            a_col = find_matching_col(history_df, acc_name)
            if a_col: 
                line_c = '#00FF00' if history_df[a_col].iloc[-1] >= indiv_target else '#FF4B4B'
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[a_col], name='계좌 수익률', line=dict(width=4, color=line_c)))
            
            s_col = find_matching_col(history_df, acc_name, sel)
            if s_col: fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[s_col], name=sel[:9], line=dict(dash='dashdot', color='rgba(135,206,235,0.6)')))

            fig_acc.update_layout(
                title=dict(text=f"📈 {sel} 분석 및 {acc_name} 성과 추이", x=0.0, xanchor='left'),
                height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white",
                legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
                margin=dict(l=10, r=10, t=80, b=80), xaxis=dict(type='category', tickangle=-45)
            )
            st.plotly_chart(fig_acc, use_container_width=True)

        # 실시간 뉴스
        st.divider()
        news = get_stock_news(sel)
        n_cols = st.columns(2)
        for i, item in enumerate(news):
            with n_cols[i%2]:
                badge = "<span style='color:#FFD700;'>[NEW]</span>" if item['is_recent'] else ""
                st.html(f"<div style='margin-bottom:10px; padding:10px; border-radius:8px; background:rgba(255,255,255,0.02); border-left:4px solid #87CEEB;'>{badge} <a href='{item['link']}' style='color:#87CEEB; text-decoration:none;'>{item['title']}</a><br><small>{item['info']} | {item['date']}</small></div>")

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])

with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
    st.divider()
    st.caption(f"최종 갱신: {datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')}")

