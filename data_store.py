"""
data_store.py — 가족 자산 관제탑 데이터 저장 레이어
=======================================================
우선순위 3: SQLite 로컬 캐시 + Google Sheets 저장 파이프라인

역할
────
- SQLite: 수집한 주가 일봉 데이터를 로컬 DB에 캐싱
          → Streamlit 재실행 시 pykrx 재요청 없이 즉시 로드
- Google Sheets 저장: 수집된 데이터를 자동으로 snapshot 시트에 기록
- 캐시 무효화: TTL 기반 자동 갱신 (기본 4시간)

외부 의존성: 표준 라이브러리 sqlite3 사용 (추가 설치 불필요)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════
# 설정
# ════════════════════════════════════════════════════════

DB_PATH     = Path("market_cache.db")   # Streamlit Cloud: /tmp/market_cache.db 으로 변경
CACHE_TTL_H = 4                          # 캐시 유효 시간 (시간 단위)

KST = timezone(timedelta(hours=9))


# ════════════════════════════════════════════════════════
# 1. SQLite 초기화
# ════════════════════════════════════════════════════════

def _get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """SQLite 연결 반환 (WAL 모드로 동시 읽기 성능 향상)"""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """
    캐시 테이블 생성 (없을 때만).
    테이블:
      price_cache    — 종목별 (현재가, 전일종가) 캐시
      ohlcv_cache    — 종목별 일봉 OHLCV 캐시
      market_cache   — 시장 지표 (KOSPI, KOSDAQ 등) 캐시
    """
    conn = _get_conn(db_path)
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_cache (
                code        TEXT NOT NULL,
                date        TEXT NOT NULL,
                current     INTEGER DEFAULT 0,
                prev        INTEGER DEFAULT 0,
                updated_at  TEXT NOT NULL,
                PRIMARY KEY (code, date)
            );

            CREATE TABLE IF NOT EXISTS ohlcv_cache (
                code       TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open       INTEGER DEFAULT 0,
                high       INTEGER DEFAULT 0,
                low        INTEGER DEFAULT 0,
                close      INTEGER DEFAULT 0,
                volume     INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (code, trade_date)
            );

            CREATE TABLE IF NOT EXISTS market_cache (
                key        TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
    conn.close()
    logger.info(f"DB 초기화 완료: {db_path}")


# ════════════════════════════════════════════════════════
# 2. 종목 주가 캐시 (price_cache)
# ════════════════════════════════════════════════════════

def _is_cache_valid(updated_at: str, ttl_hours: int = CACHE_TTL_H) -> bool:
    """updated_at ISO 문자열 기준으로 캐시 유효 여부 반환"""
    try:
        updated = datetime.fromisoformat(updated_at).replace(tzinfo=KST)
        return datetime.now(KST) - updated < timedelta(hours=ttl_hours)
    except Exception:
        return False


def get_cached_price(
    code: str,
    db_path: Path = DB_PATH,
    ttl_hours: int = CACHE_TTL_H,
) -> Optional[tuple[int, int]]:
    """
    SQLite 캐시에서 (현재가, 전일종가) 반환.
    캐시 없거나 만료 시 None 반환.
    """
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        conn = _get_conn(db_path)
        row = conn.execute(
            "SELECT current, prev, updated_at FROM price_cache WHERE code=? AND date=?",
            (code, today),
        ).fetchone()
        conn.close()
        if row and _is_cache_valid(row[2], ttl_hours):
            return int(row[0]), int(row[1])
    except Exception as e:
        logger.warning(f"캐시 조회 실패({code}): {e}")
    return None


def set_cached_price(
    code: str,
    current: int,
    prev: int,
    db_path: Path = DB_PATH,
) -> None:
    """(현재가, 전일종가) 를 SQLite 캐시에 저장"""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    now   = datetime.now(KST).isoformat()
    try:
        conn = _get_conn(db_path)
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO price_cache
                   (code, date, current, prev, updated_at) VALUES (?,?,?,?,?)""",
                (code, today, current, prev, now),
            )
        conn.close()
    except Exception as e:
        logger.warning(f"캐시 저장 실패({code}): {e}")


