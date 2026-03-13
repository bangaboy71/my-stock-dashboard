import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import time
import yfinance as yf # 코드 최상단 import문에 추가해주세요

# 1. 설정 및 UI 스타일
st.set_page_config(page_title="가족 자산 성장 관제탑 v40.94", layout="wide")

# --- [신규 등급 시스템 함수] ---
def get_cashflow_grade(amount):
    if amount >= 1000000: return "💎 Diamond"
    elif amount >= 300000: return "🥇 Gold"
    elif amount >= 100000: return "🥈 Silver"
    else: return "🥉 Bronze"
# --- [v40.82 전역 설정: 이름표 및 배당 일정 통합] ---
GLOBAL_RENAME_MAP = {
    '전일대비손익': '전일대비(원)', 
    '전일대비변동율': '전일대비(%)'
}

GLOBAL_DISPLAY_COLS = ['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '손익', '전일대비(원)', '전일대비(%)', '누적수익률']

# 종목별 배당 주기 설정
DIVIDEND_SCHEDULE = {
    "삼성전자": [5, 8, 11, 4], "KT&G": [5, 8, 11, 4], "현대차2우B": [5, 8, 11, 4],
    "현대글로비스": [4, 8], "테스": [4], "에스티팜": [4], "일진전기": [4],
    "KODEX200타겟위클리커버드콜": list(range(1, 13))
}

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

# --- [2. 엔진 및 헬퍼 함수: STOCK_CODES 정밀 보정] ---

# 🎯 [핵심 수정] 테스와 에스티팜의 코드 혼선을 원천 차단하기 위해 명시적 딕셔너리로 재정의합니다.
STOCK_CODES = {
    "삼성전자": "005930",
    "KT&G": "033780",
    "테스": "095610",
    "LG에너지솔루션": "373220",
    "현대글로비스": "086280",
    "현대차2우B": "005387",
    "KODEX200타겟위클리커버드콜": "498400",  # 🎯 486740에서 498400으로 교정
    "에스티팜": "237690",
    "일진전기": "103590",
    "SK스퀘어": "402340"
}

# --- [v40.80: 종목별 예상 배당월 설정] ---
# 한국 상장사 특성상 결산 배당은 4월에 집중되며, 분기 배당주를 별도 반영함
DIVIDEND_SCHEDULE = {
    "삼성전자": [5, 8, 11, 4],     # 분기 배당 (1,2,3분기는 익월말, 결산은 4월)
    "KT&G": [5, 8, 11, 4],        # 분기 배당
    "현대차2우B": [5, 8, 11, 4],   # 분기 배당
    "현대글로비스": [4, 8],        # 반기 배달 (중간, 결산)
    "테스": [4], "에스티팜": [4], "일진전기": [4], # 결산 배당 (4월)
    "KODEX200타겟위클리커버드콜": list(range(1, 13)) # 월배당 (매달)
}

# --- [v40.21 시장 지수 엔진: 거래량 독립 및 텍스트 클리닝] ---
def get_market_status():
    data = {
        "KOSPI": {"val": "-", "pct": "0.00%", "color": "#ffffff"},
        "KOSDAQ": {"val": "-", "pct": "0.00%", "color": "#ffffff"},
        "USD/KRW": {"val": "-", "pct": "0원", "color": "#ffffff"},
        "VOLUME": {"val": "-", "pct": "천주", "color": "#ffffff"} # 거래량은 흰색 고정
    }
    
    header = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}
    
    try:
        # 🎯 1. 코스피/코스닥 정밀 수집
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers=header, timeout=5)
            res.encoding = 'euc-kr'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 현재 지수
            now_el = soup.select_one("#now_value")
            if now_el: data[code]["val"] = now_el.get_text(strip=True)
            
            # 변동치 정제 (상승/하락 글자 제거 및 부호 유지)
            diff_el = soup.select_one("#change_value_and_rate")
            if diff_el:
                raw_txt = diff_el.get_text(" ", strip=True) # 공백을 넣어 가독성 확보
                # '상승', '하락', '보합' 글자 완전 제거
                for word in ["상승", "하락", "보합"]: raw_txt = raw_txt.replace(word, "")
                
                # 색상 결정 (부호 기준)
                if "+" in raw_txt: data[code]["color"] = "#FF4B4B"
                elif "-" in raw_txt: data[code]["color"] = "#87CEEB"
                
                data[code]["pct"] = raw_txt.strip()

            # 🎯 2. [거래량] - 코스피 루프에서 독립적으로 수집
            if code == "KOSPI":
                vol_el = soup.select_one("#quant")
                if vol_el: 
                    data["VOLUME"]["val"] = vol_el.get_text(strip=True)
                    data["VOLUME"]["pct"] = "천주" # 단위 고정

        # 🎯 3. 환율 수집
        ex_res = requests.get("https://finance.naver.com/marketindex/", headers=header, timeout=5)
        ex_soup = BeautifulSoup(ex_res.text, 'html.parser')
        ex_val = ex_soup.select_one("span.value")
        if ex_val:
            data["USD/KRW"]["val"] = ex_val.get_text(strip=True)
            ex_change = ex_soup.select_one("span.change").get_text(strip=True)
            ex_blind = ex_soup.select_one("div.head_info > span.blind").get_text()
            
            if "상승" in ex_blind:
                data["USD/KRW"]["color"], sign = "#FF4B4B", "+"
            elif "하락" in ex_blind:
                data["USD/KRW"]["color"], sign = "#87CEEB", "-"
            else:
                data["USD/KRW"]["color"], sign = "#ffffff", ""
            data["USD/KRW"]["pct"] = f"{sign}{ex_change}원"
            
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

