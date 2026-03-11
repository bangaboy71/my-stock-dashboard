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
st.set_page_config(page_title="가족 자산 성장 관제탑 v40.7", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .report-box { padding: 20px; border-radius: 12px; height: 210px; overflow-y: auto; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.02); line-height: 1.6; }
    .target-val { color: #FFD700; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 엔진 및 데이터 정의] ---

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

def get_market_status():
    data = {
        "KOSPI": {"val": "-", "diff": "0.00", "pct": "0.00%", "color": "white"},
        "KOSDAQ": {"val": "-", "diff": "0.00", "pct": "0.00%", "color": "white"},
        "USD/KRW": {"val": "-", "diff": "0.00", "pct": "원", "color": "white"},
        "VOLUME": {"val": "-", "diff": "KOSPI", "pct": "천주", "color": "white"}
    }
    header = {'User-Agent': 'Mozilla/5.0'}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            res = requests.get(f"https://finance.naver.com/sise/sise_index.naver?code={code}", headers=header, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            now_el = soup.select_one("#now_value")
            if now_el:
                now_val = float(now_el.get_text(strip=True).replace(',', ''))
                data[code]["val"] = f"{now_val:,.2f}"
        # 환율
        ex_res = requests.get("https://finance.naver.com/marketindex/", headers=header, timeout=3)
        ex_soup = BeautifulSoup(ex_res.text, 'html.parser')
        ex_val_el = ex_soup.select_one("span.value")
        if ex_val_el: data["USD/KRW"]["val"] = ex_val_el.get_text(strip=True)
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

def find_matching_col(df, account, stock=None):
    prefix = account.replace("투자", "").replace(" ", "")
    target = f"{prefix}{stock}수익률" if stock else f"{prefix}수익률"
    target_clean = target.replace(" ", "").replace("_", "")
    for col in df.columns:
        if target_clean == str(col).replace(" ", "").replace("_", "").replace("투자", ""): return col
    return None

# --- [3. 데이터 로드 및 정제: v40.7 통합 엔진] ---
def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    full_df = conn.read(worksheet="종목 현황", ttl="1m")
    history_df = conn.read(worksheet="trend", ttl=0)
except Exception as e:
    st.error(f"⚠️ 연결 오류: {e}"); st.stop()

if not full_df.empty:
    full_df.columns = [c.strip() for c in full_df.columns]
    # 수치형 변환 (목표가 포함)
    num_cols = ['수량', '매입단가', '52주최고가', '매입후최고가', '목표가']
    for c in num_cols:
        if c in full_df.columns:
            full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        elif c == '목표가': full_df['목표가'] = 0

    # 실시간 데이터 및 수익 지표 연산
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비변동율'] = (full_df['전일대비손익'] / (full_df['평가금액'] - full_df['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    
    # 상승여력 및 보유일수
    full_df['목표대비상승여력'] = full_df.apply(lambda x: ((x['목표가']/x['현재가']-1)*100) if x['현재가']>0 and x['목표가']>0 else 0, axis=1)
    if '최초매입일' in full_df.columns:
        full_df['최초매입일'] = pd.to_datetime(full_df['최초매입일'], errors='coerce')
        full_df['보유일수'] = (datetime.now().replace(hour=0,minute=0,second=0,microsecond=0) - full_df['최초매입일'].dt.tz_localize(None)).dt.days.fillna(365).astype(int).clip(lower=1)
    else: full_df['보유일수'] = 365

# --- [4. UI 메인 섹션] ---
st.markdown(f"<h2 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v40.7</h2>", unsafe_allow_html=True)

m_status = get_market_status()
hud_cols = st.columns(4)
titles = ["KOSPI", "KOSDAQ", "USD/KRW", "MARKET VOL"]
keys = ["KOSPI", "KOSDAQ", "USD/KRW", "VOLUME"]
for i, col in enumerate(hud_cols):
    with col:
        d = m_status[keys[i]]
        st.markdown(f"<div style='text-align: center; padding: 10px; background: rgba(255,255,255,0.03); border-radius: 10px;'><b>{titles[i]}</b><br><span style='font-size: 1.5rem;'>{d['val']}</span></div>", unsafe_allow_html=True)

tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    t_eval, t_buy = full_df['평가금액'].sum(), full_df['매입금액'].sum()
    st.columns(4)[0].metric("가족 총 평가액", f"{t_eval:,.0f}원")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum', '전일대비손익':'sum'}).reset_index()
    st.dataframe(sum_acc, use_container_width=True, hide_index=True)

# [Tab 1-3] 투자별 상세
def render_account_tab(acc_name, tab_obj, history_col_key):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        # 상단 메트릭
        a_eval, a_buy = sub_df['평가금액'].sum(), sub_df['매입금액'].sum()
        st.columns(4)[0].metric(f"{acc_name} 평가액", f"{a_eval:,.0f}원")
        
        # 1. v36.50 원본 스타일 테이블 (10개 컬럼)
        display_cols = ['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '손익', '전일대비손익', '전일대비변동율', '누적수익률']
        st.dataframe(sub_df[display_cols].style.format({
            '매입단가': '{:,.0f}', '매입금액': '{:,.0f}', '현재가': '{:,.0f}', '평가금액': '{:,.0f}', 
            '손익': '{:+,.0f}', '전일대비손익': '{:+,.0f}', '전일대비변동율': '{:+.2f}%', '누적수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)

        st.divider()
        sel = st.selectbox(f"📍 {acc_name} 종목 분석", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        s_row = sub_df[sub_df['종목명'] == sel].iloc[0]
        
        # 변수 계산
        curr_p, buy_p, target_p = float(s_row['현재가']), float(s_row['매입단가']), float(s_row.get('목표가', 0))
        post_high = float(s_row.get('매입후최고가', curr_p))
        ann_ret = ((1 + float(s_row['누적수익률'])/100)**(365/max(int(s_row['보유일수']),1)) - 1) * 100
        
        # 2. [중앙] 인텔리전스 | 전략 모니터 (트리플 지표 1.2rem)
        c_res, c_strat = st.columns(2)
        with c_res:
            res = RESEARCH_DATA.get(sel.replace(" ", ""))
            if res:
                metrics_html = "".join([f"<tr><td>{m[0]}</td><td style='text-align:right;'>{m[1]} → <span style='color:#FFD700;'>{m[2]}</span></td></tr>" for m in res['metrics']])
                st.markdown(f"<div class='report-box'>📋 <b>핵심 지표</b><table style='width:100%'>{metrics_html}</table></div>", unsafe_allow_html=True)
        
        with c_strat:
            st.markdown(f"""
                <div style='background: rgba(135,206,235,0.05); padding: 15px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.2); height: 210px; text-align: center;'>
                    <div style='display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px;'>
                        <div><small>연 환산</small><br><b style='font-size: 1.2rem; color: #FF4B4B;'>{ann_ret:+.1f}%</b></div>
                        <div style='border-left: 1px solid #444; border-right: 1px solid #444;'><small style='color:#FFD700;'>시트 목표가</small><br><b style='font-size: 1.2rem; color: #FFD700;'>{target_p:,.0f}</b></div>
                        <div><small>상승 여력</small><br><b style='font-size: 1.2rem; color: #00FF00;'>{s_row['목표대비상승여력']:+.1f}%</b></div>
                    </div>
                    <div style='margin-top: 25px; font-size: 0.9rem; color: #aaa;'>현재가: {curr_p:,.0f}원 / 52주 최고: {s_row.get('52주최고가', 0):,.0f}원</div>
                </div>
            """, unsafe_allow_html=True)

        # 3. [하단] 리스크 경보 (단일 표시)
        sl_price, tp_price = buy_p * 0.85, post_high * 0.80
        st.markdown(f"""
            <div style='background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; border: 1px solid {"#FF4B4B" if curr_p <= sl_price else "rgba(255,255,255,0.1)"}; margin-top: 15px;'>
                <div style='display: flex; justify-content: space-between; font-size: 0.95rem;'>
                    <span>🛡️ <b>손절 (-15%):</b> {sl_price:,.0f}원 <small>(매입 {buy_p:,.0f} 대비)</small></span>
                    <span style='color: {"#FF4B4B" if curr_p <= sl_price else "#00FF00"}; font-weight: bold;'>{"⚠️ 즉시 대응" if curr_p <= sl_price else "✅ 매우 안전"}</span>
                </div>
                <div style='display: flex; justify-content: space-between; font-size: 0.95rem; margin-top: 8px;'>
                    <span>🚨 <b>익절 (-20%):</b> {tp_price:,.0f}원 <small>(최고 {post_high:,.0f} 대비)</small></span>
                    <span style='color: {"#FFA500" if curr_p <= tp_price else "#00FF00"}; font-weight: bold;'>{"⚠️ 추세 이탈" if curr_p <= tp_price else "✅ 추세 유지"}</span>
                </div>
            </div>
        """, unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
    # (이하 기존 v38.9 기록 관리자 모드 로직 유지)
    st.divider()
    sel_date = st.date_input("결과 저장 날짜", value=datetime.now())
   
# --- [v38.9 패치: st.form 기반 버튼 고정 시스템] ---
    st.sidebar.header("⚙️ 기록 관리자 모드")
    sel_date = st.sidebar.date_input("📅 저장/복구 날짜 선택", value=datetime.now())
    
    # 1. 데이터 불러오기 버튼
    if st.sidebar.button(f"🔍 {sel_date} 데이터 불러오기"):
        save_date_str = sel_date.strftime('%Y-%m-%d')
        st.session_state['edit_kospi'] = 5251.87 if save_date_str == "2026-03-09" else float(m_status["KOSPI"]["val"].replace(",",""))
        
        # 3월 9일 팩트 수치 세션 저장
        tmp_p = {}
        for _, r in full_df.iterrows():
            name = r['종목명']
            if save_date_str == "2026-03-09":
                if "KODEX" in name and "위클리" in name: tmp_p[name] = 16515.0
                elif "삼성전자" in name: tmp_p[name] = 111400.0
                else: tmp_p[name] = float(r['현재가'])
            else:
                tmp_p[name] = float(r['현재가'])
        
        st.session_state['edit_prices'] = tmp_p
        st.session_state['editor_active'] = True
        st.sidebar.success("✅ 데이터를 가져왔습니다. 아래 양식을 확인하세요.")

    # 2. 고정형 입력 폼 (st.form 사용)
    if st.session_state.get('editor_active', False):
        with st.sidebar.form(key='record_form'):
            st.subheader(f"🛠️ {sel_date} 수치 확정")
            
            # KOSPI 지수 입력
            f_kospi = st.number_input("KOSPI 지수", value=st.session_state['edit_kospi'], format="%.2f")
            
            # 종목별 종가 입력 (리스트가 길어도 폼 안에 묶입니다)
            f_prices = {}
            for name, p_val in st.session_state['edit_prices'].items():
                f_prices[name] = st.number_input(f"{name}", value=p_val, format="%.0f")
            
            # 🎯 [핵심] 폼 내부의 제출 버튼 (가장 아래에 고정됩니다)
            submit_button = st.form_submit_button(label="🚀 위 수치로 시트 최종 기록")
            
            if submit_button:
                try:
                    save_date_str = sel_date.strftime('%Y-%m-%d')
                    new_entry = pd.Series(index=history_df.columns, dtype='object')
                    new_entry['Date'] = save_date_str
                    if '날짜' in new_entry.index: new_entry['날짜'] = save_date_str
                    new_entry['KOSPI'] = f_kospi

                    # 수익률 계산 및 행 구성
                    for acc in full_df['계좌명'].unique():
                        acc_df = full_df[full_df['계좌명'] == acc]
                        acc_eval_sum = 0.0
                        acc_buy_total = float(acc_df['매입금액'].sum())
                        
                        for _, r in acc_df.iterrows():
                            t_price = f_prices[r['종목명']]
                            buy_p = float(r['매입단가'])
                            
                            s_col = find_matching_col(history_df, acc, r['종목명'])
                            if s_col: new_entry[s_col] = ((t_price / buy_p) - 1) * 100
                            acc_eval_sum += (t_price * float(r['수량']))

                        a_col = find_matching_col(history_df, acc)
                        if a_col: new_entry[a_col] = ((acc_eval_sum / acc_buy_total) - 1) * 100

                    # 시트 업데이트
                    hist_copy = history_df.copy()
                    hist_copy['Date'] = pd.to_datetime(hist_copy['Date']).dt.strftime('%Y-%m-%d')
                    updated_df = pd.concat([hist_copy[hist_copy['Date'] != save_date_str], pd.DataFrame([new_entry])], ignore_index=True)
                    
                    conn.update(worksheet="trend", data=updated_df.sort_values('Date').reset_index(drop=True))
                    st.success("✅ 시트 기록 성공!")
                    st.session_state['editor_active'] = False
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 오류: {e}")
                    
st.caption(f"v36.50 가디언 레질리언스 | {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")






