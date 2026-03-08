import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 UI 스타일 정의
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.11", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 350px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(135,206,235,0.2); background-color: rgba(135,206,235,0.03); min-height: 250px; margin-bottom: 20px; }
    .sector-title { font-size: 1.2rem; font-weight: bold; border-bottom: 3px solid #87CEEB; padding-bottom: 10px; margin-bottom: 15px; color: #87CEEB; }
    .leader-tag { background: rgba(255,215,0,0.15); border: 1px solid #FFD700; padding: 4px 10px; border-radius: 5px; color: #FFD700; font-size: 0.8rem; font-weight: bold; margin-bottom: 10px; display: inline-block; }
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 25px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.3rem; margin-bottom: 20px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 12px; }
    .insight-flex { display: flex; gap: 30px; align-items: flex-start; }
    .insight-left { flex: 1.3; }
    .insight-right { flex: 1; background: rgba(255,215,0,0.04); padding: 20px; border-radius: 10px; border-left: 5px solid #FFD700; }
    .research-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
    .research-table th { text-align: left; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
    .research-table td { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .target-val { color: #FFD700; font-weight: bold; }
    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.2rem; border: 2px solid; text-align: center; background-color: rgba(0,0,0,0.2); }
    .up-style { color: #FF4B4B; border-color: #FF4B4B; }
    .down-style { color: #87CEEB; border-color: #87CEEB; }
    .acc-flash-container { background: rgba(255,215,0,0.05); padding: 20px; border-radius: 10px; border: 1px dashed #FFD700; margin-top: 25px; }
    .acc-flash-item { font-size: 0.9rem; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 6px; }
    .acc-flash-stock { color: #87CEEB; font-weight: bold; margin-right: 10px; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; cursor: pointer; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 엔진 및 연구 데이터베이스] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

RESEARCH_DATA = {
    "삼성전자": {"desc": "2026년 영업이익 185조원 목표의 압도적 모멘텀.", "metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("특별 DPS", "500원", "3,500~7,000원"), ("시가배당률", "1.9%", "4.5~6.0%")], "implications": ["HBM3E 양산 본격화 및 파운드리 수익성 개선", "특별 배당 포함 시 강력한 환원 기대", "AI 서버 중심 메모리 수요 폭증에 따른 체질 개선"]},
    "KT&G": {"desc": "ROE 15% 달성 목표 및 밸류업 구간 진입.", "metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("자사주 소각", "0.9조", "0.5~1.1조"), ("정규 DPS", "6,000원", "6,400~6,600원")], "implications": ["해외 궐련 및 NGP 성장 동력 확보", "발행주식 20% 소각을 통한 가치 제고", "글로벌 신공장 가동 효과 본격화"]},
    "현대차2우B": {"desc": "고배당 우선주 및 은퇴 포트폴리오 캐시카우.", "metrics": [("영업이익률", "6.2%", "7.0%"), ("ROE", "13.0%", "15.5%"), ("정규 DPS", "13,600원", "14.5~15.5천원"), ("시가배당률", "5.7%", "6.4%")], "implications": ["SUV/제네시스 믹스 개선 및 수익 가이드라인 준수", "본주 대비 높은 할인율로 배당수익률 극대화", "분기 배당 및 자사주 소각 정책 강화"]},
    "테스": {"desc": "반도체 선단공정 장비 국산화 수혜.", "metrics": [("영업이익률", "10.7%", "19.0%"), ("ROE", "6.2%", "14.5%"), ("PBR", "1.1배", "1.6배"), ("정규 DPS", "500원", "700~900원")], "implications": ["메모리 선단 공정 전환 장비 수요 폭증", "2026년 ROE 14.5% 달성 전망", "안정적 재무 기반 배당 확대 기조"]},
    "KODEX200타겟위클리커버드콜": {"desc": "연 15% 분배 지향 은퇴 특화 인컴 도구.", "metrics": [("옵션 프리미엄", "연 15%", "연 15%"), ("월 분배금", "110원", "120원"), ("시가분배율", "연 12.5%", "연 15.0%"), ("수익구조", "인컴+상승분", "타겟 프리미엄")], "implications": ["박스권 시장 내 콜옵션 매도 수익 극대화", "은퇴 생활비 마련을 위한 월 분배금 최적화", "지수 상승 일부 참여 및 하방 방어력 보유"]}
}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def get_market_indices():
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            market[code] = {"now": val, "diff": raw[0].replace("상승","+").replace("하락","-"), "rate": raw[1], "style": "up-style" if "+" in raw[0] or "상승" in raw[0] else "down-style"}
    except: market = {"KOSPI": {"now": "-", "diff": "-", "rate": "-", "style": ""}, "KOSDAQ": {"now": "-", "diff": "-", "rate": "-", "style": ""}}
    return market

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

def get_acc_news(stocks):
    news_list = []
    try:
        for s in stocks:
            code = STOCK_CODES.get(s.replace(" ", ""))
            if not code: continue
            soup = BeautifulSoup(requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            news_sec = soup.find("div", {"class": "news_section"})
            if news_sec:
                tag = news_sec.find("li").find("a")
                news_list.append({"name": s, "title": tag.text.strip(), "url": tag['href'] if tag['href'].startswith("http") else f"https://finance.naver.com{tag['href']}"})
    except: pass
    return news_list

# --- [3. 데이터 로드 및 전처리] ---
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'], full_df['평가금액'] = full_df['수량'] * full_df['매입단가'], full_df['수량'] * full_df['현재가']
    full_df['전일평가금액'] = full_df['수량'] * full_df['전일종가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비손익'] = full_df['평가금액'] - full_df['전일평가금액']
    full_df['전일대비변동률'] = (full_df['전일대비손익'] / full_df['전일평가금액'].replace(0, float('nan')) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [4. 정밀 색채 스타일 함수] ---
def style_summary_precision(df):
    def apply_color(row):
        # 평가금액 색채: 평가금액 vs 매입금액
        eval_c = 'color: #FF4B4B' if row['평가금액'] > row['매입금액'] else 'color: #87CEEB' if row['평가금액'] < row['매입금액'] else ''
        p_c = 'color: #FF4B4B' if row['손익'] > 0 else 'color: #87CEEB' if row['손익'] < 0 else ''
        d_c = 'color: #FF4B4B' if row['전일대비손익'] > 0 else 'color: #87CEEB' if row['전일대비손익'] < 0 else ''
        return ['', '', eval_c, p_c, d_c, d_c, p_c]
    return df.style.apply(apply_color, axis=1)

def style_holdings_precision(df):
    def apply_color(row):
        # 현재가 색채: 현재가 vs 매입단가
        price_c = 'color: #FF4B4B' if row['현재가'] > row['매입단가'] else 'color: #87CEEB' if row['현재가'] < row['매입단가'] else ''
        d_c = 'color: #FF4B4B' if row['전일대비손익'] > 0 else 'color: #87CEEB' if row['전일대비손익'] < 0 else ''
        t_c = 'color: #FF4B4B' if row['누적수익률'] > 0 else 'color: #87CEEB' if row['누적수익률'] < 0 else ''
        return ['', '', '', '', price_c, '', d_c, d_c, t_c]
    return df.style.apply(apply_color, axis=1)

# --- [5. UI 메인 구성] ---
st.sidebar.header("🕹️ 관제탑 마스터 메뉴")
if st.sidebar.button("🔄 실시간 데이터 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 결과 저장"):
    today = now_kst.date()
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    new_row = {"Date": today, "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    conn.update(worksheet="trend", data=pd.concat([history_df[history_df['Date']!=today], pd.DataFrame([new_row])]).sort_values('Date'))
    st.sidebar.success("저장 완료"); st.rerun()

st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v36.11</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy, t_prev = full_df['평가금액'].sum(), full_df['매입금액'].sum(), full_df['전일평가금액'].sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("총 누적 손익", f"{t_eval-t_buy:+,.0f}원", f"{t_eval-t_prev:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100:.2f}%", f"{(t_eval/t_prev-1)*100 if t_prev>0 else 0:+.2f}%")
    
    st.divider()
    st.subheader("투자 주체별 성과 요약")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum', '전일대비손익':'sum'}).reset_index()
    sum_acc['누적수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    sum_acc['전일대비변동률'] = (sum_acc['전일대비손익'] / (sum_acc['평가금액'] - sum_acc['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    
    # 지표 배치 조정
    sum_acc = sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비손익', '전일대비변동률', '누적수익률']]
    st.dataframe(style_summary_precision(sum_acc).format({
        '매입금액':'{:,.0f}원', '평가금액':'{:,.0f}원', '손익':'{:+,.0f}원', '전일대비손익':'{:+,.0f}원', '전일대비변동률':'{:+.2f}%', '누적수익률':'{:+.2f}%'
    }), use_container_width=True, hide_index=True)

    if not history_df.empty:
        try:
            fig = go.Figure()
            h_dates = history_df['Date'].dt.date.astype(str)
            fig.add_trace(go.Scatter(x=h_dates, y=history_df['KOSPI'], name='KOSPI 지수', line=dict(dash='dash', color='gray')))
            for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
                if col in history_df.columns:
                    fig.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
            fig.update_layout(title="📈 통합 수익률 추이 (vs KOSPI)", xaxis=dict(type='category'), height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
            st.plotly_chart(fig, use_container_width=True)
        except: st.warning("수익률 추이 데이터를 불러오는 중입니다.")

    st.divider()
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    idx_l.markdown(f"<div class='index-indicator {m_idx['KOSPI']['style']}'>KOSPI: {m_idx['KOSPI']['now']} ({m_idx['KOSPI']['diff']}, {m_idx['KOSPI']['rate']})</div>", unsafe_allow_html=True)
    idx_r.markdown(f"<div class='index-indicator {m_idx['KOSDAQ']['style']}'>KOSDAQ: {m_idx['KOSDAQ']['now']} ({m_idx['KOSDAQ']['diff']}, {m_idx['KOSDAQ']['rate']})</div>", unsafe_allow_html=True)
    
    rep_l, rep_r = st.columns(2)
    with rep_l: st.markdown("<div class='report-box'><h4 style='color:#87CEEB;'>🇰🇷 국내 시장 분석</h4><p>국내 증시는 코스피 5,000선 시대를 열며 선진국형 증시로 탈바꿈 중입니다. 반도체와 모빌리티 섹터의 강력한 이익 체력이 지수의 하방 경직성을 확보하고 있습니다.</p></div>", unsafe_allow_html=True)
    with rep_r: st.markdown("<div class='report-box'><h4 style='color:#FF4B4B;'>🌍 글로벌 매크로 분석</h4><p>나스닥 AI 랠리와 미 연준의 금리 기조가 국내 대형 IT주에 우호적입니다. 환율 변동성은 수출 대형주의 영업이익률을 지지하는 요소로 작용하고 있습니다.</p></div>", unsafe_allow_html=True)

    st.divider()
    s_cols = st.columns(3)
    sectors = {"반도체 / IT": "HBM 수요 폭발 및 AI 서버 증설 수혜.", "전력 / ESS": "북미 인프라 교체 및 데이터센터 가동 수혜.", "배터리 / 에너지": "전고체 기술 우위 선점 기업 중심 재편.", "바이오 / CDMO": "RNA 치료제 및 대규모 위탁생산 모멘텀.", "모빌리티 / 전장": "현대차 그룹 중심 밸류업 및 하이브리드 강세.", "소비재 / 뷰티": "K-뷰티의 북미 및 글로벌 시장 점유율 폭증."}
    for i, (n, d) in enumerate(sectors.items()):
        with s_cols[i % 3]: st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><div class='leader-tag'>👑 주도 섹터 분석</div><p>{d}</p></div>", unsafe_allow_html=True)

# [투자 주체별 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        # 🎯 보유종목 상세 수익표
        st.dataframe(style_holdings_precision(sub_df[[
            '종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '전일대비손익', '전일대비변동률', '누적수익률'
        ]]).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '매입금액': '{:,.0f}원', '현재가': '{:,.0f}원', 
            '평가금액': '{:,.0f}원', '전일대비손익': '{:+,.0f}원', '전일대비변동률': '{:+.2f}%', '누적수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        
        # 🎯 딥다이브 (2열 레이아웃)
        res = RESEARCH_DATA.get(sel.replace(" ", ""))
        if res:
            rows = "".join([f"<tr><td>{m[0]}</td><td>{m[1]}</td><td class='target-val'>{m[2]}</td></tr>" for m in res['metrics']])
            implications_html = "".join([f"<div class='implication-item'>• {imp}</div>" for imp in res['implications']])
            st.markdown(f"""
            <div class='insight-card'>
                <div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브 (2026 Target)</div>
                <div class='insight-flex'>
                    <div class='insight-left'><table class='research-table'><thead><tr><th>지표</th><th>25년 추정</th><th>26년 Target</th></tr></thead><tbody>{rows}</tbody></table></div>
                    <div class='insight-right'><div class='implication-title'>💡 투자 시사점 및 전략</div>{implications_html}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        g_left, g_right = st.columns([2, 1])
        with g_left:
            if not history_df.empty and history_col in history_df.columns:
                fig_acc = go.Figure()
                h_dt = history_df['Date'].dt.date.astype(str)
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                fig_acc.update_layout(title=f"📈 {acc_name} 성과 추이", height=400, xaxis=dict(type='category'), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig_acc, use_container_width=True)
        with g_right:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

        acc_news = get_acc_news(sub_df['종목명'].unique().tolist())
        if acc_news:
            news_html = " ".join([f"<div class='acc-flash-item'><span class='acc-flash-stock'>[{n['name']}]</span> <a href='{n['url']}' target='_blank' class='news-link'>{n['title']} ↗️</a></div>" for n in acc_news])
            st.markdown(f"<div class='acc-flash-container'><div style='font-weight: bold; color: #FFD700; margin-bottom: 12px;'>🔔 보유종목 실시간 공시 및 뉴스 (새 창)</div>{news_html}</div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v36.11 가디언 프리시전 얼티밋")
