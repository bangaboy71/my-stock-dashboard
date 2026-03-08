import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go

# 1. 설정 및 UI 스타일 정의
st.set_page_config(page_title="가족 자산 성장 관제탑 v36.11", layout="wide")

st.markdown("""
    <style>
    /* 메트릭 및 폰트 */
    [data-testid="stMetricValue"] { font-size: 1.8rem !important; font-weight: bold !important; }
    [data-testid="stMetricLabel"] { font-size: 0.95rem !important; color: rgba(255,255,255,0.7) !important; }
    
    /* 리포트 박스 및 섹터 레이아웃 */
    .report-box { padding: 25px; border-radius: 12px; height: 350px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(135,206,235,0.2); background-color: rgba(135,206,235,0.03); min-height: 250px; margin-bottom: 20px; }
    .sector-title { font-size: 1.2rem; font-weight: bold; border-bottom: 3px solid #87CEEB; padding-bottom: 10px; margin-bottom: 15px; color: #87CEEB; }
    .leader-tag { background: rgba(255,215,0,0.15); border: 1px solid #FFD700; padding: 4px 10px; border-radius: 5px; color: #FFD700; font-size: 0.8rem; font-weight: bold; margin-bottom: 10px; display: inline-block; }

    /* 🎯 딥다이브 카드 (2열 리서치 레이아웃) */
    .insight-card { background: rgba(135,206,235,0.03); padding: 25px; border-radius: 12px; border: 1px solid rgba(135,206,235,0.25); margin-bottom: 25px; color: white; }
    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.3rem; margin-bottom: 20px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 12px; }
    .insight-flex { display: flex; gap: 30px; align-items: flex-start; }
    .insight-left { flex: 1.3; }
    .insight-right { flex: 1; background: rgba(255,215,0,0.04); padding: 20px; border-radius: 10px; border-left: 5px solid #FFD700; }
    
    .research-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
    .research-table th { text-align: left; padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }
    .research-table td { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .target-val { color: #FFD700; font-weight: bold; }
    
    .implication-title { color: #FFD700; font-weight: bold; font-size: 1.05rem; margin-bottom: 15px; }
    .implication-item { font-size: 0.9rem; color: rgba(255,255,255,0.9); margin-bottom: 10px; line-height: 1.6; }

    /* 지수 및 뉴스 인디케이터 */
    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.2rem; border: 2px solid; text-align: center; background-color: rgba(0,0,0,0.2); }
    .up-style { color: #FF4B4B; border-color: #FF4B4B; }
    .down-style { color: #87CEEB; border-color: #87CEEB; }
    .acc-flash-container { background: rgba(255,215,0,0.05); padding: 20px; border-radius: 10px; border: 1px dashed #FFD700; margin-top: 25px; }
    .acc-flash-item { font-size: 0.9rem; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 6px; }
    .acc-flash-stock { color: #87CEEB; font-weight: bold; margin-right: 10px; }
    .news-link:hover { color: #FFD700 !important; text-decoration: underline; cursor: pointer; }
    </style>
    """, unsafe_allow_html=True)

# --- [2. 전체 종목 연구 데이터베이스 (10종 전체 이식)] ---
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

