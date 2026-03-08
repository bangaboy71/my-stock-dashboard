import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 UI 스타일 (v36.5 원형 100% 복구)
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.39", layout="wide")

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

# --- [2. 엔진 및 헬퍼 함수: RESEARCH_DATA 전체 업데이트] ---
RESEARCH_DATA = {
    "삼성전자": {"metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("특별 DPS", "500원", "3.5~7천원")], "implications": ["HBM3E 양산 본격화", "특별 배당 기반 강력 환원"]},
    "KT&G": {"metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("자사주 소각", "0.9조", "0.5~1.1조")], "implications": ["NGP 성장 동력 확보", "발행주식 20% 소각 가속화"]},
    "테스": {"metrics": [("영업이익률", "10.7%", "19.0%"), ("ROE", "6.2%", "14.5%"), ("정규 DPS", "500원", "700~900원")], "implications": ["선단공정 장비 수요 폭증", "ROE 14.5% 달성 전망"]},
    
    # 🎯 신규 추가 종목 (2026 시장 전망 반영)
    "LG에너지솔루션": {
        "metrics": [("수주잔고", "450조", "520조+"), ("영업이익률", "5.2%", "8.5%"), ("4680 양산", "준비", "본격화")],
        "implications": ["4680 배터리 테슬라 공급 개시", "ESS 부문 매출 비중 확대"]
    },
    "현대글로비스": {
        "metrics": [("PCTC 선복량", "90척", "110척"), ("영업이익률", "6.5%", "7.2%"), ("배당성향", "25%", "35%")],
        "implications": ["완성차 해상운송 1위 굳히기", "수소 물류 인프라 선점"]
    },
    "현대차2우B": {
        "metrics": [("배당수익률", "7.5%", "9.2%"), ("하이브리드 비중", "12%", "20%"), ("ROE", "11%", "13%")],
        "implications": ["분기 배당 및 자사주 매입 강화", "믹스 개선을 통한 수익성 방어"]
    },
    "KODEX200타겟위클리커버드콜": {
        "metrics": [("목표 분배율", "연 12%", "월 1%↑"), ("옵션 프리미엄", "안정", "최적화"), ("지수 추종", "95%", "98%")],
        "implications": ["매주 옵션 매도를 통한 현금 흐름", "횡보장에서 코스피 대비 초과 수익"]
    },
    "에스티팜": {
        "metrics": [("올리고 매출", "2.1천억", "3.5천억"), ("영업이익률", "12%", "18%"), ("공장 가동률", "70%", "95%")],
        "implications": ["mRNA 원료 공급 글로벌 확장", "제2 올리고동 본격 가동 효과"]
    },
    "일진전기": {
        "metrics": [("초고압 변압기", "수주잔고↑", "북미 점유율↑"), ("영업이익률", "7%", "10%"), ("ROE", "14%", "18%")],
        "implications": ["미국 전력망 교체 사이클 수혜", "변압기 증설 라인 가동 개시"]
    },
    "SK스퀘어": {
        "metrics": [("NAV 할인율", "65%", "45%"), ("하이닉스 지분", "20.1%", "가치 재평가"), ("주주환원", "0.3조", "0.6조")],
        "implications": ["자사주 소각 등 적극적 가치 제고", "반도체 포트폴리오 중심 성장"]
    }
}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def get_market_indices():
    try:
        url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
        soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
        val = soup.find("em", {"id": "now_value"}).text
        return float(val.replace(',', ''))
    except: return 0.0

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

# --- [3. 데이터 로드 및 정제] ---
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

# --- [3. 데이터 로드 및 정제 부문 교체] ---
if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    
    # [실행 순서 준수]
# 1. 기초 값 산출 (매입/평가금액이 먼저 계산되어야 합니다)
full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
full_df['평가금액'] = full_df['수량'] * full_df['현재가']
full_df['손익'] = full_df['평가금액'] - full_df['매입금액']

# 2. 일일 변동 지표 산출
full_df['전일대비손익'] = full_df['평가금액'] - (full_df['수량'] * full_df['전일종가'])
full_df['전일평가액'] = full_df['평가금액'] - full_df['전일대비손익']
full_df['전일대비변동율'] = (full_df['전일대비손익'] / full_df['전일평가액'].replace(0, float('nan')) * 100).fillna(0)

# 3. 누적 성과 지표 산출
full_df['누적수익률'] = (full_df['손익'] / full_df['매입금액'].replace(0, float('nan')) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], errors='coerce')
    # 🎯 [해결 1] 가상 행 절대 생성 금지 및 시트 날짜만 사용
    history_df = history_df.dropna(subset=['Date']).sort_values('Date').drop_duplicates('Date', keep='last').reset_index(drop=True)
    
    # KOSPI 3/3 기준 정규화 (추이 분석용)
    base_date = pd.Timestamp("2026-03-03")
    base_row = history_df[history_df['Date'] == base_date]
    if not base_row.empty:
        history_df['KOSPI_Relative'] = (history_df['KOSPI'] / base_row['KOSPI'].values[0] - 1) * 100
    else:
        history_df['KOSPI_Relative'] = (history_df['KOSPI'] / (history_df['KOSPI'].iloc[0] if not history_df.empty else 1) - 1) * 100

# --- [4. 지능형 열 매칭 세이프가드 (핵심 수정)] ---
def find_matching_col(df, account, stock=None):
    # '투자'를 제거한 순수 이름 (서은, 서희, 큰스님)
    prefix = account.replace("투자", "").replace(" ", "")
    if stock:
        # 패턴: "서은_삼성전자수익률"
        target_clean = f"{prefix}{stock}수익률".replace(" ", "").replace("_", "")
    else:
        # 패턴: "서은수익률"
        target_clean = f"{prefix}수익률".replace(" ", "").replace("_", "")
    
    for col in df.columns:
        # 시트 헤더의 공백/언더바 제거 후 비교
        sheet_col_clean = str(col).replace(" ", "").replace("_", "").replace("투자", "")
        if target_clean == sheet_col_clean: return col
    return None

# --- [5. 사이드바 관리 메뉴 (영구 기능 고정)] ---
with st.sidebar:
    st.header("⚙️ 관리 메뉴")
    if st.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
    st.divider()
    st.subheader("💾 데이터 저장 (날짜 선택)")
    sel_date = st.date_input("결과를 저장할 날짜 확정", value=pd.Timestamp("2026-03-06"))
    if st.button(f"{sel_date} 결과 확정 및 저장"):
        save_ts = pd.Timestamp(sel_date)
        original_cols = [c for c in history_df.columns if c != 'KOSPI_Relative']
        new_row = pd.Series(index=original_cols, dtype='object')
        new_row['Date'] = save_ts
        new_row['KOSPI'] = get_market_indices()
        
        # 1. 계좌별 수익률 (서은수익률 등) 매칭
        acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
        for acc in ['서은투자', '서희투자', '큰스님투자']:
            col = find_matching_col(history_df, acc)
            if col: new_row[col] = float(acc_sum.get(acc, 0))
        
        # 2. 계좌_종목별 수익률 매칭
        for _, row in full_df.iterrows():
            col = find_matching_col(history_df, row['계좌명'], row['종목명'])
            if col: new_row[col] = float(row['누적수익률'])
            
        # 🎯 [해결 2] 전체 데이터 덮어쓰기로 누락 원천 차단
        final_history = pd.concat([history_df[original_cols][history_df['Date'] != save_ts], pd.DataFrame([new_row])]).sort_values('Date').reset_index(drop=True)
        conn.update(worksheet="trend", data=final_history)
        st.cache_data.clear(); st.success(f"✅ {sel_date} 수익률이 시트에 저장되었습니다!"); st.rerun()

# --- [6. UI 메인 구성: 총괄 탭 및 개별 탭 호출] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v36.43</h1>", unsafe_allow_html=True)

# 탭 생성 (총 4개)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# --- [6. UI 메인 구성: Tabs[0] 내부 테이블 부문 교체] ---
with tabs[0]:
    # 상단 지표 (v36.43/44 로직 유지)
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
    
    # 계좌별 요약 테이블 구성
    sum_acc = full_df.groupby('계좌명').agg({
        '매입금액': 'sum',
        '평가금액': 'sum',
        '손익': 'sum',
        '전일대비손익': 'sum'
    }).reset_index()
    
    # 추가 지표 계산
    sum_acc['전일평가액'] = sum_acc['평가금액'] - sum_acc['전일대비손익']
    sum_acc['전일대비변동율'] = (sum_acc['전일대비손익'] / sum_acc['전일평가액'].replace(0, float('nan')) * 100).fillna(0)
    sum_acc['누적수익률'] = (sum_acc['손익'] / sum_acc['매입금액'].replace(0, float('nan')) * 100).fillna(0)
    
    # 🎯 열 순서 조정: 손익과 누적수익률 사이에 전일 지표 삽입
    sum_acc = sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비손익', '전일대비변동율', '누적수익률']]
    
    # 음양 색채 적용 스타일링
    st.dataframe(
        sum_acc.style.apply(lambda x: [
            'color: #FF4B4B' if (i >= 3 and val > 0) else 'color: #87CEEB' if (i >= 3 and val < 0) else '' 
            for i, val in enumerate(x)
        ], axis=1).format({
            '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원',
            '전일대비손익': '{:+,.0f}원', '전일대비변동율': '{:+.2f}%', '누적수익률': '{:+.2f}%'
        }),
        use_container_width=True, hide_index=True
    )
    
    # --- 이하 그래프 코드는 기존 v36.43 유지 ---
    if not history_df.empty:
        fig = go.Figure()
        h_dates = history_df['Date'].dt.date.astype(str)
        fig.add_trace(go.Scatter(x=h_dates, y=history_df['KOSPI_Relative'], name='KOSPI (3/3 기준)', line=dict(dash='dash', color='gray')))
        for acc in ['서은투자', '서희투자', '큰스님투자']:
            col = find_matching_col(history_df, acc)
            if col: fig.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col))
        fig.update_layout(title="📈 통합 실제 수익률 추이 (시트 기록 기준)", yaxis_title="누적수익률 (%)", xaxis=dict(type='category'), height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig, use_container_width=True)

