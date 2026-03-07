    .insight-title { color: #87CEEB; font-weight: bold; font-size: 1.15rem; margin-bottom: 12px; border-bottom: 1px solid rgba(135,206,235,0.2); padding-bottom: 8px; display: flex; align-items: center; gap: 8px; }
    .insight-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 15px; }
    .insight-label { color: rgba(255,255,255,0.5); font-size: 0.8rem; }
    .insight-value { color: #FFFFFF; font-weight: bold; font-size: 0.95rem; }
    .target-price { color: #FFD700; font-size: 1.1rem; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- [데이터 엔진 및 시간 설정] ---
STOCKS_SHEET = "종목 현황"
TREND_SHEET = "trend"
STOCK_CODES = {"삼성전자": "005930", "KT&G": "033780", "LG에너지솔루션": "373220", "현대글로비스": "086280", "현대차2우B": "005387", "KODEX200타겟위클리커버드콜": "498400", "에스티팜": "237690", "테스": "095610", "일진전기": "103590", "SK스퀘어": "402340"}

def get_now_kst(): return datetime.now(timezone(timedelta(hours=9)))
now_kst = get_now_kst()
conn = st.connection("gsheets", type=GSheetsConnection)

def safe_float(text):
    try: return float(re.sub(r'[^0-9.\-+]', '', str(text))) if text else 0.0
    except: return 0.0

def color_positive_negative(v):
    if isinstance(v, (int, float)):
        return f"color: {'#FF4B4B' if v > 0 else '#87CEEB' if v < 0 else '#FFFFFF'}"
    return ''

# --- [🎯 기업 정보 & 재무 & 목표가 수집 엔진] ---
def get_stock_intelligence(name):
    code = STOCK_CODES.get(name.replace(" ", ""))
    if not code: return None
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. 기업 개요
        summary = soup.find("div", {"class": "summary"})
        desc = summary.text.replace("기업개요", "").strip().split(".")[0] + "." if summary else "정보를 불러올 수 없습니다."
        
        # 2. 재무 지표 및 목표가
        target_price, per, pbr, div_yield = "N/A", "N/A", "N/A", "N/A"
        
        aside = soup.find("div", {"class": "aside"})
        if aside:
            expect = aside.find("div", {"class": "expect"})
            if expect and expect.find("em"): target_price = expect.find("em").text + "원"
            
            table = aside.find("table", {"summary": "주요 시세 정보"})
            if table:
                for tr in table.find_all("tr"):
                    txt = tr.text
                    if "PER" in txt and "배" in txt: per = tr.find("em").text + "배"
                    elif "PBR" in txt and "배" in txt: pbr = tr.find("em").text + "배"
                    elif "배당수익률" in txt: div_yield = tr.find("em").text + "%"
        
        return {"desc": desc, "tp": target_price, "per": per, "pbr": pbr, "div": div_yield}
    except: return None

# --- [시장 및 종목 데이터 파싱: v30.9 유지] ---
def get_acc_news(stocks):
    news_list = []
    try:
        for s in stocks:
            code = STOCK_CODES.get(s.replace(" ", ""))
            if not code: continue
            res = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            news_sec = soup.find("div", {"class": "news_section"})
            if news_sec:
                tag = news_sec.find("li").find("a")
                if tag:
                    href = tag['href']
                    news_list.append({"name": s, "title": tag.text.strip(), "url": href if href.startswith("http") else f"https://finance.naver.com{href}"})
    except: pass
    return news_list

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
            cls = "up-style" if "+" in diff else "down-style" if "-" in diff else ""
            market[code] = {"now": val, "diff": diff, "rate": rate, "style": cls}
    except: market = {"KOSPI": {"now": "-", "diff": "-", "rate": "-", "style": ""}, "KOSDAQ": {"now": "-", "diff": "-", "rate": "-", "style": ""}}
    return market

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

# --- [데이터 로드 및 전처리] ---
full_df = conn.read(worksheet=STOCKS_SHEET, ttl="1m")
history_df = conn.read(worksheet=TREND_SHEET, ttl=0)

if not full_df.empty:
    for c in ['수량', '매입단가']:
        full_df[c] = pd.to_numeric(full_df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    prices = full_df['종목명'].apply(get_stock_data).tolist()
    full_df['현재가'], full_df['전일종가'] = [p[0] for p in prices], [p[1] for p in prices]
    full_df['매입금액'] = full_df['수량'] * full_df['매입단가']
    full_df['평가금액'] = full_df['수량'] * full_df['현재가']
    full_df['전일평가금액'] = full_df['수량'] * full_df['전일종가']
    full_df['주가변동'] = full_df['현재가'] - full_df['매입단가']
    full_df['손익'] = full_df['평가금액'] - full_df['매입금액']
    full_df['수익률'] = (full_df['손익'] / (full_df['매입금액'].replace(0, float('nan'))) * 100).fillna(0)
    full_df['전일대비(%)'] = ((full_df['현재가'] / (full_df['전일종가'].replace(0, float('nan'))) - 1) * 100).fillna(0)

if not history_df.empty:
    history_df['Date'] = pd.to_datetime(history_df['Date'], format='mixed', errors='coerce').dt.date
    history_df = history_df.dropna(subset=['Date']).sort_values('Date')

# --- [사이드바 마스터 메뉴] ---
def record_performance():
    today = now_kst.date()
    m_info = get_market_indices()
    acc_sum = full_df.groupby('계좌명').apply(lambda x: (x['평가금액'].sum() / x['매입금액'].sum() - 1) * 100 if x['매입금액'].sum() > 0 else 0)
    new_row = {"Date": today, "KOSPI": float(m_info['KOSPI']['now'].replace(',','')), "서은수익률": acc_sum.get('서은투자', 0), "서희수익률": acc_sum.get('서희투자', 0), "큰스님수익률": acc_sum.get('큰스님투자', 0)}
    conn.update(worksheet=TREND_SHEET, data=pd.concat([history_df[history_df['Date']!=today], pd.DataFrame([new_row])]).sort_values('Date'))
    st.sidebar.success("✅ 저장 성공"); st.cache_data.clear(); st.rerun()

st.sidebar.header("🕹️ 관제탑 마스터 메뉴")
if st.sidebar.button("🔄 실시간 데이터 전체 갱신"): st.cache_data.clear(); st.rerun()
if st.sidebar.button("💾 오늘의 결과 저장/덮어쓰기"): record_performance()
if st.sidebar.button("🧹 과거 데이터 정제"):
    history_df['Date'] = pd.to_datetime(history_df['Date']).dt.strftime('%Y-%m-%d')
    conn.update(worksheet=TREND_SHEET, data=history_df.drop_duplicates(subset=['Date'], keep='last')); st.sidebar.success("정제 완료"); st.rerun()

# --- UI 메인 ---
st.markdown(f"<h1 style='text-align: center; color: #87CEEB;'>🌐 AI 금융 통합 관제탑 v31.0</h1>", unsafe_allow_html=True)
tabs = st.tabs(["📊 총괄 현황", "💰 서은투자", "📈 서희투자", "🙏 큰스님투자"])

# [Tab 0] 총괄 현황: v30.9 완전 복구
with tabs[0]:
    t_buy, t_eval, t_prev_eval = full_df['매입금액'].sum(), full_df['평가금액'].sum(), full_df['전일평가금액'].sum()
    total_profit, daily_rate = t_eval - t_buy, ((t_eval / t_prev_eval - 1) * 100) if t_prev_eval > 0 else 0
    m1, m2, m_profit, m3 = st.columns(4)
    m1.metric("가족 총 평가액", f"{t_eval:,.0f}원", f"{t_eval-t_prev_eval:+,.0f}원")
    m2.metric("총 투자 원금", f"{t_buy:,.0f}원")
    m_profit.metric("총 손익", f"{total_profit:,.0f}원")
    m3.metric("통합 누적 수익률", f"{(t_eval/t_buy-1)*100 if t_buy>0 else 0:.2f}%", f"{daily_rate:+.2f}%")
    
    st.markdown("---")
    sum_acc = full_df.groupby('계좌명').agg({'매입금액':'sum', '평가금액':'sum', '전일평가금액':'sum', '손익':'sum'}).reset_index()
    sum_acc['전일대비(%)'] = ((sum_acc['평가금액'] / sum_acc['전일평가금액'] - 1) * 100).fillna(0)
    sum_acc['누적 수익률'] = (sum_acc['손익'] / sum_acc['매입금액'] * 100).fillna(0)
    st.dataframe(sum_acc[['계좌명', '매입금액', '평가금액', '손익', '전일대비(%)', '누적 수익률']].style.map(color_positive_negative, subset=['손익', '전일대비(%)', '누적 수익률']).format({
        '매입금액': '{:,.0f}원', '평가금액': '{:,.0f}원', '손익': '{:+,.0f}원', '전일대비(%)': '{:+.2f}%', '누적 수익률': '{:+.2f}%'
    }), hide_index=True, use_container_width=True)

    if not history_df.empty:
        st.markdown("<br>", unsafe_allow_html=True)
        fig_t = go.Figure()
        h_dates = history_df['Date'].astype(str)
        bk_k = history_df['KOSPI'].iloc[0] if history_df['KOSPI'].iloc[0] != 0 else 1
        k_yield = ((history_df['KOSPI'] / bk_k) - 1) * 100
        fig_t.add_trace(go.Scatter(x=h_dates, y=k_yield, name='KOSPI 지수', line=dict(dash='dash', color='gray')))
        for col, color in {'서은수익률': '#FF4B4B', '서희수익률': '#87CEEB', '큰스님수익률': '#00FF00'}.items():
            if col in history_df.columns: fig_t.add_trace(go.Scatter(x=h_dates, y=history_df[col], mode='lines+markers', name=col.replace('수익률',''), line=dict(color=color, width=3)))
        fig_t.update_layout(title="📈 가족 자산 통합 수익률 추이 (vs KOSPI)", height=450, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
        st.plotly_chart(fig_t, use_container_width=True)

    st.divider()
    st.subheader("🕵️ AI 관제탑 데일리 심층 리포트")
    m_idx = get_market_indices()
    idx_l, idx_r = st.columns(2)
    idx_l.markdown(f"<div class='index-indicator {m_idx['KOSPI']['style']}'>KOSPI: {m_idx['KOSPI']['now']} ({m_idx['KOSPI']['diff']}, {m_idx['KOSPI']['rate']})</div>", unsafe_allow_html=True)
    idx_r.markdown(f"<div class='index-indicator {m_idx['KOSDAQ']['style']}'>KOSDAQ: {m_idx['KOSDAQ']['now']} ({m_idx['KOSDAQ']['diff']}, {m_idx['KOSDAQ']['rate']})</div>", unsafe_allow_html=True)

    rep_l, rep_r = st.columns(2)
    with rep_l:
        st.markdown(f"""<div class='report-box'>
            <h4 style='color: #87CEEB;'>🇰🇷 국내 시장 심층 분석 리포트</h4>
            <div class='market-tag'>데일리 시장 총평</div>
            <p>2026년 3월 7일 현재, 국내 증시는 <b>KOSPI 5,000선</b> 돌파 이후의 역사적 랠리 국면에 있습니다. 사용자님 지적대로 지수가 5,000중반/1,000이상을 상회하며 초강세장을 유지 중입니다.</p>
        </div>""", unsafe_allow_html=True)
    with rep_r:
        st.markdown(f"""<div class='report-box'>
            <h4 style='color: #FF4B4B;'>🌍 글로벌 시장 및 매크로 분석</h4>
            <div class='market-tag'>환율 상황 및 선거 변수</div>
            <p>현재 환율은 <b>1,400원 중후반대(1,450~1,480원)</b>를 기록하며 고환율 장기화 국면에 있습니다. 하반기 미국 중간선거에 대비한 전략적 대응이 필수적입니다.</p>
        </div>""", unsafe_allow_html=True)

    st.divider()
    st.subheader("📊 관심 섹터별 인텔리전스")
    sec_cols = st.columns(3)
    sectors = {"반도체 / IT": "AI 칩 수요 폭발.", "전력 / ESS": "미국 인프라 교체 수혜.", "배터리 / 에너지": "전고체 기술 초격차.", "바이오": "기술 수출 모멘텀.", "모빌리티": "휴머노이드 상용화.", "뷰티": "북미 점유율 폭증."}
    for i, (n, d) in enumerate(sectors.items()):
        with sec_cols[i % 3]: st.markdown(f"<div class='sector-box'><div class='sector-title'>{n}</div><p>{d}</p></div>", unsafe_allow_html=True)

# [계좌별 상세 분석 탭: 딥다이브 탑재]
def render_account_tab(acc_name, tab_obj, history_col):
    with tab_obj:
        sub_df = full_df[full_df['계좌명'] == acc_name].copy()
        if sub_df.empty: return
        
        # 메트릭 및 데이터프레임
        a_buy, a_eval, a_prev_eval = sub_df['매입금액'].sum(), sub_df['평가금액'].sum(), sub_df['전일평가금액'].sum()
        c1, c2, cp, c3 = st.columns(4)
        c1.metric("평가액", f"{a_eval:,.0f}원", f"{a_eval-a_prev_eval:+,.0f}원")
        c2.metric("매입금액", f"{a_buy:,.0f}원")
        cp.metric("손익", f"{a_eval-a_buy:+,.0f}원")
        c3.metric("누적 수익률", f"{(a_eval/a_buy-1)*100:.2f}%")
        
        st.dataframe(sub_df[['종목명', '수량', '매입단가', '현재가', '주가변동', '매입금액', '평가금액', '손익', '전일대비(%)', '수익률']].style.map(color_positive_negative, subset=['주가변동', '손익', '전일대비(%)', '수익률']), hide_index=True, use_container_width=True)

        st.divider()
        g1, g2 = st.columns([2, 1])
        with g1:
            # 🎯 [🎯 핵심 추가] 종목 대조 및 인텔리전스 딥다이브
            stk_list = sub_df['종목명'].unique().tolist()
            sel_stk = st.selectbox(f"📍 {acc_name} 종목 분석 및 대조", stk_list, key=f"sel_{acc_name}")
            
            # 기업 인텔리전스 카드 팝업
            intel = get_stock_intelligence(sel_stk)
            if intel:
                st.markdown(f"""
                <div class='insight-card'>
                    <div class='insight-title'>🔍 {sel_stk} 기업 인텔리전스</div>
                    <p style='font-size: 0.88rem;'>{intel['desc']}</p>
                    <div class='insight-grid'>
                        <div><span class='insight-label'>리서치 목표가</span><br><span class='target-price'>{intel['tp']}</span></div>
                        <div><span class='insight-label'>배당수익률</span><br><span class='insight-value'>{intel['div']}</span></div>
                        <div><span class='insight-label'>PER (배)</span><br><span class='insight-value'>{intel['per']}</span></div>
                        <div><span class='insight-label'>PBR (배)</span><br><span class='insight-value'>{intel['pbr']}</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            if not history_df.empty and history_col in history_df.columns:
                fig = go.Figure()
                h_dt = history_df['Date'].astype(str)
                fig.add_trace(go.Scatter(x=h_dt, y=history_df[history_col], mode='lines+markers', name='계좌 수익률', line=dict(color='#87CEEB', width=4)))
                s_c = next((c for c in history_df.columns if acc_name[:2] in c and sel_stk.replace(' ','') in c.replace(' ','')), "")
                if s_c: fig.add_trace(go.Scatter(x=h_dt, y=history_df[s_c], mode='lines', name=f'{sel_stk} 수익률', line=dict(color='#FF4B4B', width=2)))
                fig.update_layout(title=f"📈 {acc_name} 성과 추이", height=400, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
                st.plotly_chart(fig, use_container_width=True)
        with g2:
            fig_p = go.Figure(data=[go.Pie(labels=sub_df['종목명'], values=sub_df['평가금액'], hole=.3)])
            fig_p.update_layout(title="💰 자산 비중", height=520, paper_bgcolor='rgba(0,0,0,0)', font_color="white")
            st.plotly_chart(fig_p, use_container_width=True)

        st.divider()
        st.subheader(f"🕵️ {acc_name} 데일리 리포트 및 공시")
        st.markdown("<div class='report-box' style='height:150px;'><p>현재 계좌는 시장 주도주를 바탕으로 안정적인 흐름을 유지하고 있습니다.</p></div>", unsafe_allow_html=True)
        
        acc_news = get_acc_news(sub_df['종목명'].unique().tolist())
        if acc_news:
            news_html = "".join([f"<div class='acc-flash-item'><span class='acc-flash-stock'>[{n['name']}]</span> <a href='{n['url']}' target='_blank' class='news-link'>{n['title']} ↗️</a></div>" for n in acc_news])
            st.markdown(f"<div class='acc-flash-container'><div style='font-weight: bold; color: #FFD700; margin-bottom: 10px;'>🔔 최신 공시/뉴스 (클릭 시 새 창 이동)</div>{news_html}</div>", unsafe_allow_html=True)

render_account_tab("서은투자", tabs[1], "서은수익률")
render_account_tab("서희투자", tabs[2], "서희수익률")
render_account_tab("큰스님투자", tabs[3], "큰스님수익률")

st.caption(f"최종 업데이트: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST) | v31.0 인프라 완결 버전")