RESEARCH_DATA = {
    "삼성전자": {"desc": "2026년 영업이익 185조원 목표의 압도적 모멘텀.", "metrics": [("영업이익률", "16.8%", "38.5%"), ("ROE", "12.5%", "28.0%"), ("PER", "15.2배", "9.1배"), ("시가배당률", "1.9%", "4.5~6.0%")], "implications": ["HBM3E 양산 본격화 및 파운드리 수익성 개선", "특별 배당 포함 시 연 6% 수준의 환원 기대", "AI 서버 중심 메모리 수요 폭증에 따른 체질 개선"]},
    "KT&G": {"desc": "ROE 15% 달성 및 자사주 소각을 통한 밸류업 구간 진입.", "metrics": [("영업이익률", "20.5%", "20.8%"), ("ROE", "10.5%", "15.0%"), ("PBR", "1.25배", "1.40배"), ("정규 DPS", "6,000원", "6,400~6,600원")], "implications": ["해외 궐련 수출 확대 및 NGP 성장 동력 확보", "2027년까지 발행주식 20% 소각 진행", "글로벌 신공장 가동을 통한 공급망 강화"]},
    "현대차2우B": {"desc": "고배당 우선주 및 은퇴 포트폴리오의 강력한 캐시카우.", "metrics": [("영업이익률", "6.2%", "7.0%"), ("ROE", "13.0%", "15.5%"), ("시가배당률", "5.7%", "6.4%"), ("정규 DPS", "13,600원", "14.5~15.5천원")], "implications": ["SUV/제네시스 중심 믹스 개선 및 수익 가이드라인 준수", "본주 대비 높은 할인율로 배당수익률 극대화", "자사주 소각 등 적극적 밸류업 정책 수행"]},
    "테스": {"desc": "반도체 선단공정 장비 국산화 수혜 및 이익률 점프 예상.", "metrics": [("영업이익률", "10.7%", "19.0%"), ("ROE", "6.2%", "14.5%"), ("PER", "18.5배", "11.2배"), ("정규 DPS", "500원", "700~900원")], "implications": ["메모리 선단 공정 전환에 따른 장비 수요 폭증", "2026년 ROE 14.5% 달성 전망의 성장 가치주", "업황 회복에 따른 가동률 상승 및 현금흐름 개선"]},
    "KODEX200타겟위클리커버드콜": {"desc": "주 단위 콜옵션 매도로 연 15% 분배율 지향.", "metrics": [("옵션 프리미엄", "연 15%", "연 15%"), ("월 분배금", "110원", "120원"), ("수익 구조", "인컴+상승분", "타겟 프리미엄"), ("시가분배율", "연 12.5%", "연 15.0%")], "implications": ["박스권 장세에서 콜옵션 매도 수익을 통한 초과 수익", "은퇴 생활비 마련을 위한 월 분배금 최적화 도구", "하방 방어력을 갖춘 인컴 집중형 포트폴리오"]},
    "일진전기": {"desc": "북미 전력 인프라 교체 주기 직접적 수혜주.", "metrics": [("영업이익률", "6.2%", "8.6%"), ("ROE", "15.2%", "22.5%"), ("PER", "18.0배", "12.5배"), ("시가배당률", "1.5%", "2.0~2.5%")], "implications": ["북미 인프라 교체 및 데이터센터 증설의 직접적 수혜", "수주 잔고 기반 2026년 영업이익 0.16조원 목표", "전력 효율화 및 ESS 시장 확대에 따른 추가 모멘텀"]},
    "에스티팜": {"desc": "RNA 치료제 CDMO 모멘텀 및 이익률 20% 타겟.", "metrics": [("영업이익률", "14.3%", "20.7%"), ("ROE", "8.5%", "18.2%"), ("PER", "45.0배", "22.5배"), ("시가배당률", "0.5%", "0.8~1.2%")], "implications": ["올리고 핵산 생산 시설 가동률 상승에 따른 수익 개선", "글로벌 제약사와의 CDMO 계약 확대 기대", "RNA 플랫폼 기반의 장기적 성장성 확보"]},
    "현대글로비스": {"desc": "물류 효율화 및 DPS 8,000원 시대 지향.", "metrics": [("영업이익률", "6.2%", "6.7%"), ("ROE", "12.8%", "14.5%"), ("PER", "9.2배", "8.1배"), ("정규 DPS", "6,300원", "7,500~8,000원")], "implications": ["자동차 운반선 공급 부족에 따른 수익 방어", "해외 물류 거점 확보 및 그룹사 시너지", "배당 증액을 통한 주주 가치 제고 의지"]},
    "LG에너지솔루션": {"desc": "이차전지 수익성 개선 및 영업이익 4.8조 타겟.", "metrics": [("영업이익률", "6.5%", "10.6%"), ("ROE", "5.2%", "11.5%"), ("PER", "65.0배", "32.0배"), ("시가배당률", "0.35%", "0.5~0.8%")], "implications": ["북미 합적 공장 가동 본격화", "차세대 배터리 양산 기술 우위 확보", "전기차 수요 회복 시 이익 가시성 대폭 개선"]},
    "SK스퀘어": {"desc": "지주사 할인율 축소 및 자사주 소각 최대 0.8조 목표.", "metrics": [("ROE", "4.5%", "9.8%"), ("PBR", "0.45배", "0.65배"), ("NAV 할인율", "65.0%", "45.0%"), ("자사주 소각", "0.2조", "0.5~0.8조")], "implications": ["하이닉스 배당 기반 주주 환원 정책 강화", "비상장 포트폴리오 자산 가치 재평가", "밸류업 가이드라인 준수를 통한 할인율 해소"]}
}

# --- [3. 엔진 함수] ---
def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def get_market_indices():
