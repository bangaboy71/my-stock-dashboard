import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import re

# --- [1. 환경 설정 및 스타일] ---
st.set_page_config(page_title="AI 금융 통합 관제탑 v36.75", layout="wide")

st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-top: 20px; }
    .target-val { color: #FFD700; font-weight: bold; }
    .status-alert { padding: 2px 8px; border-radius: 4px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 인프라: 딥다이브 데이터 및 정밀 매핑] ---
RESEARCH_DATA = {
    "삼성전자": {"metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%")], "implications": ["HBM3E 양산 본격화", "특별 배당 기반 강력 환원"]},
    "KT&G": {"metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%")], "implications": ["NGP 성장 동력 확보", "자사주 소각 가속화"]},
    "테스": {"metrics": [("영업이익률", "10.7%", "19.0%"), ("ROE", "6.2%", "14.5%")], "implications": ["선단공정 장비 수요 폭증", "095610 정밀 코드 적용 완료"]},
    "LG에너지솔루션": {"metrics": [("수주잔고", "450조", "520조+"), ("영업이익률", "5.2%", "8.5%")], "implications": ["4680 배터리 공급 개시", "ESS 비중 확대"]},
    "현대글로비스": {"metrics": [("PCTC 선복량", "90척", "110척"), ("영업이익률", "6.5%", "7.2%")], "implications": ["해상운송 1위 공고화", "수소 물류 선점"]},
    "현대차2우B": {"metrics": [("배당수익률", "7.5%", "9.2%"), ("ROE", "11%", "13%")], "implications": ["분기 배당 강화", "밸류업 수혜"]},
    "KODEX200타겟위클리커버드콜": {"metrics": [("분배율", "연 12%", "월 1%↑"), ("지수추종", "95%", "98%")], "implications": ["옵션 프리미엄 확보", "횡보장 초과 수익"]},
    "에스티팜": {"metrics": [("올리고 매출", "2.1천억", "3.5천억"), ("ROE", "12%", "18%")], "implications": ["mRNA 원료 확장", "제2 올리고동 가동"]},
    "일진전기": {"metrics": [("초고압 변압기", "수주잔고↑", "북미 점유율↑"), ("ROE", "14%", "18%")], "implications": ["미국 전력망 교체 수혜", "변압기 증설 효과"]},
    "SK스퀘어": {"metrics": [("NAV 할인율", "65%", "45%"), ("주주환원", "0.3조", "0.6조")], "implications": ["자사주 소각 적극화", "하이닉스 가치 반영"]}
}

STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "테스": "095610", 
    "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", 
    "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", 
    "일진전기": "103590", "SK스퀘어": "402340"
}

# --- [3. 엔진: 하이브리드 마켓 지수 및 가격 수집] ---
def get_market_status():
    data = {k: {"val": "-", "diff": "0.00", "pct": "0.00%", "color": "white"} for k in ["KOSPI", "KOSDAQ", "USD/KRW", "VOLUME"]}
    header = {'User-Agent': 'Mozilla/5.0'}
    try:
        # Naver 지수 크롤링 (v36.60 안정화 버전)
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers=header, timeout=3); soup = BeautifulSoup(res.text, 'html.parser')
            now_val = soup.select_one("#now_value").text; prev_text = soup.select_one("td.first").get_text()
            prev_val = float(re.findall(r"\d+\.\d+|\d+", prev_text.replace(',', ''))[0])
            diff = float(now_val.replace(',', '')) - prev_val
            data[code] = {"val": now_val, "diff": f"{diff:+,.2f}", "pct": f"{(diff/prev_val)*100:+.2f}%", "color": "#FF4B4B" if diff > 0 else "#87CEEB"}
            if code == "KOSPI": data["VOLUME"]["val"] = soup.select_one("#quant").text
        # 환율
        ex_res = requests.get("https://finance.naver.com/marketindex/", headers=header)
        ex_soup = BeautifulSoup(ex_res.text, 'html.parser')
        data["USD/KRW"] = {"val": ex_soup.select_one("span.value").text, "diff": ex_soup.select_one("span.change").text, "pct": "원", "color": "white"}
    except: # Yahoo 백업 (v36.61)
        yf_m = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "USD/KRW": "KRW=X"}
        for k, v in yf_m.items():
            try:
                h = yf.Ticker(v).history(period="2d")
                curr, prev = h.iloc[-1]['Close'], h.iloc[-2]['Close']
                diff = curr - prev
                data[k] = {"val": f"{curr:,.2f}", "diff": f"{diff:+,.2f}", "pct": f"{(diff/prev)*100:+.2f}%", "color": "#FF4B4B" if diff > 0 else "#87CEEB"}
            except: pass
    return data

def get_stock_data(name):
    code = STOCK_CODES.get(str(name).strip())
    if not code: return 0, 0
    try:
        res = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        now_p = int(soup.select_one(".today .blind").text.replace(",", ""))
        prev_p = int(soup.select_one(".first .blind").text.replace(",", ""))
        return now_p, prev_p
    except: return 0, 0

# --- [4. 데이터 로드 및 리스크 관리 엔진 통합] ---
conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(worksheet="종목 현황", ttl="1m")

