import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v25.9", layout="wide")

# --- [시트 및 시간 설정] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

# --- [헬퍼 함수] ---
def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# --- [데이터 로드 엔진] ---
try:
    full_df = conn.read(worksheet=STOCKS_SHEET, ttl="1m")
    history_df = conn.read(worksheet=TREND_SHEET, ttl=0)
    if not history_df.empty:
        history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
        history_df = history_df.dropna(subset=['Date']).sort_values('Date')
except Exception as e:
    st.error(f"데이터 로드 오류: {e}")
    st.stop()

# --- [시장 지수 및 시세 엔진] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_stock_data(name):
    clean_name = str(name).replace(" ", "").strip()
    code = STOCK_CODES.get(clean_name)
    if not code: return 0, 0
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        now_price = int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
        prev_price = int(soup.find("td", {"class": "first"}).find("span", {"class": "blind"}).text.replace(",", ""))
        return now_price, prev_price
    except: return 0, 0

def get_market_status():
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            now_val = soup.find("em", {"id": "now_value"}).text
            change_area = soup.find("span", {"id": "change_value_and_rate"})
            raw = change_area.text.strip().split()
            diff, rate = raw[0].replace("상승","").replace("하락","").strip(), raw[1].replace("상승","").replace("하락","").strip()
            if 'red02' in str(change_area) or '+' in diff: diff, rate = "+" + diff.replace("+",""), "+" + rate.replace("+","")
            elif 'nv01' in str(change_area) or '-' in diff: diff, rate = "-" + diff.replace("-",""), "-" + rate.replace("-","")
            market[code] = {"now": now_val, "diff": diff, "rate": rate}
    except: pass
    return market

# --- [데이터 전처리] ---
for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

prices_list = full_df['종목명'].apply(get_stock_data).tolist()
full_df['현재가'] = [p[0] for p in prices_list]
full_df['전일종가'] = [p[1] for p in prices_list]

full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
full_df['평가금액'] = full_df['수량'] * full_df['현재가']
full_df['전일평가금액'] = full_df['수량'] * full_df['전일종가']
full_df['주가변동'] = full_df['현재가'] - full_df['매입단가']
full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)
full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