def get_price_with_cache(
    code: str,
    fetch_fn,            # callable(code) → (int, int)
    db_path: Path = DB_PATH,
    ttl_hours: int = CACHE_TTL_H,
) -> tuple[int, int]:
    """
    캐시 우선 조회 → 없으면 fetch_fn 호출 후 캐싱.
    사용 예:
        from market_collector import get_krx_price
        price = get_price_with_cache("005930", get_krx_price)
    """
    cached = get_cached_price(code, db_path, ttl_hours)
    if cached is not None:
        return cached
    result = fetch_fn(code)
    if result[0] > 0:               # 수집 성공 시만 캐싱
        set_cached_price(code, *result, db_path)
    return result


# ════════════════════════════════════════════════════════
# 3. 시장 지표 캐시 (market_cache)
# ════════════════════════════════════════════════════════

def get_cached_market(
    key: str = "market_status",
    db_path: Path = DB_PATH,
    ttl_hours: int = 1,             # 시장 지표는 1시간 TTL
) -> Optional[dict]:
    """시장 지표 캐시 조회. 만료/없으면 None."""
    try:
        conn = _get_conn(db_path)
        row = conn.execute(
            "SELECT value_json, updated_at FROM market_cache WHERE key=?", (key,)
        ).fetchone()
        conn.close()
        if row and _is_cache_valid(row[1], ttl_hours):
            return json.loads(row[0])
    except Exception as e:
        logger.warning(f"market_cache 조회 실패: {e}")
    return None


def set_cached_market(
    data: dict,
    key: str = "market_status",
    db_path: Path = DB_PATH,
) -> None:
    """시장 지표를 SQLite 캐시에 저장"""
    now = datetime.now(KST).isoformat()
    try:
        conn = _get_conn(db_path)
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO market_cache (key, value_json, updated_at) VALUES (?,?,?)",
                (key, json.dumps(data, ensure_ascii=False), now),
            )
        conn.close()
    except Exception as e:
        logger.warning(f"market_cache 저장 실패: {e}")


# ════════════════════════════════════════════════════════
# 4. OHLCV 일봉 캐시 (ohlcv_cache)
# ════════════════════════════════════════════════════════

