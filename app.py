import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

# --- [1. 기본 설정] ---
st.set_page_config(page_title="주식 관제탑 v37.5", layout="wide")

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

# --- [2. 시장 데이터 엔진: 최대한 가볍고 안전하게] ---
def get_market_status():
    try:
        # KOSPI 지수만 가볍게 가져옴
        ticker = yf.Ticker("^KS11")
        hist = ticker.history(period="2d")
        if not hist.empty:
            curr = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2]
            chg = curr - prev
            per = (chg / prev) * 100
            return {"KOSPI": {"val": f"{curr:,.2f}", "chg": f"{chg:+.2f}", "per": f"{per:+.2f}%"}}
    except: pass
    return {"KOSPI": {"val": "0.00", "chg": "0.00", "per": "0.00%"}}

def get_stock_price(ticker):
    try:
        if not ticker or str(ticker) == 'nan': return 0, 0
        s = yf.Ticker(str(ticker).strip())
        # fast_info 대신 가장 안정적인 history 사용
        hist = s.history(period="2d")
        if not hist.empty:
            return hist['Close'].iloc[-1], hist['Close'].iloc[-2]
    except: pass
    return 0, 0

# --- [3. 데이터 로드 및 v36.64식 매핑 복구] ---
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    full_df = conn.read(worksheet="종목 현황", ttl="1m")
    history_df = conn.read(worksheet="trend", ttl=0)
except Exception as e:
    st.error(f"⚠️ 시트 연결 실패: {e}"); st.stop()

# A. 종목 현황 정제 (v36.64 연산 로직)
if not full_df.empty:
    # 숫자 변환
    for c in ['수량', '매입단가', '52주최고가']:
        if c in full_df.columns:
            full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    # 실시간 가격 반영
    if '종목코드' in full_df.columns:
        with st.spinner("🚀 실시간 시세 반영 중..."):
            prices = [get_stock_price(t) for t in full_df['종목코드']]
            full_df['현재가'] = [p[0] for p in prices]
            full_df['전일종가'] = [p[1] for p in prices]
    
    # 기본 수익 지표 연산
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['상승여력'] = (full_df['52주최고가'] / full_df['현재가'].replace(0, 1) - 1) * 100

# B. 성과 추이 정제 (중복 해결 및 날짜 고정)
if not history_df.empty:
    history_df = history_df.loc[:, ~history_df.columns.duplicated()]
    # '날짜'나 'Date' 중 하나를 선택해 Date로 통일
    date_col = '날짜' if '날짜' in history_df.columns else 'Date'
    history_df['Date'] = pd.to_datetime(history_df[date_col], errors='coerce')
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [4. UI 구성: v36.64의 직관성 복구] ---
st.title("🦅 주식 관제탑 (안정성 복구 버전)")
m_data = get_market_status()
st.metric("KOSPI", m_data['KOSPI']['val'], f"{m_data['KOSPI']['chg']} ({m_data['KOSPI']['per']})")

tab1, tab2 = st.tabs(["📊 현황 요약", "📈 성과 추이"])

with tab1:
    # 계좌별 요약
    if not full_df.empty:
        acc_sum = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum'}).reset_index()
        acc_sum['수익률'] = (acc_sum['손익'] / acc_sum['매입금액'] * 100).map("{:,.2f}%".format)
        st.subheader("계좌별 성과 요약")
        st.table(acc_sum)
        st.subheader("상세 종목 현황")
        st.dataframe(full_df, use_container_width=True)

with tab2:
    if not history_df.empty:
        fig = go.Figure()
        # 시트의 계좌별 수익률 열(서은, 서희, 큰스님) 매핑
        for col in ['서은수익률', '서희수익률', '큰스님수익률']:
            if col in history_df.columns:
                fig.add_trace(go.Scatter(x=history_df['Date'], y=history_df[col], name=col, mode='lines+markers'))
        
        fig.update_layout(xaxis_type='date', hovermode='x unified', title="투자자별 누적 수익률 추이")
        st.plotly_chart(fig, use_container_width=True)

# --- [5. 사이드바: 관리 기능 (v36.64 방식 + 신규 기능)] ---
with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 전체 갱신"):
        st.cache_data.clear(); st.rerun()
    
    st.divider()
    
    # 기능 1: 결과 확정 저장 (v37.2 안정화 버전)
    sel_date = st.date_input("📅 저장 날짜", value=datetime.now())
    if st.button(f"🚀 {sel_date} 확정 저장"):
        try:
            save_date_str = sel_date.strftime('%Y-%m-%d')
            # KOSPI 수집
            k_val = float(m_data['KOSPI']['val'].replace(',',''))
            
            # 신규 행 생성
            new_row = pd.Series(index=history_df.columns, dtype='object')
            new_row['Date'] = save_date_str
            new_row['날짜'] = save_date_str
            new_row['KOSPI'] = k_val
            
            # 계좌 및 종목 매핑 (v36.99 공백 제거 적용)
            for acc in full_df['계좌명'].unique():
                acc_df = full_df[full_df['계좌명'] == acc]
                acc_ret = (acc_df['손익'].sum() / acc_df['매입금액'].sum() * 100) if acc_df['매입금액'].sum() > 0 else 0
                
                # 계좌 수익률 저장
                acc_col = f"{acc.replace('투자','')}수익률"
                if acc_col in new_row.index: new_row[acc_col] = acc_ret
                
                # 종목 수익률 저장
                for _, r in acc_df.iterrows():
                    clean_name = r['종목명'].replace(' ', '').strip()
                    s_col = f"{acc.replace('투자','')}_{clean_name}수익률"
                    if s_col in new_row.index: new_row[s_col] = r['누적수익률']

            # 합치기
            hist_tmp = history_df.copy()
            hist_tmp['Date'] = hist_tmp['Date'].dt.strftime('%Y-%m-%d')
            updated = pd.concat([hist_tmp[hist_tmp['Date'] != save_date_str], pd.DataFrame([new_row])], ignore_index=True)
            updated = updated.sort_values('Date')
            
            conn.update(worksheet="trend", data=updated)
            st.success("✅ 저장 완료!"); st.rerun()
        except Exception as e:
            st.error(f"❌ 저장 실패: {e}")

    st.divider()

    # 기능 2: 52주 최고가 자동화 (v36.97)
    if st.button("📈 52주 최고가 자동 업데이트"):
        try:
            for idx, row in full_df.iterrows():
                ticker = str(row.get('종목코드', '')).strip()
                if ticker and ticker != 'nan':
                    new_high = yf.Ticker(ticker).info.get('fiftyTwoWeekHigh')
                    if new_high: full_df.at[idx, '52주최고가'] = new_high
            conn.update(worksheet="종목 현황", data=full_df)
            st.success("✅ 최고가 업데이트 완료!"); st.rerun()
        except Exception as e:
            st.error(f"❌ 실패: {e}")
