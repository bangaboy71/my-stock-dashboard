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

# --- [2. 엔진 및 헬퍼 함수: 네이버 + 야후 하이브리드 지수 엔진] ---
def get_market_status():
    # 🎯 [기본값 설정] KeyError 방지를 위해 모든 항목을 초기화
    data = {
        "KOSPI": {"val": "-", "diff": "0.00", "pct": "0.00%", "color": "white"},
        "KOSDAQ": {"val": "-", "diff": "0.00", "pct": "0.00%", "color": "white"},
        "USD/KRW": {"val": "-", "diff": "0.00", "pct": "원", "color": "white"},
        "VOLUME": {"val": "-", "diff": "KOSPI", "pct": "천주", "color": "white"}
    }
    
    header = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    
    # 🎯 [1단계: Naver Finance] 정밀 크롤링 시도
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers=header, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            now_el = soup.select_one("#now_value")
            prev_el = soup.select_one("td.first") # 전일종가 영역
            
            if now_el and prev_el:
                now_val = float(now_el.get_text(strip=True).replace(',', ''))
                import re
                prev_text = prev_el.get_text(strip=True).replace(',', '')
                prev_nums = re.findall(r"\d+\.\d+|\d+", prev_text)
                
                if prev_nums:
                    prev_val = float(prev_nums[0])
                    diff_val = now_val - prev_val
                    pct_val = (diff_val / prev_val) * 100
                    color = "#FF4B4B" if diff_val > 0 else "#87CEEB" if diff_val < 0 else "white"
                    
                    data[code] = {
                        "val": f"{now_val:,.2f}",
                        "diff": f"{diff_val:+,.2f}",
                        "pct": f"{pct_val:+.2f}%",
                        "color": color
                    }
            if code == "KOSPI":
                vol_el = soup.select_one("#quant")
                if vol_el: data["VOLUME"]["val"] = vol_el.get_text(strip=True)

        # 환율 (Naver)
        ex_res = requests.get("https://finance.naver.com/marketindex/", headers=header, timeout=3)
        ex_soup = BeautifulSoup(ex_res.text, 'html.parser')
        ex_val_el = ex_soup.select_one("span.value")
        if ex_val_el:
            data["USD/KRW"]["val"] = ex_val_el.get_text(strip=True)
            ex_change = ex_soup.select_one("span.change")
            ex_blind = ex_soup.select_one("div.head_info > span.blind")
            if ex_change and ex_blind:
                is_down = "하락" in ex_blind.get_text()
                data["USD/KRW"]["diff"] = f"-{ex_change.get_text()}" if is_down else f"+{ex_change.get_text()}"
                data["USD/KRW"]["color"] = "#87CEEB" if is_down else "#FF4B4B"
    except:
        pass # 네이버 실패 시 조용히 야후로 넘어감

    # 🎯 [2단계: Yahoo Finance 백업] 데이터가 비어있는 항목 보완
    yf_mapping = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "USD/KRW": "KRW=X"}
    
    for name, ticker in yf_mapping.items():
        if data[name]["val"] == "-": # 네이버 데이터가 없을 때만 실행
            try:
                tk = yf.Ticker(ticker)
                hist = tk.history(period="2d")
                if not hist.empty:
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2]
                    now_p = latest['Close']
                    diff = now_p - prev['Close']
                    pct = (diff / prev['Close']) * 100
                    
                    color = "#FF4B4B" if diff > 0 else "#87CEEB" if diff < 0 else "white"
                    
                    data[name] = {
                        "val": f"{now_p:,.2f}",
                        "diff": f"{diff:+,.2f}",
                        "pct": f"{pct:+.2f}%",
                        "color": color
                    }
                    # 거래량이 비어있다면 야후 데이터로 보완
                    if name == "KOSPI" and data["VOLUME"]["val"] == "-":
                        data["VOLUME"]["val"] = f"{latest['Volume']/1000:,.0f}"
                        data["VOLUME"]["diff"] = "YF_VOL"
            except:
                continue

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