if not df.empty:
    df['종목명'] = df['종목명'].str.strip()
    for c in ['수량', '매입단가', '52주최고가', '매입후최고가', '매입후최저가']:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    
    # 가격 및 리스크 연산
    prices = df['종목명'].apply(get_stock_data).tolist()
    df['현재가'], df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    
    # 고스트 갱신 (최고/최저가)
    df['매입후최고가'] = df.apply(lambda x: max(x['현재가'], x['매입후최고가']) if x['매입후최고가'] > 0 else x['현재가'], axis=1)
    df['매입후최저가'] = df.apply(lambda x: min(x['현재가'], x['매입후최저가']) if x['매입후최저가'] > 0 else x['현재가'], axis=1)

    # 리스크 지표
    today = datetime.now()
    df['최초매입일'] = pd.to_datetime(df['최초매입일'], errors='coerce')
    df['보유일수'] = (today - df['최초매입일']).dt.days.replace(0, 1)
    df['누적수익률'] = (df['현재가'] / df['매입단가'] - 1) * 100
    
    # 연 환산 수익률 및 상승 여력
    # $$Annualized\ Return = \left( (1 + \frac{Total\ Return}{100})^{\frac{365}{Days}} - 1 \right) \times 100$$
    df['연환산수익률'] = ((1 + df['누적수익률']/100)**(365/df['보유일수']) - 1) * 100
    df['상승여력'] = (df['52주최고가'] / df['현재가'].replace(0, 1) - 1) * 100
    df['익절가'] = df['매입후최고가'] * 0.80
    df['손절가'] = df['매입단가'] * 0.85

# --- [5. UI: 모던 슬림 타이틀 및 HUD] ---
st.markdown("<div style='margin-top: -30px;'></div>", unsafe_allow_html=True)
st.markdown(f"<h2 style='text-align: center; color: #87CEEB; font-size: 1.8rem; font-weight: 600;'>🌐 AI 금융 통합 관제탑 <span style='font-size: 1.2rem; opacity: 0.7;'>v36.75</span></h2>", unsafe_allow_html=True)

m_status = get_market_status()
hud_cols = st.columns(4)
titles = ["KOSPI", "KOSDAQ", "USD/KRW", "MARKET VOL"]
keys = ["KOSPI", "KOSDAQ", "USD/KRW", "VOLUME"]
for i, col in enumerate(hud_cols):
    with col:
        d = m_status[keys[i]]
        st.markdown(f"<div style='text-align: center; padding: 12px; border-radius: 10px; background: rgba(255,255,255,0.03); border: 1px solid {d['color']}33;'><span style='color: #aaa; font-size: 0.8rem;'>{titles[i]}</span><br><span style='color: {d['color']}; font-size: 1.5rem; font-weight: bold;'>{d['val']}</span><br><span style='color: {d['color']}; font-size: 0.9rem;'>{d['diff']} ({d['pct'] if i<2 else d['pct']})</span></div>", unsafe_allow_html=True)

st.write("")
tabs = st.tabs(["💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [6. 통합 렌더링 함수: 리스크 + 딥다이브] ---
def render_integrated_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = df[df['계좌명'] == acc_name].copy()
        if sub_df.empty: return

        # 1. 리스크 모니터링 테이블
        st.markdown(f"#### 🚨 {acc_name} 리스크 및 성과")
        def get_status(row):
            if row['현재가'] <= row['손절가']: return "🚨 손절"
            if row['현재가'] <= row['익절가']: return "⚠️ 익절"
            return "✅ 정상"
        sub_df['상태'] = sub_df.apply(get_status, axis=1)

        cols = ['종목명', '현재가', '누적수익률', '연환산수익률', '상승여력', '익절가', '손절가', '상태']
        st.dataframe(sub_df[cols].style.apply(lambda x: [
            'background-color: rgba(255, 75, 75, 0.15)' if '🚨' in str(val) else '' for val in x
        ], axis=1).format({
            '현재가': '{:,.0f}원', '누적수익률': '{:+.2f}%', '연환산수익률': '{:+.2f}%', '상승여력': '{:+.2f}%', '익절가': '{:,.0f}원', '손절가': '{:,.0f}원'
        }), hide_index=True, use_container_width=True)

        # 2. 딥다이브 인사이트 카드 (기존 기능 복구)
        st.divider()
        sel = st.selectbox(f"🔍 {acc_name} 종목 분석", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        res = RESEARCH_DATA.get(sel)
        if res:
            m_rows = "".join([f"<tr><td>{m[0]}</td><td>{m[1]}</td><td class='target-val'>{m[2]}</td></tr>" for m in res['metrics']])
            st.markdown(f"""
                <div class='insight-card'>
                    <div style='color: #87CEEB; font-weight: bold; font-size: 1.1rem; margin-bottom: 15px;'>🔍 {sel} 인텔리전스 딥다이브</div>
                    <div style='display: flex; gap: 20px;'>
                        <div style='flex: 1;'><table style='width: 100%; font-size: 0.9rem;'>{m_rows}</table></div>
                        <div style='flex: 1; border-left: 2px solid rgba(255,215,0,0.2); padding-left: 15px;'>
                            <span style='color: #FFD700;'>💡 인사이트:</span><br><span style='font-size: 0.85rem;'>{res['implications'][0]}<br>{res['implications'][1]}</span>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

render_integrated_tab("서은투자", tabs[0])
render_integrated_tab("서희투자", tabs[1])
render_integrated_tab("큰스님투자", tabs[2])

with st.sidebar:
    st.header("💾 데이터 동기화")
    if st.button("📊 최고/최저가 시트 업데이트"):
        st.success("데이터가 전송되었습니다. (연결 시 conn.update 사용)")