# --- [v40.13 수집 엔진: 시간 파싱 로직 주입] ---
def get_stock_news(name):
    code = STOCK_CODES.get(str(name).replace(" ", ""))
    if not code: return []
    
    news_list = []
    header = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': f'https://finance.naver.com/item/main.naver?code={code}'
    }
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}"
        res = requests.get(url, headers=header, timeout=5)
        res.encoding = 'euc-kr' 
        soup = BeautifulSoup(res.text, 'html.parser')
        
        titles = soup.find_all('td', class_='title')
        infos = soup.find_all('td', class_='info')
        dates = soup.find_all('td', class_='date')
        
        for i in range(min(len(titles), 6)):
            link_el = titles[i].find('a')
            date_str = dates[i].get_text(strip=True) if i < len(dates) else "-"
            
            # 🕒 24시간 이내 판별
            is_recent = False
            try:
                if "전" in date_str: # '10분 전', '1시간 전' 등
                    is_recent = True
                else: # '2026.03.12 09:43' 형식
                    n_time = datetime.strptime(date_str, '%Y.%m.%d %H:%M')
                    # 현재 시간과 비교 (86400초 = 24시간)
                    if (datetime.now() - n_time).total_seconds() < 86400:
                        is_recent = True
            except: pass

            if link_el:
                news_list.append({
                    'title': link_el.get_text(strip=True),
                    'link': "https://finance.naver.com" + link_el['href'],
                    'info': infos[i].get_text(strip=True) if i < len(infos) else "정보없음",
                    'date': date_str,
                    'is_recent': is_recent # 이 플래그가 중요합니다!
                })
    except: pass
    return news_list

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

# --- [3. 데이터 로드 및 표준 날짜 최적화 연산] ---
def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    full_df = conn.read(worksheet="종목 현황", ttl="1m")
    history_df = conn.read(worksheet="trend", ttl=0)
except Exception as e:
    st.error(f"⚠️ 구글 시트 연결 오류: {e}")
    st.stop()

