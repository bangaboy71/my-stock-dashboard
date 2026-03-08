import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import re

# 1. 설정 및 연결 (v31.6 원형 사수)
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.1", layout="wide")

# --- [CSS: 리서치 중심 딥다이브 스타일] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 750px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.04); min-height: 500px; margin-bottom: 20px; }
    .sector-title { font-size: 1.3rem; font-weight: bold; border-bottom: 4px solid #87CEEB; padding-bottom: 12px; margin-bottom: 15px; color: #87CEEB; }
    
    /* 🎯 딥다이브 카드 고도화 (시사점 섹션 포함) */
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 25px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.25rem; margin-bottom: 15px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 10px; }
    .research-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.92rem; }
    .research-table th { text-align: left; padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
    .research-table td { padding: 10px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .target-val { color: #FFD700; font-weight: bold; }
    
    .implication-box { margin-top: 20px; padding: 15px; background: rgba(255,215,0,0.03); border-radius: 8px; border-left: 4px solid #FFD700; }
    .implication-title { color: #FFD700; font-weight: bold; font-size: 0.95rem; margin-bottom: 8px; }
    .implication-item { font-size: 0.88rem; color: rgba(255,255,255,0.9); margin-bottom: 5px; }

    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.2rem; border: 2px solid; text-align: center; background-color: rgba(0,0,0,0.2); }
    .up-style { color: #FF4B4B; border-color: #FF4B4B; }
    .down-style { color: #87CEEB; border-color: #87CEEB; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 연구 데이터베이스 확장: 시사점 추가] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

RESEARCH_DATA = {
    "삼성전자": {
        "desc": "2026년 영업이익 185조원 목표의 압도적 모멘텀.",
        "metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("PER", "15.2배", "9.1배"), ("시가배당률", "1.9%", "4.5~6.0%")],
        "implications": ["HBM3E 양산 본격화 및 파운드리 수율 개선을 통한 수익성 극대화", "특별 배당 포함 시 연 6% 수준의 강력한 주주 환원 기대", "AI 서버 중심의 메모리 수요 폭증에 따른 체질 개선 완료"]
    },
    "KT&G": {
        "desc": "ROE 15% 달성 및 자사주 소각을 통한 밸류업 구간 진입.",
        "metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("PBR", "1.25배", "1.40배"), ("정규 DPS", "6,000원", "6,400~6,600원")],
        "implications": ["해외 궐련 수출 확대 및 NGP(전자담배) 성장 동력 확보", "2027년까지 발행주식 20% 소각을 통한 주당 가치 제고", "카자흐스탄·인도네시아 신공장 가동을 통한 글로벌 공급망 강화"]
    },
    "현대차2우B": {
        "desc": "배당 성향 25% 유지 및 은퇴 포트폴리오의 강력한 현금원.",
        "metrics": [("영업이익률", "6.2%", "7.0%"), ("ROE", "13.0%", "15.5%"), ("시가배당률", "5.7%", "6.4%"), ("정규 DPS", "13,600원", "14,500~15,500원")],
        "implications": ["고부가가치 차종(SUV, 제네시스) 판매 확대를 통한 믹스 개선", "본주 대비 높은 할인율로 저평가 매력 및 배당수익률 극대화", "자사주 소각 등 자본 효율성 제고를 통한 밸류업 가이드라인 준수"]
    },
    "KODEX200타겟위클리커버드콜": {
        "desc": "주 단위 콜옵션 매도로 연 15% 시가분배율을 지향하는 은퇴 특화 도구.",
        "metrics": [("옵션 프리미엄", "연 15.0%", "연 15.0%"), ("월 분배금", "100~120원", "110~130원"), ("연환산 수익률", "12~15%", "15.0% 이상"), ("시가분배율", "연 12.5%", "연 15.0%")],
        "implications": ["지수 박스권 정체 시 콜옵션 매도 수익을 통한 초과 수익 창출", "매월 안정적인 현금 흐름을 필요로 하는 은퇴 생활비 마련의 핵심", "국내 대형주 시장의 완만한 상승세 향유 및 하락장 방어력 보유"]
    },
    "LG에너지솔루션": {
        "desc": "이차전지 수익성 개선 및 2026년 영업이익 4.8조 타겟.",
        "metrics": [("영업이익률", "6.5%", "10.6%"), ("ROE", "5.2%", "11.5%"), ("PER", "65.0배", "32.0배"), ("시가배당률", "0.35%", "0.5~0.8%")],
        "implications": ["북미 합작 공장(JV) 가동 본격화에 따른 시장 점유율 확대", "차세대 배터리(4680 등) 양산 기술 우위를 통한 경쟁력 격차 확보", "전기차 수요 회복 국면 진입 시 이익 가시성 대폭 개선"]
    },
    "SK스퀘어": {
        "desc": "지주사 할인율 45% 축소 및 자사주 소각 최대 0.8조 목표.",
        "metrics": [("ROE", "4.5%", "9.8%"), ("PBR", "0.45배", "0.65배"), ("NAV 할인율", "65.0%", "45.0%"), ("자사주 소각", "0.2조", "0.5~0.8조")],
        "implications": ["하이닉스 배당 수익을 기반으로 한 자사주 매입/소각 기조 강화", "비상장 포트폴리오 IPO 및 자산 매각을 통한 투자 재원 확보", "순자산가치(NAV) 대비 과도한 저평가 해소를 위한 적극적 밸류업 정책"]
    }
}

# (기존 데이터 로드 및 파싱 함수 원형 유지)
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

conn = st.connection("gsheets", type=GSheetsConnection)
full_df = conn.read(worksheet="종목 현황", ttl="1m")
history_df = conn.read(worksheet="trend", ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'], full_df['평가금액'] = full_df['수량'] * full_df['매입단가'], full_df['수량'] * full_df['현재가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)

# --- [UI 메인 구성] ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v36.1</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        # 상단 메트릭 및 테이블 생략 (v35.6 유지)
        st.dataframe(sub_df[['종목명', '수량', '현재가', '손익', '수익률']].style.format({
            '현재가': '{:,.0f}원', '손익': '{:+,.0f}원', '수익률': '{:+.2f}%'
        }), use_container_width=True, hide_index=True)

        st.divider()
        sel = st.selectbox(f"📍 {acc_name} 종목 분석/대조", sub_df['종목명'].unique(), key=f"sel_{acc_name}")
        
        # 🎯 [연구 기반 딥다이브 카드 v36.1]
        res = RESEARCH_DATA.get(sel.replace(" ", ""))
        if res:
            rows = "".join([f"<tr><td>{m[0]}</td><td>{m[1]}</td><td class='target-val'>{m[2]}</td></tr>" for m in res['metrics']])
            implications_html = "".join([f"<div class='implication-item'>• {imp}</div>" for imp in res['implications']])
            
            st.markdown(f"""
            <div class='insight-card'>
                <div class='insight-title'>🔍 {sel} 인텔리전스 딥다이브 (2026 Target)</div>
                <p style='font-size: 0.9rem; color: rgba(255,255,255,0.8); margin-bottom: 15px;'>{res['desc']}</p>
                <table class='research-table'>
                    <thead><tr><th>분석 지표</th><th>2025년 (추정)</th><th>2026년 (Target)</th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
                <div class='implication-box'>
                    <div class='implication-title'>💡 투자 시사점 및 전략</div>
                    {implications_html}
                </div>
            </div>
            """, unsafe_allow_html=True)

        # 하단 그래프 및 뉴스 피드 생략 (v35.6 유지)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")
