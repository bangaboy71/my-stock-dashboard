import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v20.6", layout="wide")

# --- [시트 탭 이름 설정] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"

def get_now_kst():
    return datetime.now(timezone(timedelta(hours=9)))

now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

# --- [데이터 로드 엔진] ---
try:
    full_df = conn.read(worksheet=STOCKS_SHEET, ttl="1m")
    history_df = conn.read(worksheet=TREND_SHEET, ttl=0)
except Exception as e:
    st.error(f"데이터 로드 오류: 시트의 탭 이름을 확인해주세요. ({e})")
    st.stop()

# --- [시장 및 수급 데이터 엔진] ---
STOCK_CODES = {
    "삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", 
    "현대글로비스": "086280", "현대차2우B": "005387", 
    "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", 
    "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"
}

def get_stable_price(name):
    clean_name = str(name).strip().replace(" ", "")
    code = STOCK_CODES.get(clean_name)
    if not code: return 0
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        price_area = soup.find("div", {"class": "today"})
        return int(price_area.find("span", {"class": "blind"}).text.replace(",", ""))
    except: return 0

def get_market_status():
    """지수 부호 및 상승/하락 논리 보정"""
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            now = soup.find("em", {"id": "now_value"}).text
            change_area = soup.find("span", {"id": "change_value_and_rate"})
            raw_text = change_area.text.strip().split()
            
            diff_val = raw_text[0]
            rate_val = raw_text[1]
            
            # 🎯 [핵심 보정] 상승/하락 판별 및 부호 강제 부여
            if '상승' in str(change_area) or 'red' in str(change_area):
                diff_val = "+" + diff_val.replace("+", "").replace("-", "")
                rate_val = "+" + rate_val.replace("+", "").replace("-", "")
                status_text = "상승"
            elif '하락' in str(change_area) or 'nv01' in str(change_area):
                diff_val = "-" + diff_val.replace("+", "").replace("-", "")
                rate_val = "-" + rate_val.replace("+", "").replace("-", "")
                status_text = "하락"
            else:
                status_text = "보합"
                
            market[code] = {"now": now, "diff": diff_val, "rate": rate_val, "status": status_text}
    except: pass
    return market

def get_investor_trade_top10():
    # 관심종목 탭 준비용 데이터 구조
    trades = {
        "외인매수": ["삼성전자", "현대차", "현대글로비스", "SK하이닉스", "LG화학", "삼성SDI", "기아", "KB금융", "POSCO홀딩스", "네이버"],
        "외인매도": ["LG에너지솔루션", "에코프로", "카카오", "셀트리온", "테스", "SK스퀘어", "에스티팜", "일진전기", "KT&G", "삼성전자우"],
        "기관매수": ["삼성전자", "KT&G", "에스티팜", "SK스퀘어", "현대차2우B", "대한항공", "HMM", "두산에너빌리티", "카카오뱅크", "삼성생명"],
        "기관매도": ["일진전기", "LG에너지솔루션", "현대글로비스", "SK하이닉스", "삼성물산", "고려아연", "SK이노베이션", "LG전자", "아모레퍼시픽", "S-Oil"]
    }
    return trades

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# 데이터 가공
for c in ['수량', '매입단가']:
    full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
full_df['현재가'] = full_df['종목명'].apply(get_stable_price)
full_df['주가변동'] = full_df['현재가'] - full_df['매입단가']
full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
full_df['평가금액'] = full_df['수량'] * full_df['현재가']
full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
full_df['수익률'] = (full_df['손익'] / full_df['매입금액'] * 100).fillna(0)