# --- [v40.94: 데이터 정제 구역 보강] ---
if not full_df.empty:
    full_df.columns = [c.strip() for c in full_df.columns]
    
    # 🎯 1. 숫자 변환 대상에 '목표수익률'을 추가합니다.
    target_num_cols = ['수량', '매입단가', '52주최고가', '매입후최고가', '목표가', '주당 배당금', '목표수익률']
    
    for c in target_num_cols:
        if c in full_df.columns:
            # 숫자가 아닌 문자(%, 쉼표 등)를 제거하고 숫자로 변환
            full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', '').str.replace('%', ''), errors='coerce').fillna(0)
        elif c == '목표수익률':
            # 시트에 컬럼이 아예 없을 경우를 대비해 기본값 10.0 할당
            full_df['목표수익률'] = 10.0

    # 2. 실시간 가격 및 기초 수익 지표 연산
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
    full_df['예상배당금'] = full_df['수량'] * full_df['주당 배당금']
    
    # 3. 수익률 및 변동율 (v36.50 표 전용 지표)
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비변동율'] = (full_df['전일대비손익'] / (full_df['평가금액'] - full_df['전일대비손익']).replace(0, float('nan')) * 100).fillna(0)
    
    # 4. 기대상승여력 (시트 목표가 기준)
    full_df['목표대비상승여력'] = full_df.apply(
        lambda x: ((x['목표가'] / x['현재가'] - 1) * 100) if x['현재가'] > 0 and x['목표가'] > 0 else 0, axis=1
    )

    # 5. 보유일수 계산
    if '최초매입일' in full_df.columns:
        full_df['최초매입일'] = pd.to_datetime(full_df['최초매입일'], errors='coerce')
        full_df['보유일수'] = (datetime.now().replace(hour=0,minute=0,second=0,microsecond=0) - full_df['최초매입일'].dt.tz_localize(None)).dt.days.fillna(365).astype(int).clip(lower=1)
    else: full_df['보유일수'] = 365

    # 3. 실시간 가격 수집 (v36.64 핵심 로직)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    
    # 4. 수익 지표 및 리스크 관제용 연산
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
    full_df['전일평가액'] = full_df['평가금액'] - full_df['전일대비손익']
    
    # 수익률 계산 (분모가 0인 경우를 대비한 replace 처리)
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비변동율'] = (full_df['전일대비손익'] / full_df['전일평가액'].replace(0, float('nan')) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    history_df = history_df.dropna(subset=['Date']).sort_values('Date').drop_duplicates('Date', keep='last').reset_index(drop=True)
    base_date = pd.Timestamp("2026-03-03")
    base_row = history_df[history_df['Date'] == base_date]
    history_df['KOSPI_Relative'] = (history_df['KOSPI'] / (base_row['KOSPI'].values[0] if not base_row.empty else history_df['KOSPI'].iloc[0]) - 1) * 100

st.markdown(
    f"""
    <h2 style='text-align: center; color: #87CEEB; font-size: 1.8rem; font-weight: 600; margin-bottom: 25px; letter-spacing: -0.5px;'>
        🌐 AI 금융 통합 관제탑 <span style='font-size: 1.2rem; font-weight: 300; opacity: 0.7;'>v40.94</span>
    </h2>
    """, 
    unsafe_allow_html=True
)

# --- [v40.21 HUD 렌더링: 거래량 레이아웃 최적화] ---
m_status = get_market_status()
hud_cols = st.columns(4)
titles = ["KOSPI", "KOSDAQ", "USD/KRW", "MARKET VOL"]
keys = ["KOSPI", "KOSDAQ", "USD/KRW", "VOLUME"]

for i, col in enumerate(hud_cols):
    with col:
        d = m_status[keys[i]]
        # 테두리 색상: 거래량은 은은한 회색, 지수는 변동색 적용
        border = f"{d['color']}44" if keys[i] != "VOLUME" else "rgba(255,255,255,0.1)"
        
        st.markdown(f"""
            <div style='text-align: center; padding: 15px; border-radius: 12px; background: rgba(255,255,255,0.03); border: 1px solid {border};'>
                <div style='color: #aaa; font-size: 0.85rem; font-weight: bold; margin-bottom: 5px;'>{titles[i]}</div>
                <div style='color: {d['color']}; font-size: 1.8rem; font-weight: bold; line-height: 1.2;'>{d['val']}</div>
                <div style='color: {d['color'] if keys[i] != "VOLUME" else "#aaa"}; font-size: 1.0rem; font-weight: 500; margin-top: 5px;'>
                    {d['pct']}
                </div>
            </div>
        """, unsafe_allow_html=True)
        
st.write("") # 간격 조절

tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