# --- [성과 기록 함수: 보정 완료] ---
def record_performance(overwrite=False):
    today_str = now_kst.strftime('%Y-%m-%d')
    m_info = get_market_status()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    
    def get_stock_yield(acc, stock):
        row = full_df[(full_df['계좌명']==acc) & (full_df['종목명'].str.replace(' ', '') == stock.replace(' ', ''))]
        return row.iloc[0]['수익률'] if not row.empty else None # 존재하지 않으면 None

    kospi_now = m_info.get('KOSPI', {}).get('now', '0').replace(',','')
    new_row = {"Date": today_str, "KOSPI": float(kospi_now), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    
    # 🎯 핵심 보정: 시트에 이미 존재하는 열 이름(S열~AI열 방지)만 찾아서 데이터 매칭
    for col in history_df.columns:
        if "수익률" in col and "_" in col:
            # 예: "서은_삼성전자수익률" -> acc: "서은투자", stock: "삼성전자"
            parts = col.split("_")
            acc_part = parts[0] + "투자"
            stock_part = parts[1].replace("수익률", "")
            
            y = get_stock_yield(acc_part, stock_part)
            if y is not None:
                new_row[col] = y

    try:
        updated_df = pd.concat([history_df[history_df['Date'].dt.strftime('%Y-%m-%d') != today_str], pd.DataFrame([new_row])], ignore_index=True)
        # 시트의 원래 열 순서 유지
        updated_df = updated_df[history_df.columns]
        conn.update(worksheet=TREND_SHEET, data=updated_df)
        st.sidebar.success("✅ 저장 완료!"); st.cache_data.clear(); st.rerun()
    except Exception as e: st.sidebar.error(f"❌ 실패: {e}")

# --- [사이드바 관리 메뉴] ---
st.sidebar.header("🕹️ 관리 메뉴")
if st.sidebar.button("🔄 실시간 데이터 갱신"): st.cache_data.clear(); st.rerun()
st.sidebar.divider()
today_str = now_kst.strftime('%Y-%m-%d')
today_exists = any(history_df['Date'].dt.strftime('%Y-%m-%d') == today_str) if not history_df.empty else False
if today_exists:
    if st.sidebar.button("♻️ 오늘 데이터 덮어쓰기"): record_performance(overwrite=True)
else:
    if st.sidebar.button("💾 오늘의 결과 저장하기"): record_performance(overwrite=False)

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v25.9</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    m_info = get_market_status()
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    t_prev_eval = full_df['전일평가금액'].sum()
    total_daily_rate = ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원 (전일대비)")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{total_daily_rate:+.2f}% (전일대비)")
    
    st.markdown("---")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

    if not history_df.empty:
        st.divider()
        fig_t = go.Figure()
        bk_kospi = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        kospi_yield = ((history_df['KOSPI'] / bk_kospi) - 1) * 100
        fig_t.add_trace(go.Scatter(x=history_df['Date'], y=kospi_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns:
                fig_t.add_trace(go.Scatter(x=history_df['Date'], y=history_df[col], name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig_t.update_layout(title="📈 가족 자산 통합 수익률 추이 (vs KOSPI)", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", xaxis=dict(tickformat="%Y-%m-%d"), yaxis=dict(ticksuffix="%"))
        st.plotly_chart(fig_t, use_container_width=True)

# [계좌별 상세 분석 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        a_prev_eval = sub_df['전일평가금액'].sum()
        a_daily_rate = ((a_eval / a_prev_eval - 1) * 100) if a_prev_eval > 0 else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_prev_eval:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100 if a_buy>0 else 0:.2f}%", f"{a_daily_rate:+.2f}%")
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '전일대비(%)', '수익률']].style.map(color_positive_negative, subset=['주가변동', '손익', '전일대비(%)', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원', '매입금액': '{:,.0f}원', 
            '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)
        
        st.divider()
        col_c1, col_c2 = st.columns([2, 1])
        with col_c1:
            available_stocks = sub_df['종목명'].unique().tolist()
            num_stocks = len(available_stocks)
            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=history_df['Date'], y=history_df[history_col], mode='lines+markers', name='계좌 전체 수익률', line=dict(color='#87CEEB', width=4)))
                bk_kospi = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
                kospi_yield = ((history_df['KOSPI'] / bk_kospi) - 1) * 100
                fig.add_trace(go.Scatter(x=history_df['Date'], y=kospi_yield, mode='lines', name='KOSPI 지수', line=dict(color='gray', width=2, dash='dash')))
                if num_stocks > 1:
                    selected_stock = st.selectbox(f"📍 {acc_name} 대조 종목 선택", available_stocks, key=f"sel_{acc_name}")
                    short_acc = acc_name.replace("투자", "")
                    target_stock_name = selected_stock.replace(' ', '')
                    history_stock_col = ""
                    for col in history_df.columns:
                        if f"{short_acc}_" in col and target_stock_name in col.replace(' ', ''):
                            history_stock_col = col; break
                    if history_stock_col:
                        fig.add_trace(go.Scatter(x=history_df['Date'], y=history_df[history_stock_col], mode='lines', name=f'{selected_stock} 수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                    fig.update_layout(title=f"📈 {acc_name} 성과분석 레이더 (종목 대조)")
                else:
                    fig.update_layout(title=f"📈 {acc_name} 누적 수익률 추이 ({available_stocks[0]})")
                fig.update_layout(xaxis=dict(tickformat="%Y-%m-%d"), yaxis=dict(ticksuffix="%"), height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
        with col_c2:
            if not sub_df.empty:
                fig_pie = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
                fig_pie.update_layout(title="💰 자산 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
                st.plotly_chart(fig_pie, use_container_width=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v25.9 불필요 컬럼 생성 원천 차단")