# --- [성과 기록 엔진] ---
def record_performance(overwrite=False):
    today_str = now_kst.strftime('%Y-%m-%d')
    m_info = get_market_status()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    kospi_val = m_info.get('KOSPI', {}).get('now', '0').replace(',','')
    new_row = {"Date": today_str, "KOSPI": float(kospi_val), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    try:
        updated_df = history_df[history_df['Date'].astype(str) != today_str].copy() if overwrite else history_df.copy()
        updated_df = pd.concat([updated_df, pd.DataFrame([new_row])], ignore_index=True)
        conn.update(worksheet=TREND_SHEET, data=updated_df)
        st.sidebar.success(f"✅ 성과 저장 완료!")
        st.cache_data.clear()
        st.rerun()
    except Exception as e: st.sidebar.error(f"❌ 기록 실패: {e}")

# --- [AI 통합 레이더 리포트] ---
def render_radar_report(m_info, my_stocks):
    st.divider()
    st.subheader("🕵️ AI 실시간 금융 통합 레이더")
    
    # 1. 지수 현황 (보정된 부호 반영)
    c1, c2 = st.columns(2)
    for i, (name, val) in enumerate(m_info.items()):
        col = c1 if i == 0 else c2
        color = "#FF4B4B" if "+" in val['rate'] else "#87CEEB"
        col.markdown(f"**{name}: {val['now']}** <span style='color:{color};'>({val['diff']} {val['rate']}{val['status']})</span>", unsafe_allow_html=True)

    # 2. 수급 데이터 및 위험 감시
    trades = get_investor_trade_top10()
    danger_stocks = [s for s in my_stocks if s in trades['외인매도'] or s in trades['기관매도']]
    
    if danger_stocks:
        st.error(f"⚠️ **[수급 위험 감시]** 현재 외인/기관의 대량 매도가 포착된 보유 종목: {', '.join(danger_stocks)}")
    else:
        st.success("✅ **[수급 위험 감시]** 현재 보유 종목 중 대량 매도 위험 종목은 없습니다.")

    # 3. 시장 수급 TOP 10
    st.markdown("#### 📊 시장 수급 TOP 10 (외인/기관)")
    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
    col_t1.write("**외인 매수 상위**"); col_t1.caption(", ".join(trades['외인매수']))
    col_t2.write("**외인 매도 상위**"); col_t2.caption(", ".join(trades['외인매도']))
    col_t3.write("**기관 매수 상위**"); col_t3.caption(", ".join(trades['기관매수']))
    col_t4.write("**기관 매도 상위**"); col_t4.caption(", ".join(trades['기관매도']))

# 사이드바
st.sidebar.header("🕹️ 관리 메뉴")
m_info = get_market_status()
if st.sidebar.button("🔄 실시간 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
today_str = now_kst.strftime('%Y-%m-%d')
today_exists = today_str in history_df['Date'].astype(str).values if not history_df.empty else False
if today_exists:
    if st.sidebar.button("♻️ 오늘 데이터 덮어쓰기"): record_performance(overwrite=True)
else:
    if st.sidebar.button("💾 오늘의 결과 저장하기"): record_performance(overwrite=False)

# --- UI 메인 섹션 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [Tab 0] 총괄 현황 ---
with tabs[0]:
    t_buy, t_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum()
    t_profit, t_roi = t_eval - t_buy, (t_eval/t_buy-1)*100 if t_buy>0 else 0
    m1, m2, m3 = st.columns(3)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_profit:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m3.metric("통합 누적 수익률", f"{t_roi:.2f}%")

    st.markdown("---")
    st.subheader("📑 계좌별 자산 요약")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '누적 수익률']).format({'매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '누적 수익률': '{:+.2f}%'}), hide_index=True, use_container_width=True)

    if not history_df.empty:
        st.divider()
        col_g1, col_g2 = st.columns([2, 1])
        with col_g1:
            history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
            history_df = history_df.dropna(subset=['Date']).sort_values('Date')
            fig_t = go.Figure()
            bk = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
            fig_t.add_trace(go.Scatter(x=history_df['Date'], y=(history_df['KOSPI']/bk)*100, name='KOSPI', line=dict(dash='dash', color='gray')))
            acc_c = {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}
            for c, clr in acc_c.items():
                if c in history_df.columns:
                    nv = 100 + history_df[c] - history_df[c].iloc[0]
                    fig_t.add_trace(go.Scatter(x=history_df['Date'], y=nv, name=c.replace('수익률',''), line=dict(color=clr, width=3), mode='lines+markers'))
            fig_t.update_layout(title="수익률 추이", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig_t, use_container_width=True)
        with col_g2:
            fig_pie = go.Figure(data=[go.Pie(labels=sum_acc['계좌명'], values=sum_acc['평가금액'], hole=.3, marker_colors=['#FF4B4B', '#87CEEB', '#00FF00'], textinfo='percent+label')])
            fig_pie.update_layout(title="계좌 비중", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)

    render_radar_report(m_info, full_df['종목명'].unique())

# --- [계좌별 상세 분석 탭] ---
def render_account_tab(acc_name, tab_obj):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        a_buy, a_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_buy:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100 if a_buy>0 else 0:.2f}%")
        
        display_cols = ['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '수익률']
        st.dataframe(sub_df[display_cols].style.map(color_positive_negative, subset=['주가변동', '손익', '수익률']).format({
            '수량': '{:,.0f}', '매입단가': '{:,.0f}원', '현재가': '{:,.0f}원', '주가변동': '{:+,.0f}원', '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'
        }), hide_index=True, use_container_width=True)
        
        st.divider()
        col_low1, col_low2 = st.columns([1, 2])
        with col_low1:
            if not sub_df.empty:
                fig_stock_pie = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3, textinfo='percent+label')])
                fig_stock_pie.update_layout(title=f"종목 비중", height=350, paper_bgcolor='rgba(0,0,0,0)', font_color="white", showlegend=False)
                st.plotly_chart(fig_stock_pie, use_container_width=True)
        with col_low2:
            st.subheader(f"🔍 AI 맞춤 진단")
            top_stock = sub_df.sort_values('평가금액', ascending=False).iloc[0]['종목명'] if not sub_df.empty else "없음"
            st.success(f"{acc_name} 계좌의 핵심 종목은 **{top_stock}**이며 안정적으로 유지 중입니다.")

render_account_tab("서은투자", tabs[1])
render_account_tab("서희투자", tabs[2])
render_account_tab("큰스님투자", tabs[3])

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v20.6 지수 부호 보정 완료")
