import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

# --- [1. 기본 설정 및 보안] ---
st.set_page_config(page_title="주식 인텔리전스 관제탑", layout="wide", initial_sidebar_state="expanded")

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

# --- [2. 시장 데이터 수집 엔진] ---
@st.cache_data(ttl=600)
def get_market_status():
    """KOSPI 지수 및 변동률 수집"""
    try:
        kospi = yf.Ticker("^KS11")
        hist = kospi.history(period="2d")
        if len(hist) >= 2:
            val = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2]
            chg = val - prev
            per = (chg / prev) * 100
            return {"KOSPI": {"val": f"{val:,.2f}", "chg": f"{chg:+.2f}", "per": f"{per:+.2f}%"}}
    except:
        pass
    return {"KOSPI": {"val": "0.00", "chg": "0.00", "per": "0.00%"}}

def get_stock_data(ticker):
    """개별 종목 실시간가 수집 (Ticker 기반)"""
    try:
        if not ticker or str(ticker) == 'nan': return 0, 0
        stock = yf.Ticker(str(ticker).strip())
        info = stock.fast_info
        curr = info['last_price']
        prev = info['regular_market_previous_close']
        return curr, prev
    except:
        return 0, 0

# --- [3. 데이터 로드 및 정제 엔진: 중복/에러 방어] ---
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    full_df = conn.read(worksheet="종목 현황", ttl="1m")
    history_df = conn.read(worksheet="trend", ttl=0)
except Exception as e:
    st.error(f"⚠️ 시트 연결 오류: {e}")
    st.stop()

# --- A. 종목 현황 데이터 연산 (실시간 반영) ---
if not full_df.empty:
    # 숫자 데이터 정제
    num_cols = ['수량', '매입단가', '52주최고가', '매입후최고가', '매입후최저가']
    for c in num_cols:
        if c in full_df.columns:
            full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

    # 실시간 가격 주입
    if '종목코드' in full_df.columns:
        prices = [get_stock_data(t) for t in full_df['종목코드']]
        full_df['현재가'] = [p[0] for p in prices]
        full_df['전일종가'] = [p[1] for p in prices]
    
    # 핵심 수익 지표 연산
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
    full_df['전일평가액'] = full_df['평가금액'] - full_df['전일대비손익']
    
    full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['전일대비변동율'] = (full_df['전일대비손익'] / full_df['전일평가액'].replace(0, float('nan')) * 100).fillna(0)
    full_df['상승여력'] = (full_df['52주최고가'] / full_df['현재가'].replace(0, 1) - 1) * 100

# --- B. 성과 추이(history_df) 정제 (ValueError & KeyError 방지) ---
if not history_df.empty:
    # 1. 중복 컬럼 제거 및 이름 충돌 해결
    history_df = history_df.loc[:, ~history_df.columns.duplicated()]
    t_col = '날짜' if '날짜' in history_df.columns else 'Date'
    
    if t_col in history_df.columns:
        # 날짜 타입 강제 고정 (가로축 왜곡 방지 핵심)
        history_df['Date'] = pd.to_datetime(history_df[t_col], errors='coerce')
        if t_col != 'Date': history_df = history_df.drop(columns=[t_col])
        history_df = history_df.dropna(subset=['Date']).sort_values('Date').reset_index(drop=True)

    # 2. KOSPI_Relative 연산 (그래프 벤치마크)
    if 'KOSPI' in history_df.columns:
        history_df['KOSPI'] = pd.to_numeric(history_df['KOSPI'], errors='coerce')
        base_k = history_df['KOSPI'].iloc[0]
        history_df['KOSPI_Relative'] = ((history_df['KOSPI'] / base_k - 1) * 100) if base_k > 0 else 0

# --- [4. 대시보드 메인 UI] ---
st.title("🦅 주식 포트폴리오 관제탑")
m_data = get_market_status()
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("KOSPI 지수", m_data['KOSPI']['val'], f"{m_data['KOSPI']['chg']} ({m_data['KOSPI']['per']})")

# 계좌별 요약 탭
tab1, tab2 = st.tabs(["📊 보유 종목 현황", "📈 성과 추이 그래프"])

with tab1:
    st.subheader("계좌별 성과 요약")
    if not full_df.empty:
        summary_acc = full_df.groupby('계좌명').agg({
            '매입금액':'sum', '평가금액':'sum', '손익':'sum', '전일대비손익':'sum'
        }).reset_index()
        summary_acc['누적수익률'] = (summary_acc['손익'] / summary_acc['매입금액'] * 100).map("{:,.2f}%".format)
        st.dataframe(summary_acc, use_container_width=True)
        st.dataframe(full_df, use_container_width=True)