# --- [v40.5 데이터 정제: 수익률표 복구 및 목표가 인식] ---
if not full_df.empty:
    full_df.columns = [c.strip() for c in full_df.columns]
    
    # 1. 숫자 변환 (매입후최저가 제외, 목표가 추가)
    target_num_cols = ['수량', '매입단가', '52주최고가', '매입후최고가', '목표가']
    for c in target_num_cols:
        if c in full_df.columns:
            full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        elif c == '목표가': full_df['목표가'] = 0

    # 2. 실시간 가격 및 기초 수익 지표 연산
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
    
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
        🌐 AI 금융 통합 관제탑 <span style='font-size: 1.2rem; font-weight: 300; opacity: 0.7;'>v36.64</span>
    </h2>
    """, 
    unsafe_allow_html=True
)

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

# --- [v40.18 패치: 마크다운 간섭 차단 및 차트 레이아웃 완전 복구] ---
def render_account_tab(acc_name, tab_obj, history_col_key):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty:
            st.warning(f"{acc_name} 데이터가 발견되지 않았습니다.")
            return
        
        # 1. 상단 계좌 요약 (Metric)
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        a_diff = sub_df['전일대비손익'].sum()
        a_pct = (a_diff / (a_eval - a_diff) * 100) if (a_eval - a_diff) != 0 else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", delta=f"{a_diff:+,.0f}원 ({a_pct:+.2f}%)")
        c2.metric("매입액", f"{a_buy:,.0f}원")
        c3.metric("손익", f"{a_eval-a_buy:+,.0f}원")
        c4.metric("누적수익률", f"{(a_eval/a_buy-1)*100:+.2f}%", delta=f"{a_pct:+.2f}%p")
        
        # 2. 보유 종목 수익률 테이블 (10개 컬럼)
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
        
        # 3. 종목 분석 선택 및 수치 계산
        sel = st.selectbox(f"📍 {acc_name} 종목 분석", sub_df['종목명'].unique(), key=f"sel_v4018_{acc_name}")
        s_row = sub_df[sub_df['종목명'] == sel].iloc[0]
        
        curr_p, buy_p = float(s_row.get('현재가', 0)), float(s_row.get('매입단가', 0))
        target_p, high_52 = float(s_row.get('목표가', 0)), float(s_row.get('52주최고가', 0))
        post_high = float(s_row.get('매입후최고가', curr_p))
        total_ret, upside = float(s_row.get('누적수익률', 0)), float(s_row.get('목표대비상승여력', 0))
        days = max(int(s_row.get('보유일수', 365)), 1)
        ann_ret = ((1 + total_ret/100)**(365/days) - 1) * 100
        sl_price, tp_price = buy_p * 0.85, post_high * 0.80

        # 4. [중앙] 지표 및 전략 모니터
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

        # 5. [하단] 리스크 경보 시스템
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

        # 6. [복구] 성과 추이 및 자산 비중 차트 레이아웃
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

        # 7. [최종] 실시간 뉴스 섹션 (st.html 사용으로 마크다운 간섭 완전 차단)
        st.divider()
        st.html(f"<div style='font-size: 1.2rem; font-weight: bold; margin-bottom: 15px;'>📰 {sel} 실시간 주요 뉴스 및 공시</div>")
        
        news_items = get_stock_news(sel)
        if news_items:
            n_col1, n_col2 = st.columns([1, 1])
            for idx, item in enumerate(news_items):
                target_col = n_col1 if idx % 2 == 0 else n_col2
                with target_col:
                    is_hot = item.get('is_recent', False)
                    b_color = "#FFD700" if is_hot else "rgba(135,206,235,0.3)"
                    bg_color = "rgba(255, 215, 0, 0.04)" if is_hot else "rgba(135,206,235,0.02)"
                    badge = "<span style='color:#FFD700; font-weight:bold; font-size:0.85rem; margin-right:5px;'>[NEW]</span>" if is_hot else ""
                    
                    # 🎯 핵심: st.html()은 f-string 내부의 들여쓰기를 코드로 오해하지 않습니다.
                    st.html(f"""
                        <div style="margin-bottom: 12px; padding: 12px; border-radius: 8px; border-left: 4px solid {b_color}; background: {bg_color};">
                            {badge}
                            <a href="{item['link']}" target="_blank" style="text-decoration: none; color: #87CEEB; font-weight: 500; font-size: 1.0rem; line-height: 1.4;">
                                {item['title']}
                            </a><br>
                            <div style="margin-top: 8px; font-size: 0.8rem; color: #888; display: flex; justify-content: space-between; opacity: 0.8;">
                                <span>🏢 {item['info']}</span>
                                <span>📅 {item['date']}</span>
                            </div>
                        </div>
                    """)
        else:
            st.caption("새로운 뉴스 데이터가 없습니다.")
                
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
                    
st.caption(f"v36.50 가디언 레질리언스 | {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")













