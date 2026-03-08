import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 UI 스타일 (v36.5 원형 레이아웃 100% 복구)
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.28", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 350px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(135,206,235,0.2); background-color: rgba(135,206,235,0.03); min-height: 250px; margin-bottom: 20px; }
    .sector-title { font-size: 1.2rem; font-weight: bold; border-bottom: 3px solid #87CEEB; padding-bottom: 10px; margin-bottom: 15px; color: #87CEEB; }
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 25px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.3rem; margin-bottom: 20px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 12px; }
    .insight-flex { display: flex; gap: 30px; align-items: flex-start; }
    .insight-left { flex: 1.3; }
    .insight-right { flex: 1; background: rgba(255,215,0,0.04); padding: 20px; border-radius: 10px; border-left: 5px solid #FFD700; }
    .research-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
    .research-table th { text-align: left; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
    .research-table td { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .target-val { color: #FFD700; font-weight: bold; }
    .acc-flash-container { background: rgba(255,215,0,0.05); padding: 20px; border-radius: 10px; border: 1px dashed #FFD700; margin-top: 25px; }
    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.2rem; border: 2px solid; text-align: center; background-color: rgba(0,0,0,0.2); }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 엔진 및 헬퍼 함수] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}
RESEARCH_DATA = {
    "삼성전자": {"metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("특별 DPS", "500원", "3.5~7천원")], "implications": ["HBM3E 양산 본격화", "특별 배당 기반 강력 환원"]},
    "KT&G": {"metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("자사주 소각", "0.9조", "0.5~1.1조")], "implications": ["NGP 성장 동력 확보", "발행주식 20% 소각"]},
    "테스": {"metrics": [("영업이익률", "10.7%", "19.0%"), ("ROE", "6.2%", "14.5%"), ("정규 DPS", "500원", "700~900원")], "implications": ["선단공정 장비 수요 폭증", "ROE 14.5% 달성 전망"]}
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
            market[code] = {"now": val, "style": "color: #FF4B4B" if "상승" in raw[0] else "color: #87CEEB"}
    except: market = {"KOSPI": {"now": "-", "style": ""}}
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

# --- [3. 데이터 로드 및 정규화] ---
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'], full_df['평가금액'] = full_df['수량'] * full_df['매입단가'], full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
    full_df['전일대비변동률'] = (full_df['전일대비손익'] / (full_df['수량'] * full_df['전일종가']).replace(0, float('nan')) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    # 🎯 사실 기반 정렬 (3/6 밀림 방지 핵심)
    history_df = history_df.dropna(subset=['Date']).sort_values('Date').drop_duplicates('Date', keep='last').reset_index(drop=True)
    
    base_date = pd.Timestamp("2026-03-03")
    base_row = history_df[history_df['Date'] == base_date]
    if not base_row.empty:
        history_df['KOSPI_Rel'] = (history_df['KOSPI'] / base_row['KOSPI'].values[0] - 1) * 100
    else:
        history_df['KOSPI_Rel'] = (history_df['KOSPI'] / (history_df['KOSPI'].iloc[0] if not history_df['KOSPI'].empty else 1) - 1) * 100

# --- [4. 유연한 열 매칭 세이프가드] ---
def get_col_safe(df, key):
    clean_key = str(key).replace(" ", "").replace("_", "")
    for col in df.columns:
        if clean_key in str(col).replace(" ", "").replace("_", ""):
            return col
    return None

# --- [5. 사이드바 영구 관리 메뉴 (기능 고정)] ---
with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 갱신"): st.cache_data.clear(); st.rerun()
    
    st.divider()
    st.subheader("💾 데이터 저장 (날짜 선택)")
    target_date = st.date_input("저장/확정할 날짜 선택", value=now_kst.date())
    if st.button("선택한 날짜 결과 확정 및 저장"):
        save_ts = pd.Timestamp(target_date)
        m_info = get_market_indices()
        new_row = {c: None for c in history_df.columns}
        new_row.update({"Date": save_ts, "KOSPI": float(m_info.get('KOSPI',{}).get('now','0').replace(',',''))})
        
        acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
        for acc in ['서은투자', '서희투자', '큰스님투자']:
            col = get_col_safe(history_df, f"{acc}수익률")
            if col: new_row[col] = acc_sum.get(acc, 0)
        
        for _, row in full_df.iterrows():
            key = f"{row['계좌명']}_{row['종목명']}수익률"
            col = get_col_safe(history_df, key)
            if col: new_row[col] = row['누적수익률']
            
        update_df = pd.concat([history_df[history_df['Date'] != save_ts], pd.DataFrame([new_row])]).sort_values('Date').reset_index(drop=True)
        conn.update(worksheet="trend", data=update_df)
        st.cache_data.clear(); st.success(f"✅ {target_date} 데이터 저장 완료!"); st.rerun()
        
    st.divider()
    st.subheader("🧹 과거 데이터 정제")
    if not history_df.empty:
        del_date = st.selectbox("삭제할 날짜 선택", history_df['Date'].dt.date.unique())
        if st.button("해당 날짜 데이터 삭제"):
            update_df = history_df[history_df['Date'].dt.date != del_date]
            conn.update(worksheet="trend", data=update_df)
            st.cache_data.clear(); st.warning(f"🗑️ {del_date} 삭제 완료"); st.rerun()

# --- [6. UI 메인 구성] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v36.28</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy = full_df['평가금액'].sum(), full_df['매입금액'].sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("총 누적 손익", f"{t_eval-t_buy:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100:+.2f}%")
    
    st.divider()
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum', '전일대비손익':'sum'}).reset_index()
    sum_acc['누적수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    sum_acc['전일대비변동률'] = (sum_acc['전일대비손익'] / (sum_acc['평가금액'] - sum_acc['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    sum_acc = sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비손익', '전일대비변동률', '누적수익률']]
    st.dataframe(sum_acc.style.apply(lambda row: ['' if i != 2 else ('color: #FF4B4B' if row[2]>row[1] else 'color: #87CEEB') for i, v in enumerate(row)], axis=1).format({
        '매입금액':'{:,.0f}원', '평가금액':'{:,.0f}원', '손익':'{:+,.0f}원', '전일대비변동률':'{:+.2f}%', '누적수익률':'{:+.2f}%'
    }), use_container_width=True, hide_index=True)

    if not history_df.empty:
        fig = go.Figure()
        h_dates = history_df['Date'].dt.date.astype(str)
        fig.add_trace(go.Scatter(x=h_dates, y=history_df['KOSPI_Rel'], name='KOSPI (상대지표)', line=dict(dash='dash', color='gray')))
        for acc in ['서은투자수익률', '서희투자수익률', '큰스님투자수익률']:
            col = get_col_safe(history_df, acc)
            if col: fig.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col, line=dict(width=3)))
        fig.update_layout(title="📈 통합 실제 수익률 추이", yaxis_title="누적수익률 (%)", xaxis=dict(type='category'), height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig, use_container_width=True)

    st.divider(); st.subheader("📊 관심 섹터별 인텔리전스")
    s_cols = st.columns(3)
    sectors = {"반도체 / IT": "HBM 수요 폭발 및 AI 서버 증설 수혜.", "전력 / ESS": "북미 인프라 교체 및 데이터센터 가동 수혜.", "배터리 / 에너지": "전고체 기술 점유율 확대."}
    for i, (n, d) in enumerate(sectors.items()):
        with s_cols[i % 3]: st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><p>{d}</p></div>", unsafe_allow_html=True)

# [투자 주체별 상세 탭]
def render_account_tab(acc_name, tab_obj, history_col_key):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        # 🎯 4대 핵심 지표 (v36.5 원형 복구)
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("평가금액", f"{a_eval:,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        c3.metric("누적손익", f"{a_eval-a_buy:+,.0f}원")
        c4.metric("누적수익률", f"{(a_eval/a_buy-1)*100:+.2f}%")
        
        # 🎯 소수점 없는 정수 포맷
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '전일대비손익', '전일대비변동률', '누적수익률']].style.apply(lambda row: ['' if i != 4 else ('color: #FF4B4B' if row[4]>row[2] else 'color: #87CEEB') for i, v in enumerate(row)], axis=1).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '매입금액': '{:,.0f}원', '현재가': '{:,.0f}원', 
            '평가금액': '{:,.0f}원', '전일대비손익': '{:+,.0f}원', '전일대비변동률': '{:+.2f}%', '누적수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider(); sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        
        # 🎯 기업 딥다이브 리서치 카드
        res = RESEARCH_DATA.get(sel.replace(" ", ""))
        if res:
            rows = "".join([f"<tr><td>{m[0]}</td><td>{m[1]}</td><td class='target-val'>{m[2]}</td></tr>" for m in res['metrics']])
            st.markdown(f"<div class='insight-card'><div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브</div><div class='insight-flex'><div class='insight-left'><table class='research-table'><thead><tr><th>지표</th><th>25년 추정</th><th>26년 Target</th></tr></thead><tbody>{rows}</tbody></table></div><div class='insight-right'>💡 {res['implications'][0]}</div></div></div>", unsafe_allow_html=True)

        g_left, g_right = st.columns([2, 1])
        with g_left:
            if not history_df.empty:
                fig_acc = go.Figure()
                h_dt = history_df['Date'].dt.date.astype(str)
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df['KOSPI_Rel'], name='KOSPI (상대지표)', line=dict(dash='dash', color='gray')))
                
                # 투자 주체 실제 수익률
                col = get_col_safe(history_df, history_col_key)
                if col: fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[col], mode='lines+markers', name=f'{acc_name} 실제수익률', line=dict(width=4)))
                
                # 종목 실제 수익률
                s_key = f"{acc_name}_{sel}수익률"
                s_col = get_col_safe(history_df, s_key)
                if s_col and s_col != col: fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[s_col], mode='lines', name=f'{sel} 실제수익률', line=dict(width=2, dash='dot')))
                
                fig_acc.update_layout(title=f"📈 {acc_name} 성과 추이", yaxis_title="누적수익률(%)", xaxis=dict(type='category'), height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig_acc, use_container_width=True)
        with g_right:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)

        # 하단 리포트 박스 복구
        st.divider(); r_l, r_r = st.columns(2)
        with r_l: st.markdown(f"<div class='report-box'><h4>📋 {acc_name} 계좌 총평</h4><p>Target 달성까지 전략적 보유를 유지합니다.</p></div>", unsafe_allow_html=True)
        with r_r: st.markdown("<div class='report-box'><h4>🌍 업황 대응 전략</h4><p>거시 변동성 대응 모니터링 중입니다.</p></div>", unsafe_allow_html=True)

        acc_news = get_acc_news(sub_df['종목명'].unique().tolist())
        if acc_news:
            news_html = " ".join([f"<div style='margin-bottom:8px;'>[{n['name']}] <a href='{n['url']}' target='_blank' style='color:white; text-decoration:none;'>{n['title']} ↗️</a></div>" for n in acc_news])
            st.markdown(f"<div class='acc-flash-container'>🔔 실시간 뉴스: {news_html}</div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은투자수익률")
render_account_tab("서희투자", tabs[2], "서희투자수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님투자수익률")
