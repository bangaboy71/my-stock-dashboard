import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import plotly.graph_objects as go
import time
import re

# 1. 설정 및 연결
st.set_page_config(page_title="가족 자산 성장 관제탑 v30.2 (Standard)", layout="wide")

# --- [CSS: 시인성 강화 및 심층 리포트 레이아웃] ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; }
    .report-box { padding: 25px; border-radius: 12px; height: 750px; overflow-y: auto; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.15); background-color: rgba(255,255,255,0.02); line-height: 1.8; }
    .sector-box { padding: 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background-color: rgba(255,255,255,0.04); min-height: 500px; margin-bottom: 20px; }
    .sector-title { font-size: 1.3rem; font-weight: bold; border-bottom: 4px solid #87CEEB; padding-bottom: 12px; margin-bottom: 15px; color: #87CEEB; }
    .market-tag { background-color: rgba(135,206,235,0.2); padding: 5px 12px; border-radius: 6px; color: #87CEEB; font-weight: bold; margin-bottom: 10px; display: inline-block; font-size: 0.9em; }
    .leader-tag { background-color: rgba(255,215,0,0.15); border: 1px solid rgba(255,215,0,0.4); padding: 6px 12px; border-radius: 6px; color: #FFD700; font-weight: bold; margin-bottom: 12px; display: inline-block; font-size: 0.9em; }
    .index-indicator { padding: 15px 30px; border-radius: 12px; font-weight: bold; font-size: 1.2rem; border: 2px solid; text-align: center; box-shadow: 4px 4px 15px rgba(0,0,0,0.3); background-color: rgba(0,0,0,0.2); }
    .up-style { color: #FF4B4B; border-color: #FF4B4B; }
    .down-style { color: #87CEEB; border-color: #87CEEB; }
    </style>
    """, unsafe_allow_html=True)

# [시간 및 데이터 엔진 생략 - v30.2 로직과 동일]
now_kst = datetime.now(timezone(timedelta(hours=9)))
conn = st.connection("gsheets", type=GSheetsConnection)

def get_market_indices():
    market = {}
    try:
        for code in ["KOSPI", "KOSDAQ"]:
            url = f"https://finance.naver.com/sise/sise_index.naver?code={code}"
            soup = BeautifulSoup(requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).text, 'html.parser')
            val = soup.find("em", {"id": "now_value"}).text
            raw = soup.find("span", {"id": "change_value_and_rate"}).text.strip().split()
            diff = raw[0].replace("상승","+").replace("하락","-").strip()
            rate = raw[1].replace("상승","").replace("하락","").strip()
            style_cls = "up-style" if "+" in diff else "down-style" if "-" in diff else ""
            market[code] = {"now": val, "diff": diff, "rate": rate, "style": style_cls}
    except: market = {"KOSPI": {"now": "-", "diff": "-", "rate": "-", "style": ""}, "KOSDAQ": {"now": "-", "diff": "-", "rate": "-", "style": ""}}
    return market

# [데이터 전처리 및 주가 파싱 생략 - v28.3~30.2 마스터 로직 유지]
# ... (중략: full_df 생성 및 전처리 로직) ...

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v30.2</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

with tabs[0]:
    # ... (상단 메트릭 및 계좌 요약 표 표출) ...
    
    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    
    # 🎯 지수 표시판 (v30.2 시인성 고수)
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    idx_l.markdown(f"<div class='index-indicator {m_idx['KOSPI']['style']}'>KOSPI: {m_idx['KOSPI']['now']} ({m_idx['KOSPI']['diff']}, {m_idx['KOSPI']['rate']})</div>", unsafe_allow_html=True)
    idx_r.markdown(f"<div class='index-indicator {m_idx['KOSDAQ']['style']}'>KOSDAQ: {m_idx['KOSDAQ']['now']} ({m_idx['KOSDAQ']['diff']}, {m_idx['KOSDAQ']['rate']})</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    rep_l, rep_r = st.columns(2)
    with rep_l:
        st.markdown("""<div class='report-box'>
            <h4 style='color: #87CEEB;'>🇰🇷 국내 시장 심층 분석 리포트</h4>
            <div class='market-tag'>데일리 시장 총평</div>
            <p>풍부한 텍스트 분석 내용...</p>
            <div class='market-tag'>KOSPI 시장 분석</div>
            <p>2,500선 사수 및 수급 공방 상세 분석...</p>
            <div class='market-tag'>KOSDAQ 시장 분석</div>
            <p>바이오 대장주 및 2차전지 개별 장세 분석...</p>
        </div>""", unsafe_allow_html=True)
    
    with rep_r:
        st.markdown("""<div class='report-box'>
            <h4 style='color: #FF4B4B;'>🌍 글로벌 시장 및 매크로 분석</h4>
            <div class='market-tag'>미국 S&P 500 & NASDAQ 동향</div>
            <p>Tech-Selloff 및 나스닥 기술주 변동성 상세 분석...</p>
            <div class='market-tag'>원/달러 환율 및 금리 현황</div>
            <p>1,400~1,500원대 초고환율 사실관계 및 수출입 영향 분석...</p>
        </div>""", unsafe_allow_html=True)

    # 📊 관심 섹터별 인텔리전스 (주도주 및 5대 요소)
    st.divider()
    st.subheader("📊 관심 섹터별 인텔리전스 (주도주 및 심층 분석)")
    # ... (반도체, 전력, 배터리, 바이오, 모빌리티/로봇, 소비재 6개 박스 구성) ...