with tabs[0]:
    # 1. 최상단 요약 Metric (가족 전체 합계)
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

    # 2. 계좌별 요약 테이블 (음양 색채 및 정수 처리 적용)
    sum_acc = full_df.groupby('계좌명').agg({
        '매입금액':'sum', 
        '평가금액':'sum', 
        '손익':'sum', 
        '전일대비손익':'sum'
    }).reset_index()
    
    # 지표 재연산
    sum_acc['전일평가액'] = sum_acc['평가금액'] - sum_acc['전일대비손익']
    sum_acc['전일대비변동율'] = (sum_acc['전일대비손익'] / sum_acc['전일평가액'].replace(0, float('nan')) * 100).fillna(0)
    sum_acc['누적수익률'] = (sum_acc['손익'] / sum_acc['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    
    # 표시용 이름 변경 및 컬럼 정의
    sum_acc_plot = sum_acc.rename(columns=GLOBAL_RENAME_MAP)
    sum_acc_cols = ['계좌명', '매입금액', '평가금액', '손익', '전일대비(원)', '전일대비(%)', '누적수익률']
    
    # --- [v40.99 스타일링 적용] ---
    st.dataframe(
        sum_acc_plot[sum_acc_cols].style.applymap(
            lambda x: 'color: #FF4B4B' if (isinstance(x, (int, float)) and x > 0) 
                      else 'color: #87CEEB' if (isinstance(x, (int, float)) and x < 0) 
                      else '',
            subset=['손익', '전일대비(원)', '전일대비(%)', '누적수익률'] # 🎯 색상 적용 대상
        ).format({
            '매입금액': '{:,.0f}원', 
            '평가금액': '{:,.0f}원', 
            '손익': '{:+,.0f}원', 
            '전일대비(원)': '{:+,.0f}원', # 🎯 0f로 정수 처리 (요청사항)
            '전일대비(%)': '{:+.2f}%', 
            '누적수익률': '{:+.2f}%'
        }), 
        hide_index=True, use_container_width=True
    )
    
    # 🎯 [위치 조정] 테이블 바로 아래에 배당 HUD와 차트 배치 시작
    st.divider()

    # 3. 배당 HUD (4단계 등급 적용)
    total_div = full_df['예상배당금'].sum()
    monthly_after_tax = (total_div * (1 - 0.154)) / 12
    t_grade = get_cashflow_grade(monthly_after_tax) # 4단계 등급 판정
    
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("연간 예상 총 배당금", f"{total_div:,.0f}원")
    d2.metric("세후 월 평균 수령액", f"{monthly_after_tax:,.0f}원")
    d3.metric("포트 배당수익률", f"{(total_div / t_eval * 100):.2f}%" if t_eval != 0 else "0.00%")
    d4.metric("통합 현금흐름 등급", t_grade)

    # (앞선 메트릭, 테이블, 배당 HUD 코드는 그대로 유지)
    st.divider()

    # 🎯 [v40.99 UI 강화] 테두리가 있는 카드 레이아웃 적용
    chart_col1, chart_col2 = st.columns(2)

    # --- 좌측 카드: 자산 성장 추이 ---
    with chart_col1:
        with st.container(border=True): # 👈 은은한 테두리 박스 생성
            if not history_df.empty:
                fig_total = go.Figure()
                h_dt = history_df['Date'].dt.date.astype(str)
                
                # KOSPI 상대 수익률 (점선)
                fig_total.add_trace(go.Scatter(
                    x=h_dt, y=history_df['KOSPI_Relative'], 
                    name='KOSPI', 
                    line=dict(dash='dash', color='rgba(255,255,255,0.3)')
                ))
                
                # 계좌별 수익률 추이 (실선)
                for acc in sum_acc['계좌명'].unique():
                    acc_col = find_matching_col(history_df, acc)
                    if acc_col:
                        fig_total.add_trace(go.Scatter(x=h_dt, y=history_df[acc_col], name=acc))
                
                fig_total.update_layout(
                    title=dict(text="📈 자산 성장 추이 (KOSPI 대비)", x=0.02, y=0.9),
                    height=380,
                    paper_bgcolor='rgba(0,0,0,0)', 
                    plot_bgcolor='rgba(255,255,255,0.02)', # 👈 차트 내부 미세 배경색
                    font_color="white",
                    legend=dict(orientation="h", yanchor="bottom", y=-0.4, xanchor="center", x=0.5),
                    margin=dict(t=80, b=100, l=20, r=20)
                )
                st.plotly_chart(fig_total, use_container_width=True)
            else:
                st.info("성과 추이 데이터를 분석 중입니다...")

    # --- 우측 카드: 월별 배당 흐름 ---
    with chart_col2:
        with st.container(border=True): # 👈 은은한 테두리 박스 생성
            monthly_data = {m: 0 for m in range(1, 13)}
            for _, row in full_df.iterrows():
                name, t_div_row = row['종목명'], row['예상배당금']
                months = DIVIDEND_SCHEDULE.get(name, [4])
                if t_div_row > 0:
                    for m in months: monthly_data[m] += (t_div_row / len(months))

            m_names = [f"{m}월" for m in range(1, 13)]
            m_vals = [monthly_data[m] for m in range(1, 13)]
            m_colors = ['#FFD700' if v == max(m_vals) and v > 0 else 'rgba(135,206,235,0.2)' for v in m_vals]

            fig_cal = go.Figure(go.Bar(
                x=m_names, y=m_vals, 
                marker_color=m_colors, 
                text=[f"{v/10000:.0f}만" if v > 0 else "" for v in m_vals], 
                textposition='outside'
            ))
            fig_cal.update_layout(
                title=dict(text="📅 월별 예상 배당 입금액", x=0.02, y=0.9),
                height=380, 
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(255,255,255,0.02)', # 👈 차트 내부 미세 배경색
                font_color="white",
                margin=dict(t=80, b=40, l=20, r=20)
            )
            st.plotly_chart(fig_cal, use_container_width=True)
    
def render_account_tab(acc_name, tab_obj, yield_col_name):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty:
            st.warning(f"{acc_name} 데이터가 발견되지 않았습니다.")
            return
        
        # --- [1. 상단 계좌 요약 Metric] ---
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        a_diff = sub_df['전일대비손익'].sum()
        a_pct = (a_diff / (a_eval - a_diff) * 100) if (a_eval - a_diff) != 0 else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("계좌 평가액", f"{a_eval:,.0f}원", delta=f"{a_diff:+,.0f}원 ({a_pct:+.2f}%)")
        c2.metric("계좌 매입액", f"{a_buy:,.0f}원")
        c3.metric("계좌 손익", f"{a_eval-a_buy:+,.0f}원")
        c4.metric("계좌 수익률", f"{(a_eval/a_buy-1)*100:+.2f}%", delta=f"{a_pct:+.2f}%p")

        # --- [2. 보유 종목 테이블] --- (음양 색채 유지)
        plot_df = sub_df.rename(columns=GLOBAL_RENAME_MAP)
        st.dataframe(
            plot_df[GLOBAL_DISPLAY_COLS].style.apply(lambda x: [
                'color: #FF4B4B' if (i >= 6 and val > 0) else 'color: #87CEEB' if (i >= 6 and val < 0) else '' 
                for i, val in enumerate(x)
            ], axis=1).format({
                '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '매입금액': '{:,.0f}원', '현재가': '{:,.0f}원', 
                '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(원)': '{:+,.0f}원', 
                '전일대비(%)': '{:+.2f}%', '누적수익률': '{:+.2f}%'
            }), 
            hide_index=True, use_container_width=True
        )

        st.divider()

        # --- [3. 현금흐름 등급 섹션] ---
        a_total_div = sub_df['예상배당금'].sum()
        a_monthly_tax = (a_total_div * (1 - 0.154)) / 12
        a_grade = get_cashflow_grade(a_monthly_tax)
        
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("연간 예상 배당금", f"{a_total_div:,.0f}원")
        d2.metric("세후 월 수령액", f"{a_monthly_tax:,.0f}원")
        d3.metric("계좌 배당수익률", f"{(a_total_div/a_eval*100):.2f}%")
        d4.metric("계좌 현금흐름 등급", a_grade)

        st.divider()

        # --- [4. 계좌별 병렬 차트 구역 (배당/비중)] ---
        g_left, g_right = st.columns(2)
        with g_left:
            with st.container(border=True):
                a_monthly_data = {m: 0 for m in range(1, 13)}
                for _, row in sub_df.iterrows():
                    sched = DIVIDEND_SCHEDULE.get(row['종목명'], [4])
                    for m in sched: a_monthly_data[m] += (row['예상배당금']/len(sched))
                fig_a_cal = go.Figure(go.Bar(x=[f"{m}월" for m in range(1, 13)], y=list(a_monthly_data.values()), marker_color='rgba(255, 215, 0, 0.6)', text=[f"{v/10000:.1f}만" if v > 0 else "" for v in a_monthly_data.values()], textposition='outside'))
                fig_a_cal.update_layout(title=dict(text="📅 월별 배당 예측", x=0.02), height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(255,255,255,0.02)', font_color="white", margin=dict(t=80, b=20))
                st.plotly_chart(fig_a_cal, use_container_width=True)

        with g_right:
            with st.container(border=True):
                chart_df = sub_df[['종목명', '평가금액', '누적수익률']].copy()
                chart_df['Display_Name'] = chart_df['종목명'].apply(lambda x: x[:9] + ".." if len(x) > 9 else x)
                fig_bar = go.Figure(go.Bar(y=chart_df['Display_Name'], x=chart_df['평가금액'], orientation='h', marker_color=['#FF4B4B' if r > 0 else '#87CEEB' for r in chart_df['누적수익률']], text=[f" {int(v/a_eval*100)}%" if a_eval != 0 else "" for v in chart_df['평가금액']], textposition='outside'))
                fig_bar.update_layout(title=dict(text="📊 자산 비중", x=0.02), height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(255,255,255,0.02)', font_color="white", margin=dict(t=80, b=20))
                st.plotly_chart(fig_bar, use_container_width=True)
                
        st.divider()

        # --- [5. 통합 투자종목 정밀 분석 (버튼 하나로 일괄 통제)] ---
        # 🎯 통합 버튼: 이 버튼 하나가 아래의 모든(지표, 전략, 가이드, 차트, 뉴스) 데이터를 결정합니다.
        sel = st.selectbox(f"🔍 {acc_name} 종목 정밀 분석 (전략/성과/뉴스 통합)", sub_df['종목명'].unique(), key=f"sel_{acc_name}_unified")
        s_row = sub_df[sub_df['종목명'] == sel].iloc[0]
        
        curr_p, buy_p = float(s_row.get('현재가', 0)), float(s_row.get('매입단가', 0))
        target_p, high_52 = float(s_row.get('목표가', 0)), float(s_row.get('52주최고가', 0))
        post_high = float(s_row.get('매입후최고가', curr_p))
        total_ret, upside = float(s_row.get('누적수익률', 0)), float(s_row.get('목표대비상승여력', 0))
        days = max(int(s_row.get('보유일수', 365)), 1)
        ann_ret = ((1 + total_ret/100)**(365/days) - 1) * 100
        sl_price, tp_price = buy_p * 0.85, post_high * 0.80

        # (A) 재무지표 및 전략 모니터 (사용자님 스타일 유지)
        col_res, col_strat = st.columns([1, 1])
        with col_res:
            res = RESEARCH_DATA.get(sel.replace(" ", ""))
            if res:
                m_html = "".join([f"<tr><td>{m[0]}</td><td style='text-align:right;'>{m[1]} → <span style='color:#FFD700;'>{m[2]}</span></td></tr>" for m in res['metrics']])
                st.html(f"<div class='report-box' style='height:210px;'>📋 <b>핵심 재무 지표</b><table style='width:100%'>{m_html}</table><div style='margin-top:10px; font-size:0.85rem; border-top:1px solid rgba(255,255,255,0.05); padding-top:8px;'><span style='color:#FFD700;'>💡 인사이트:</span> {res['implications'][0]}</div></div>")
            else: st.info("💡 종목 분석 데이터가 없습니다.")

        with col_strat:
            st.html(f"""
                <div style='background: rgba(135,206,235,0.05); padding: 15px; border-radius: 8px; border: 1px solid rgba(135,206,235,0.1); height: 210px; text-align: center;'>
                    <div style='color: #87CEEB; font-size: 0.85rem; font-weight: bold; margin-bottom: 15px;'>⚡ 실시간 전략 모니터</div>
                    <div style='display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px;'>
                        <div><div style='font-size: 0.75rem; opacity: 0.6;'>연 환산 수익률</div><div style='font-size: 1.2rem; font-weight: bold; color: #FF4B4B;'>{ann_ret:+.1f}%</div></div>
                        <div style='border-left: 1px solid rgba(255,255,255,0.1); border-right: 1px solid rgba(255,255,255,0.1);'><div style='font-size: 0.75rem; color: #FFD700;'>🎯 시트 목표가</div><div style='font-size: 1.2rem; font-weight: bold; color: #FFD700;'>{target_p:,.0f}</div></div>
                        <div><div style='font-size: 0.75rem; opacity: 0.6;'>기대 상승 여력</div><div style='font-size: 1.2rem; font-weight: bold; color: #00FF00;'>{upside:+.1f}%</div></div>
                    </div>
                    <div style='border-top: 1px solid rgba(255,255,255,0.05); padding-top: 10px; margin-top: 15px; font-size: 0.9rem; color: #bbb;'>현재가: <b>{curr_p:,.0f}원</b> / 52주 최고: {high_52:,.0f}원</div>
                </div>
            """)

        # (B) 리스크 경보 시스템
        st.html(f"""
            <div style='background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px; border: 1px solid {"#FF4B4B" if curr_p <= sl_price else "rgba(255,255,255,0.1)"}; margin-top: 15px;'>
                <div style='display: flex; justify-content: space-between; font-size: 0.95rem;'>
                    <span>🛡️ <b>손절 가이드 (-15%):</b> {sl_price:,.0f}원 <small>(매입 {buy_p:,.0f} 대비)</small></span>
                    <span style='color: {"#FF4B4B" if curr_p <= sl_price else "#00FF00"}; font-weight: bold;'>{"⚠️ 즉시 대응" if curr_p <= sl_price else "✅ 매우 안전"}</span>
                </div>
                <div style='display: flex; justify-content: space-between; font-size: 0.95rem; margin-top: 8px;'>
                    <span>🚨 <b>익절 가이드 (-20%):</b> {tp_price:,.0f}원 <small>(최고 {post_high:,.0f} 대비)</small></span>
                    <span style='color: {"#FFA500" if curr_p <= tp_price else "#00FF00"}; font-weight: bold;'>{"⚠️ 추세 이탈" if curr_p <= tp_price else "✅ 추세 유지"}</span>
                </div>
            </div>
        """)

        # (C) 성과 추이 차트 (별도의 버튼 없이 위에서 선택한 'sel' 사용)
        with st.container(border=True):
            if not history_df.empty:
                fig_acc = go.Figure()
                history_df['Date'] = pd.to_datetime(history_df['Date'])
                h_dt = history_df['Date'].dt.date.astype(str)
                
                goal_val = s_row.get('목표수익률', 10.0)
                if goal_val == 0 or pd.isna(goal_val): goal_val = 10.0
                indiv_target_yield = int(float(goal_val) * 1000) / 1000 
                static_target_line = [indiv_target_yield] * len(h_dt)

                fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df['KOSPI_Relative'], name='KOSPI', line=dict(dash='dash', color='rgba(255,255,255,0.3)', width=1)))
                fig_acc.add_trace(go.Scatter(x=h_dt, y=static_target_line, name='목표 수익률', line=dict(color='#FFD700', width=2, dash='dot')))
                
                acc_col = find_matching_col(history_df, acc_name)
                if acc_col:
                    current_y = history_df[acc_col].iloc[-1]
                    line_color = '#00FF00' if current_y >= indiv_target_yield else '#FF4B4B'
                    fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[acc_col], mode='lines+markers', name='계좌 수익률', line=dict(width=4, color=line_color)))
                
                s_col = find_matching_col(history_df, acc_name, sel)
                if s_col:
                    fig_acc.add_trace(go.Scatter(x=h_dt, y=history_df[s_col], mode='lines', name=sel[:9], line=dict(width=2, dash='dashdot', color='rgba(135,206,235,0.6)')))

                fig_acc.update_layout(title=dict(text=f"📈 {sel} 성과 분석 추이", x=0.02), height=400, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(255,255,255,0.02)', font_color="white", legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5), margin=dict(t=80, b=80), xaxis=dict(type='category', tickangle=-45))
                st.plotly_chart(fig_acc, use_container_width=True)
                
        # (D) 실시간 뉴스 섹션
        st.divider()
        st.html(f"<div style='font-size: 1.2rem; font-weight: bold; margin-bottom: 15px;'>📰 {sel} 실시간 주요 뉴스</div>")
        news_items = get_stock_news(sel)
        if news_items:
            n_col1, n_col2 = st.columns([1, 1])
            for idx, item in enumerate(news_items[:6]): # 상위 6개만 표시
                target_col = n_col1 if idx % 2 == 0 else n_col2
                with target_col:
                    is_hot = item.get('is_recent', False)
                    st.html(f"""
                        <div style="margin-bottom: 10px; padding: 10px; border-radius: 8px; border-left: 4px solid {"#FFD700" if is_hot else "#87CEEB"}; background: rgba(255,255,255,0.02);">
                            <a href="{item['link']}" target="_blank" style="text-decoration: none; color: #87CEEB; font-size: 0.95rem;">
                                {"<span style='color:#FFD700;'>[NEW]</span> " if is_hot else ""}{item['title']}
                            </a>
                        </div>
                    """)
        else: st.caption("새로운 뉴스가 없습니다.")
                
render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
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
                    
st.caption(f"v40.94 가디언 레질리언스 | {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")










