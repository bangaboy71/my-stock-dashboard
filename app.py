import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v24.9", layout="wide")

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

# --- [시장 지수 및 시세 엔진 (v24.2 베이스)] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_price(name):
    clean_name = str(name).replace(" ", "").strip()
    code = STOCK_CODES.get(clean_name)
    if not code: return 0
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        return int(soup.find("div", {"class": "today"}).find("span", {"class": "blind"}).text.replace(",", ""))
    except: return 0

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

# --- [성과 기록 함수] ---
def record_performance(overwrite=False):
    today_str = now_kst.strftime('%Y-%m-%d')
    m_info = get_market_status()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    
    def get_stock_yield(acc, stock):
        row = full_df[(full_df['계좌명']==acc) & (full_df['종목명'].str.contains(stock))]
        return row.iloc[0]['수익률'] if not row.empty else 0

    kospi_now = m_info.get('KOSPI', {}).get('now', '0').replace(',','')
    new_row = {
        "Date": today_str, "KOSPI": float(kospi_now), 
        "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)
    }
    for stock in STOCK_CODES.keys():
        new_row[f"서은_{stock}수익률"] = get_stock_yield('서은투자', stock)
        new_row[f"서희_{stock}수익률"] = get_stock_yield('서희투자', stock)
        new_row[f"큰스님_{stock}수익률"] = get_stock_yield('큰스님투자', stock)

    try:
        updated_df = history_df[history_df['Date'].dt.strftime('%Y-%m-%d') != today_str].copy() if overwrite else history_df.copy()
        updated_df = pd.concat([updated_df, pd.DataFrame([new_row])], ignore_index=True)
        conn.update(worksheet=TREND_SHEET, data=updated_df)
        st.sidebar.success(f"✅ 성과 저장 완료!")
        st.cache_data.clear(); st.rerun()
    except Exception as e: st.sidebar.error(f"❌ 기록 실패: {e}")

# 데이터 가공
for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
full_df['현재가'] = full_df['종목명'].apply(get_price)
full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
full_df['평가금액'] = full_df['수량'] * full_df['현재가']
full_df['주가변동'] = full_df['현재가'] - full_df['매입단가']
full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
full_df['수익률'] = (full_df['손익'] / full_df['매입금액'] * 100).fillna(0)

# 사이드바
st.sidebar.header("🕹️ 관리 메뉴")
if st.sidebar.button("🔄 실시간 시세 갱신"):
    st.cache_data.clear(); st.rerun()
st.sidebar.divider()
today_str = now_kst.strftime('%Y-%m-%d')
today_exists = any(history_df['Date'].dt.strftime('%Y-%m-%d') == today_str) if not history_df.empty else False
if today_exists:
    if st.sidebar.button("♻️ 오늘 데이터 덮어쓰기"): record_performance(overwrite=True)
else:
    if st.sidebar.button("💾 오늘의 결과 저장하기"): record_performance(overwrite=False)

# UI 메인
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황
with tabs[0]:
    m_info = get_market_status()
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_buy:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%")
    st.markdown("---")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '누적 수익률']).format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적 수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)
    
    if not history_df.empty:
        st.divider()
        col_g1, col_g2 = st.columns([2, 1])
        with col_g1:
            fig_t = go.Figure()
            bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
            fig_t.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
            acc_colors = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
            for col, color in acc_colors.items():
                if col in history_df.columns:
                    fig_t.add_trace(go.Scatter(x=history_df['Date'], y=100 + history_df[col], name=col.replace('수익률',''), line=dict(color=color, width=3)))
            fig_t.update_layout(title="📈 가족 자산 통합 성장 추이", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", xaxis=dict(tickformat="%Y-%m-%d"))
            st.plotly_chart(fig_t, use_container_width=True)
        with col_g2:
            fig_pie = go.Figure(data=[go.Pie(labels=sum_acc['계좌명'], values=sum_acc['평가금액'], hole=.3, marker_colors=['#FF4B4B', '#87CEEB', '#00FF00'], textinfo='percent+label')])
            fig_pie.update_layout(title="💰 계좌별 자산 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)

    st.divider()
    st.subheader("🕵️ AI 실시간 시장 모니터링 리포트")
    c_idx1, c_idx2 = st.columns(2)
    with c_idx1:
        v = m_info.get('KOSPI', {})
        st.markdown(f"**KOSPI: {v.get('now','-')}** | <span style='color:{'#FF4B4B' if '+' in v.get('rate','') else '#87CEEB'};'>{v.get('diff','')} ({v.get('rate','')})</span>", unsafe_allow_html=True)
    with c_idx2:
        v = m_info.get('KOSDAQ', {})
        st.markdown(f"**KOSDAQ: {v.get('now','-')}** | <span style='color:{'#FF4B4B' if '+' in v.get('rate','') else '#87CEEB'};'>{v.get('diff','')} ({v.get('rate','')})</span>", unsafe_allow_html=True)

# [계좌별 상세 분석 탭]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_buy:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100 if a_buy>0 else 0:.2f}%")
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '수익률']].style.map(color_positive_negative, subset=['주가변동', '손익', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원', '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)
        
        st.divider()
        col_c1, col_c2 = st.columns([2, 1])
        with col_c1:
            # 🎯 고도화: 모든 계좌에 종목 선택 메뉴 적용
            available_stocks = sub_df['종목명'].unique().tolist()
            selected_stock = st.selectbox(f"📍 {acc_name} 대조 종목 선택", available_stocks, key=f"sel_{acc_name}")
            
            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=history_df['Date'], y=history_df[history_col], mode='lines+markers', name='계좌 전체 수익률', line=dict(color='#87CEEB', width=3)))
                
                short_acc = acc_name.replace("투자", "")
                history_stock_col = f"{short_acc}_{selected_stock.replace(' ', '')}수익률"
                
                if history_stock_col in history_df.columns:
                    fig.add_trace(go.Scatter(x=history_df['Date'], y=history_df[history_stock_col], mode='lines', name=f'{selected_stock} 수익률', line=dict(color='#FF4B4B', width=2, dash='dot')))
                
                fig.update_layout(title=f"📈 {acc_name} 성과분석 레이더", xaxis=dict(tickformat="%Y-%m-%d"), yaxis=dict(ticksuffix="%"), height=400, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
        with col_c2:
            if not sub_df.empty:
                fig_pie = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
                fig_pie.update_layout(title="💰 자산 비중", height=400, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
                st.plotly_chart(fig_pie, use_container_width=True)

        top_name = sub_df.sort_values('평가금액', ascending=False).iloc[0]['종목명'] if not sub_df.empty else "없음"
        st.success(f"🔍 **AI 진단 리포트:** {acc_name} 계좌는 현재 **{top_name}**의 비중이 가장 높으며 안정적으로 관리되고 있습니다.")

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v24.9 전 계좌 종목 분석 통합")