# --- [7. 투자 주체별 상세 렌더링 함수 정의] ---
def render_account_tab(acc_name, tab_obj, history_col_key):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty:
            st.warning(f"{acc_name}에 해당하는 데이터가 없습니다.")
            return
        
        # 지표 계산
        a_buy = sub_df['매입금액'].sum()
        a_eval = sub_df['평가금액'].sum()
        a_prev_eval = (sub_df['수량'] * sub_df['전일종가']).sum()
        a_change_amt = a_eval - a_prev_eval
        a_change_pct = (a_change_amt / a_prev_eval * 100) if a_prev_eval != 0 else 0
        
        # 상단 4대 지표 (누적손익 변동 표기 삭제 버전)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", delta=f"{a_change_amt:+,.0f}원 ({a_change_pct:+.2f}%)")
        c2.metric("매입액", f"{a_buy:,.0f}원")
        c3.metric("손익", f"{a_eval-a_buy:+,.0f}원") # 변동 표기 삭제
        c4.metric("누적수익률", f"{(a_eval/a_buy-1)*100:+.2f}%", delta=f"{a_change_pct:+.2f}%p")
        
       # --- [7. render_account_tab 함수 내 테이블 출력 부문 교체] ---
        # 🎯 열 순서: 평가금액과 누적수익률 사이에 손익, 전일대비손익, 전일대비변동율 삽입
        display_cols = ['종목명', '수량', '매입단가', '매입금액', '현재가', '평가금액', '손익', '전일대비손익', '전일대비변동율', '누적수익률']
        
        # 음양 색채 적용 스타일링 (손익 관련 4개 열)
        st.dataframe(
            sub_df[display_cols].style.apply(lambda x: [
                'color: #FF4B4B' if (i >= 6 and val > 0) else 'color: #87CEEB' if (i >= 6 and val < 0) else '' 
                for i, val in enumerate(x)
            ], axis=1).format({
                '수량': '{:,.0f}', 
                '매입단가': '{:,.0f}원', 
                '매입금액': '{:,.0f}원', 
                '현재가': '{:,.0f}원', 
                '평가금액': '{:,.0f}원', 
                '손익': '{:+,.0f}원',
                '전일대비손익': '{:+,.0f}원', 
                '전일대비변동율': '{:+.2f}%', 
                '누적수익률': '{:+.2f}%'
            }), 
            hide_index=True, 
            use_container_width=True
        )
        
        st.divider()
        # 🎯 중복 키 방지를 위해 key에 acc_name 반영
        sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_widget_{acc_name}")
        
        # 리서치 데이터 출력
        res = RESEARCH_DATA.get(sel.replace(" ", ""))
        if res:
            rows = "".join([f"<tr><td>{m[0]}</td><td>{m[1]}</td><td class='target-val'>{m[2]}</td></tr>" for m in res['metrics']])
            st.markdown(f"<div class='insight-card'><div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브</div><div class='insight-flex'><div class='insight-left'><table class='research-table'><thead><tr><th>지표</th><th>25년 추정</th><th>26년 Target</th></tr></thead><tbody>{rows}</tbody></table></div><div class='insight-right'>💡 {res['implications'][0]}</div></div></div>", unsafe_allow_html=True)

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

        st.divider(); r_l, r_r = st.columns(2)
        with r_l: st.markdown(f"<div class='report-box'><h4>📋 {acc_name} 계좌 총평</h4><p>Target 달성 보유 지속.</p></div>", unsafe_allow_html=True)
        with r_r: st.markdown("<div class='report-box'><h4>🌍 업황 대응 전략</h4><p>시장 변동성 모니터링 중.</p></div>", unsafe_allow_html=True)

# --- [8. 각 탭에 함수 호출 (중복 주의)] ---
render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"v36.43 가디언 프리시전 클린-업 | {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")