def save_ohlcv_to_cache(
    code: str,
    df: pd.DataFrame,
    db_path: Path = DB_PATH,
) -> int:
    """
    OHLCV DataFrame 을 SQLite 에 저장.
    df 컬럼: Date | 시가 | 고가 | 저가 | 종가 | 거래량  (pykrx 기본)
    반환: 저장된 행 수
    """
    if df.empty:
        return 0
    now = datetime.now(KST).isoformat()
    rows = []
    for _, row in df.iterrows():
        try:
            date_str = str(row.get("Date", ""))[:10]
            rows.append((
                code,
                date_str,
                int(row.get("시가",  0)),
                int(row.get("고가",  0)),
                int(row.get("저가",  0)),
                int(row.get("종가",  0)),
                int(row.get("거래량", 0)),
                now,
            ))
        except Exception:
            continue
    if not rows:
        return 0
    try:
        conn = _get_conn(db_path)
        with conn:
            conn.executemany(
                """INSERT OR REPLACE INTO ohlcv_cache
                   (code, trade_date, open, high, low, close, volume, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                rows,
            )
        conn.close()
        return len(rows)
    except Exception as e:
        logger.error(f"OHLCV 저장 실패({code}): {e}")
        return 0


def load_ohlcv_from_cache(
    code: str,
    from_date: str,          # "YYYY-MM-DD"
    to_date: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> pd.DataFrame:
    """SQLite 에서 OHLCV DataFrame 로드"""
    if to_date is None:
        to_date = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        conn = _get_conn(db_path)
        df = pd.read_sql_query(
            """SELECT trade_date AS Date, open AS 시가, high AS 고가,
                      low AS 저가, close AS 종가, volume AS 거래량
               FROM ohlcv_cache
               WHERE code=? AND trade_date BETWEEN ? AND ?
               ORDER BY trade_date""",
            conn,
            params=(code, from_date, to_date),
        )
        conn.close()
        if not df.empty:
            df["Date"] = pd.to_datetime(df["Date"])
        return df
    except Exception as e:
        logger.error(f"OHLCV 로드 실패({code}): {e}")
        return pd.DataFrame()


# ════════════════════════════════════════════════════════
# 5. Google Sheets snapshot 자동 저장
# ════════════════════════════════════════════════════════

def save_prices_to_snapshot(
    conn_gsheets,
    full_df: pd.DataFrame,
    market_status: dict,
    now_kst: Optional[datetime] = None,
) -> bool:
    """
    현재 주가 + 시장 지표를 Google Sheets 'snapshot' 시트에 자동 기록.

    시트 구조: 날짜 | 항목 | 값
    ─────────────────────────────────────────────────
    2026-03-30 | KOSPI                     | 2650.00
    2026-03-30 | 삼성전자                  | 72400
    2026-03-30 | USD/KRW                   | 1385.50
    ─────────────────────────────────────────────────
    기존 data_engine.load_snapshot() 과 동일 포맷.
    """
    try:
        from config import WS_SNAPSHOT
    except ImportError:
        WS_SNAPSHOT = "snapshot"

    if now_kst is None:
        now_kst = datetime.now(timezone(timedelta(hours=9)))
    today = now_kst.strftime("%Y-%m-%d")

    rows: list[dict] = []

    # 시장 지표
    for label, data in market_status.items():
        val_str = data.get("val", "-")
        if val_str == "-":
            continue
        try:
            val = float(val_str.replace(",", "").replace("%p", "").replace("%", ""))
            rows.append({"날짜": today, "항목": label, "값": val})
        except ValueError:
            pass

    # 종목 현재가
    if not full_df.empty and "종목명" in full_df.columns and "현재가" in full_df.columns:
        for _, row in full_df.drop_duplicates("종목명").iterrows():
            price = row.get("현재가", 0)
            if price and float(price) > 0:
                rows.append({
                    "날짜": today,
                    "항목": str(row["종목명"]),
                    "값":   float(price),
                })

    if not rows:
        logger.warning("snapshot 저장 데이터 없음")
        return False

    new_df = pd.DataFrame(rows)

    try:
        # 기존 snapshot 로드 후 오늘 날짜 행 교체
        existing = conn_gsheets.read(worksheet=WS_SNAPSHOT, ttl=0)
        if not existing.empty and "날짜" in existing.columns:
            existing = existing[existing["날짜"] != today]
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df

        conn_gsheets.update(worksheet=WS_SNAPSHOT, data=combined)
        logger.info(f"snapshot {today} — {len(rows)}개 항목 저장")
        return True

    except Exception as e:
        logger.error(f"snapshot 저장 실패: {e}")
        return False


# ════════════════════════════════════════════════════════
# 6. 캐시 유지보수
# ════════════════════════════════════════════════════════

def purge_old_cache(
    days_to_keep: int = 30,
    db_path: Path = DB_PATH,
) -> dict[str, int]:
    """
    오래된 캐시 데이터 삭제.
    반환: {"price_cache": n, "ohlcv_cache": n}
    """
    cutoff = (datetime.now(KST) - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
    deleted = {}
    try:
        conn = _get_conn(db_path)
        with conn:
            r1 = conn.execute("DELETE FROM price_cache WHERE date < ?", (cutoff,))
            r2 = conn.execute("DELETE FROM ohlcv_cache WHERE trade_date < ?", (cutoff,))
        deleted = {"price_cache": r1.rowcount, "ohlcv_cache": r2.rowcount}
        conn.close()
        logger.info(f"캐시 정리: {deleted}")
    except Exception as e:
        logger.error(f"캐시 정리 실패: {e}")
    return deleted


def get_cache_stats(db_path: Path = DB_PATH) -> dict:
    """캐시 현황 조회 (디버그·사이드바 표시용)"""
    try:
        conn = _get_conn(db_path)
        stats = {}
        for table in ["price_cache", "ohlcv_cache", "market_cache"]:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            stats[table] = row[0] if row else 0
        # DB 파일 크기
        stats["db_size_kb"] = round(db_path.stat().st_size / 1024, 1) if db_path.exists() else 0
        conn.close()
        return stats
    except Exception:
        return {}


# ════════════════════════════════════════════════════════
# 모듈 로드 시 DB 자동 초기화
# ════════════════════════════════════════════════════════
try:
    init_db()
except Exception as _e:
    logger.warning(f"DB 초기화 건너뜀: {_e}")