with tab2:
    if not history_df.empty:
        fig = go.Figure()
        # 시트의 '수익률' 관련 열들을 자동으로 찾아 그래프에 추가
        for col in [c for c in history_df.columns if '수익률' in c and '_' not in c]:
            fig.add_trace(go.Scatter(x=history_df['Date'], y=history_df[col], name=col, mode='lines+markers'))
        
        # 벤치마크 추가
        if 'KOSPI_Relative' in history_df.columns:
            fig.add_trace(go.Scatter(x=history_df['Date'], y=history_df['KOSPI_Relative'], name='KOSPI 대비', 
                                     line=dict(dash='dash', color='gray')))
        
        fig.update_layout(xaxis_type='date', hovermode='x unified', title="투자 주체별 누적 성과")
        st.plotly_chart(fig, use_container_width=True)

# --- [5. 사이드바: 관리 메뉴 마스터 통합] ---
with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 전체 갱신"):
        st.cache_data.clear()
        st.rerun()
    
    st.divider()

    # (기능 1) 결과 확정 저장 로직 (타임머신 + 공백제거 포함)
    sel_date = st.date_input("📅 결과 저장 날짜 선택", value=datetime.now())
    if st.button(f"🚀 {sel_date} 결과 확정 저장"):
        try:
            save_date_str = sel_date.strftime('%Y-%m-%d')
            today_str = datetime.now().strftime('%Y-%m-%d')
            is_past = save_date_str < today_str
            
            with st.status(f"📡 {save_date_str} 데이터 수집 및 정밀 연산 중...") as status:
                # 1. KOSPI 수집
                k_t = yf.Ticker("^KS11")
                k_val = k_t.history(start=sel_date, end=sel_date + timedelta(days=1))['Close'].iloc[-1] if is_past else float(m_data['KOSPI']['val'].replace(',',''))
                
                # 2. 새 데이터 그릇 생성 (history_df 구조 복제)
                new_row = pd.Series(index=history_df.columns, dtype='object')
                new_row['Date'] = save_date_str
                new_row['KOSPI'] = k_val
                
                # 3. 계좌 및 종목 매핑 (KODEX 공백 제거 등 해결)
                for acc in full_df['계좌명'].unique():
                    acc_df = full_df[full_df['계좌명'] == acc]
                    a_buy = acc_df['매입금액'].sum()
                    a_eval = 0
                    
                    for _, row in acc_df.iterrows():
                        t_price = row['현재가']
                        ticker = str(row.get('종목코드','')).strip()
                        if is_past and ticker != 'nan':
                            h_p = yf.Ticker(ticker).history(start=sel_date, end=sel_date+timedelta(days=1))
                            if not h_p.empty: t_price = h_p['Close'].iloc[-1]
                        
                        a_eval += (t_price * row['수량'])
                        # 종목별 수익률 (공백 제거 로직)
                        clean_stock = row['종목명'].replace(' ', '').strip()
                        stock_col = f"{acc.replace('투자','')}_{clean_stock}수익률"
                        if stock_col in new_row.index:
                            new_row[stock_col] = ((t_price / row['매입단가']) - 1) * 100
                    
                    # 계좌별 수익률
                    acc_ret = ((a_eval / a_buy) - 1) * 100 if a_buy > 0 else 0
                    acc_col = f"{acc.replace('투자','')}수익률"
                    if acc_col in new_row.index: new_row[acc_col] = acc_ret

                # 4. 시트 병합 (Upsert: 같은 날짜는 덮어쓰기)
                hist_copy = history_df.copy()
                hist_copy['Date'] = hist_copy['Date'].dt.strftime('%Y-%m-%d')
                final_trend = pd.concat([hist_copy[hist_copy['Date'] != save_date_str], pd.DataFrame([new_row])], ignore_index=True)
                final_trend = final_trend.sort_values('Date').reset_index(drop=True)
                
                conn.update(worksheet="trend", data=final_trend)
                status.update(label=f"✅ {save_date_str} 저장 완료!", state="complete")
                st.success(f"{save_date_str} 데이터가 trend 시트에 성공적으로 업데이트되었습니다.")
                st.rerun()
        except Exception as e:
            st.error(f"❌ 저장 중 오류 발생: {e}")

    st.divider()

    # (기능 2) 52주 최고가 무한 자동화 (v36.97)
    if st.button("📈 52주 최고가 데일리 자동화"):
        if '종목코드' not in full_df.columns:
            st.error("⚠️ 시트에 '종목코드' 열이 없습니다.")
        else:
            try:
                with st.status("📡 전 종목 신고가 데이터 추적 중...") as status:
                    for idx, row in full_df.iterrows():
                        ticker = str(row['종목코드']).strip()
                        if ticker and ticker != 'nan':
                            stock_info = yf.Ticker(ticker).info
                            new_high = stock_info.get('fiftyTwoWeekHigh')
                            if new_high: full_df.at[idx, '52주최고가'] = new_high
                    conn.update(worksheet="종목 현황", data=full_df)
                    status.update(label="✅ 최고가 동기화 완료!", state="complete")
                st.success("전 종목의 52주 최고가가 실시간 금융 데이터로 업데이트되었습니다.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ 동기화 실패: {e}")
