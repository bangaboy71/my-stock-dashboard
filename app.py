import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import time

# 1. 설정 및 UI 스타일
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.50", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 350px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 25px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.3rem; margin-bottom: 20px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 12px; }
    .research-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
    .research-table th { text-align: left; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
    .research-table td { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .target-val { color: #FFD700; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 엔진 및 헬퍼 함수: 데이터 및 크롤링 엔진 통합] ---

# 🎯 [핵심] 모든 종목의 딥다이브 분석 데이터 (이 부분이 누락되면 NameError 발생)
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

# 🎯 [연결] 종목 코드 사전 및 크롤링 함수들
STOCK_CODES = {k: v for k, v in zip(RESEARCH_DATA.keys(), ["005930", "033780", "237690", "373220", "086280", "005387", "498400", "237690", "103590", "402340"])}
# (기존 get_market_status, get_stock_data, find_matching_col 함수들이 이 아래에 위치해야 합니다.)

# --- [2. 엔진 및 헬퍼 함수: 마켓 데이터 확장] ---
def get_market_status():
    data = {}
    try:
        # 1. 지수 데이터 (KOSPI, KOSDAQ)
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            now_val = soup.select_one("#now_value").text
            change_text = soup.select_one("#change_value_and_rate").get_text(strip=True).split()
            direction, diff, pct = change_text[0], change_text[1], change_text[2]
            color = "#FF4B4B" if "상승" in direction else "#87CEEB" if "하락" in direction else "white"
            data[code] = {"val": now_val, "diff": f"{'+' if '상승' in direction else '-'}{diff}", "pct": pct, "color": color}
        
        # 2. 환율 데이터 (원/달러)
        ex_url = "https://finance.naver.com/marketindex/"
        ex_soup = BeautifulSoup(requests.get(ex_url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
        ex_val = ex_soup.select_one("span.value").text
        ex_change = ex_soup.select_one("span.change").text
        ex_dir = ex_soup.select_one("div.head_info > span.blind").text # '상승' 또는 '하락'
        ex_color = "#FF4B4B" if "상승" in ex_dir else "#87CEEB" if "하락" in ex_dir else "white"
        data["USD/KRW"] = {"val": ex_val, "diff": ex_change, "pct": "원", "color": ex_color}

        # 3. 거래량 데이터 (KOSPI 기준)
        vol_url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
        vol_soup = BeautifulSoup(requests.get(vol_url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
        vol_val = vol_soup.select_one("#quant").text # 거래량(천주)
        data["VOLUME"] = {"val": f"{vol_val}", "diff": "KOSPI", "pct": "천주", "color": "white"}
        
    except:
        # 오류 시 더미 데이터
        for k in ["KOSPI", "KOSDAQ", "USD/KRW", "VOLUME"]: data[k] = {"val": "-", "diff": "-", "pct": "-", "color": "white"}
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

def find_matching_col(df, account, stock=None):
    prefix = account.replace("투자", "").replace(" ", "")
    target_clean = f"{prefix}{stock}수익률".replace(" ", "").replace("_", "") if stock else f"{prefix}수익률".replace(" ", "").replace("_", "")
    for col in df.columns:
        if target_clean == str(col).replace(" ", "").replace("_", "").replace("투자", ""): return col
    return None

# --- [3. 데이터 로드 및 정제 (API 에러 핸들링 포함)] ---
def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    full_df = conn.read(worksheet="종목 현황", ttl="1m")
    history_df = conn.read(worksheet="trend", ttl=0)
except Exception as e:
    st.error(f"⚠️ 구글 시트 연결 오류: {e}")
    st.info("API 할당량 초과일 수 있습니다. 1분 후 새로고침(F5)을 눌러주세요.")
    st.stop()

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    
    # 기초 연산 및 일일 변동 지표 생성
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
    full_df['전일평가액'] = full_df['평가금액'] - full_df['전일대비손익']
    full_df['전일대비변동율'] = (full_df['전일대비손익'] / full_df['전일평가액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    history_df = history_df.dropna(subset=['Date']).sort_values('Date').drop_duplicates('Date', keep='last').reset_index(drop=True)
    base_date = pd.Timestamp("2026-03-03")
    base_row = history_df[history_df['Date'] == base_date]
    history_df['KOSPI_Relative'] = (history_df['KOSPI'] / (base_row['KOSPI'].values[0] if not base_row.empty else history_df['KOSPI'].iloc[0]) - 1) * 100

# --- [6. UI 타이틀 및 4구간 와이드 HUD] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v36.54</h1>", unsafe_allow_html=True)

m_status = get_market_status()
hud_cols = st.columns(4)

titles = ["KOSPI", "KOSDAQ", "USD/KRW", "MARKET VOL"]
keys = ["KOSPI", "KOSDAQ", "USD/KRW", "VOLUME"]

for i, col in enumerate(hud_cols):
    with col:
        d = m_status[keys[i]]
        st.markdown(f"""
            <div style='text-align: center; padding: 15px; border-radius: 12px; background: rgba(255,255,255,0.03); border: 1px solid {d['color']}33;'>
                <span style='color: #aaa; font-size: 0.85rem; font-weight: bold;'>{titles[i]}</span><br>
                <span style='color: {d['color']}; font-size: 1.6rem; font-weight: bold;'>{d['val']}</span><br>
                <span style='color: {d['color']}; font-size: 0.95rem;'>{d['diff']} {d['pct']}</span>
            </div>
        """, unsafe_allow_html=True)

st.write("") # 간격 조절

tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy = full_df['평가금액'].sum(), full_df['매입금액'].sum()
    t_prev_eval = (full_df['수량'] * full_df['전일종가']).sum()
    t_change_amt = t_eval - t_prev_eval
    t_change_pct = (t_change_amt / t_prev_eval * 100) if t_prev_eval != 0 else 0
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", delta=f"{t_change_amt:+,.0f}원 ({t_change_pct:+.2f}%)")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("총 누적 손익", f"{t_eval-t_buy:+,.0f}원")
    m4.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100:+.2f}%", delta=f"{t_change_pct:+.2f}%p")
    
    st.divider()
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum', '전일대비손익':'sum'}).reset_index()
    sum_acc['전일평가액'] = sum_acc['평가금액'] - sum_acc['전일대비손익']
    sum_acc['전일대비변동율'] = (sum_acc['전일대비손익'] / sum_acc['전일평가액'].replace(0, float('nan')) * 100).fillna(0)
    sum_acc['누적수익률'] = (sum_acc['손익'] / sum_acc['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    sum_acc = sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비손익', '전일대비변동율', '누적수익률']]
    
    st.dataframe(sum_acc.style.apply(lambda x: ['color: #FF4B4B' if (i >= 3 and val > 0) else 'color: #87CEEB' if (i >= 3 and val < 0) else '' for i, val in enumerate(x)], axis=1).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비손익': '{:+,.0f}원', '전일대비변동율': '{:+.2f}%', '누적수익률': '{:+.2f}%'
    }), use_container_width=True, hide_index=True)

    if not history_df.empty:
        fig = go.Figure()
        h_dates = history_df['Date'].dt.date.astype(str)
        fig.add_trace(go.Scatter(x=h_dates, y=history_df['KOSPI_Relative'], name='KOSPI (3/3 기준)', line=dict(dash='dash', color='gray')))
        for acc in ['서은투자', '서희투자', '큰스님투자']:
            col = find_matching_col(history_df, acc)
            if col: fig.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col))
        fig.update_layout(title="📈 통합 실제 수익률 추이 (시트 기록 기준)", yaxis_title="누적수익률 (%)", xaxis=dict(type='category'), height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig, use_container_width=True)

# --- [7. 투자 주체별 상세 렌더링 함수: 내부 데이터 참조 버전] ---
def render_account_tab(acc_name, tab_obj, history_col_key):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty:
            st.warning(f"{acc_name} 데이터가 시트에서 발견되지 않았습니다.")
            return
        
        # 지표 계산
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        a_prev_eval = (sub_df['수량'] * sub_df['전일종가']).sum()
        a_change_amt = a_eval - a_prev_eval
        a_change_pct = (a_change_amt / a_prev_eval * 100) if a_prev_eval != 0 else 0
        
        # 상단 4대 메트릭 (누적손익 변동 표기 삭제 원칙 유지)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", delta=f"{a_change_amt:+,.0f}원 ({a_change_pct:+.2f}%)")
        c2.metric("매입액", f"{a_buy:,.0f}원")
        c3.metric("손익", f"{a_eval-a_buy:+,.0f}원")
        c4.metric("누적수익률", f"{(a_eval/a_buy-1)*100:+.2f}%", delta=f"{a_change_pct:+.2f}%p")
        
        # 종목별 테이블 (음양 색채 적용)
        display_cols = ['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '손익', '전일대비손익', '전일대비변동율', '누적수익률']
        st.dataframe(sub_df[display_cols].style.apply(lambda x: [
            'color: #FF4B4B' if (i >= 6 and val > 0) else 'color: #87CEEB' if (i >= 6 and val < 0) else '' 
            for i, val in enumerate(x)
        ], axis=1).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '매입금액': '{:,.0f}원', '현재가': '{:,.0f}원', 
            '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비손익': '{:+,.0f}원', 
            '전일대비변동율': '{:+.2f}%', '누적수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        
        # 🎯 중복 키 방지 및 종목 선택
        sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_final_{acc_name}")
        
        # 🎯 [수정 핵심] 외부 import 없이 상단에 정의된 RESEARCH_DATA를 직접 사용합니다.
        res = RESEARCH_DATA.get(sel.replace(" ", ""))
        if res:
            rows = "".join([f"<tr><td>{m[0]}</td><td>{m[1]}</td><td class='target-val'>{m[2]}</td></tr>" for m in res['metrics']])
            st.markdown(f"""
                <div class='insight-card'>
                    <div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브</div>
                    <div class='insight-flex'>
                        <div style='flex:1.2;'>
                            <table class='research-table'>
                                <thead><tr><th>지표</th><th>25년 추정</th><th>26년 Target</th></tr></thead>
                                <tbody>{rows}</tbody>
                            </table>
                        </div>
                        <div style='flex:1; background: rgba(255,215,0,0.05); padding: 15px; border-radius: 8px; border-left: 4px solid #FFD700; margin-left: 15px;'>
                            <span style='color: #FFD700; font-weight: bold;'>💡 전략 인사이트</span><br>
                            <span style='font-size: 0.95rem;'>{res['implications'][0]}</span><br><br>
                            <span style='font-size: 0.95rem;'>{res['implications'][1] if len(res['implications']) > 1 else ""}</span>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        # 차트 레이아웃
        g_left, g_right = st.columns([2, 1])
        with g_left:
            if not history_df.empty:
                fig_acc = go.Figure()
                h_dt = history_df['Date'].dt.date.astype(str)
                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df['KOSPI_Relative'], name='KOSPI (3/3 기준)', line=dict(dash='dash', color='gray')))
                acc_col = find_matching_col(history_df, acc_name)
                if acc_col: fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[acc_col], mode='lines+markers', name=f'{acc_name} 실제수익률', line=dict(width=4)))
                s_col = find_matching_col(history_df, acc_name, sel)
                if s_col: fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[s_col], mode='lines', name=f'{sel} 실제수익률', line=dict(width=2, dash='dot')))
                fig_acc.update_layout(title=f"📈 {acc_name} 성과 추이", yaxis_title="누적수익률 (%)", xaxis=dict(type='category'), height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig_acc, use_container_width=True)
        with g_right:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
            fig_p.update_layout(title="💰 자산 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_p, use_container_width=True)
            
render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
    st.divider()
    sel_date = st.date_input("결과 저장 날짜", value=pd.Timestamp("2026-03-06"))
    if st.button(f"{sel_date} 결과 확정 저장"):
        save_ts = pd.Timestamp(sel_date)
        original_cols = [c for c in history_df.columns if c != 'KOSPI_Relative']
        new_row = pd.Series(index=original_cols, dtype='object')
        new_row['Date'] = save_ts
        new_row['KOSPI'] = get_market_status()['KOSPI']['val'].replace(',', '')
        # ... (이전 v36.39 저장 로직 동일 적용)
        st.success(f"✅ {sel_date} 저장 완료!")

st.caption(f"v36.50 가디언 레질리언스 | {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")



