"""
scheduler.py — 가족 자산 관제탑 자동 수집 스케줄러
=====================================================
우선순위 2: APScheduler 기반 장 마감 후 자동 데이터 수집

수집 스케줄 (KST 기준)
─────────────────────────────────────────────────────────────
│ 시간          │ 작업
│ 장중 (09:00~15:30)  │ 30분마다 시장 지표 수집 (KOSPI, KOSDAQ, 환율)
│ 장 마감 (15:35)     │ 전 종목 주가 일봉 수집 + SQLite 캐시 저장
│ 장 마감 (15:40)     │ Google Sheets snapshot 저장
│ 매일 00:10          │ 오래된 캐시 정리 (30일 초과)
─────────────────────────────────────────────────────────────

사용 방법 (두 가지)
────────────────────
A) 독립 프로세스 실행 (권장):
    python scheduler.py

B) Streamlit 앱과 함께 실행:
    app.py 의 상단에서 start_scheduler() 호출 (백그라운드 스레드)

외부 의존성:
    pip install apscheduler>=3.10.0
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


# ════════════════════════════════════════════════════════
# 1. 개별 수집 태스크
# ════════════════════════════════════════════════════════

def task_collect_market_status() -> None:
    """시장 지표 (KOSPI, KOSDAQ, 환율, US10Y) 수집 + 캐시 저장"""
    try:
        from market_collector import get_market_status_v2
        from data_store import set_cached_market
        status = get_market_status_v2()
        set_cached_market(status, key="market_status")
        now = datetime.now(KST).strftime("%H:%M")
        logger.info(f"[{now}] 시장 지표 수집 완료: {list(status.keys())}")
    except Exception as e:
        logger.error(f"시장 지표 수집 실패: {e}")


def task_collect_stock_prices(stock_codes: Optional[dict] = None) -> None:
    """
    전 종목 일봉 주가 수집 + SQLite price_cache 저장.
    stock_codes: {종목명: 종목코드}  — None이면 config.STOCK_CODES 사용
    """
    if stock_codes is None:
        try:
            from config import STOCK_CODES
            stock_codes = STOCK_CODES
        except ImportError:
            logger.error("config.STOCK_CODES 불러오기 실패")
            return

    try:
        from market_collector import get_krx_price
        from data_store import set_cached_price, get_price_with_cache

        success, fail = 0, 0
        for name, code in stock_codes.items():
            try:
                current, prev = get_krx_price(code)
                if current > 0:
                    set_cached_price(code, current, prev)
                    success += 1
                else:
                    fail += 1
            except Exception as e:
                logger.warning(f"{name}({code}) 수집 실패: {e}")
                fail += 1

        now = datetime.now(KST).strftime("%H:%M")
        logger.info(f"[{now}] 주가 수집 완료 — 성공:{success} 실패:{fail}")

    except Exception as e:
        logger.error(f"주가 수집 태스크 실패: {e}")


def task_collect_ohlcv(stock_codes: Optional[dict] = None) -> None:
    """
    전 종목 OHLCV 일봉 수집 + SQLite ohlcv_cache 저장.
    최근 1년치만 수집 (초기 실행 시 자동 백필).
    """
    if stock_codes is None:
        try:
            from config import STOCK_CODES
            stock_codes = STOCK_CODES
        except ImportError:
            return

    try:
        from market_collector import get_krx_ohlcv
        from data_store import save_ohlcv_to_cache, load_ohlcv_from_cache

        from_date = (datetime.now(KST) - timedelta(days=365)).strftime("%Y%m%d")
        total_rows = 0

        for name, code in stock_codes.items():
            try:
                df = get_krx_ohlcv(code, from_date)
                if not df.empty:
                    saved = save_ohlcv_to_cache(code, df)
                    total_rows += saved
            except Exception as e:
                logger.warning(f"OHLCV {name}({code}): {e}")

        logger.info(f"OHLCV 수집 완료 — 총 {total_rows}행 저장")

    except Exception as e:
        logger.error(f"OHLCV 수집 태스크 실패: {e}")


def task_purge_cache() -> None:
    """30일 초과 캐시 데이터 자동 정리"""
    try:
        from data_store import purge_old_cache
        result = purge_old_cache(days_to_keep=30)
        logger.info(f"캐시 정리: {result}")
    except Exception as e:
        logger.error(f"캐시 정리 실패: {e}")


# ════════════════════════════════════════════════════════
# 2. 스케줄러 설정
# ════════════════════════════════════════════════════════

def build_scheduler():
    """
    APScheduler BlockingScheduler 구성 및 반환.
    BackgroundScheduler 로 변경하면 Streamlit 앱 내에서 백그라운드 실행 가능.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        raise ImportError("pip install apscheduler>=3.10.0")

    scheduler = BackgroundScheduler(timezone=KST)

    # ── 장중: 30분마다 시장 지표 수집 (평일 09:00~15:30) ──
    scheduler.add_job(
        task_collect_market_status,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="0,30",
            timezone=KST,
        ),
        id="market_status_intraday",
        name="장중 시장 지표 수집",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # ── 장 마감: 15:35 주가 일봉 수집 ──
    scheduler.add_job(
        task_collect_stock_prices,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=15,
            minute=35,
            timezone=KST,
        ),
        id="stock_prices_eod",
        name="장 마감 주가 수집",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── 장 마감: 15:45 OHLCV 일봉 수집 ──
    scheduler.add_job(
        task_collect_ohlcv,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=15,
            minute=45,
            timezone=KST,
        ),
        id="ohlcv_eod",
        name="장 마감 OHLCV 수집",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── 새벽 캐시 정리: 매일 00:10 ──
    scheduler.add_job(
        task_purge_cache,
        trigger=CronTrigger(hour=0, minute=10, timezone=KST),
        id="purge_cache_daily",
        name="오래된 캐시 정리",
        replace_existing=True,
    )

    return scheduler


# ════════════════════════════════════════════════════════
# 3. Streamlit 연동 (백그라운드 스케줄러)
# ════════════════════════════════════════════════════════

_scheduler_instance = None

def start_scheduler() -> None:
    """
    Streamlit app.py 에서 호출하면 백그라운드 스레드로 스케줄러 시작.
    세션당 1회만 시작 (중복 방지).

    app.py 상단에 아래 코드 추가:
        from scheduler import start_scheduler
        start_scheduler()
    """
    global _scheduler_instance
    if _scheduler_instance is not None and _scheduler_instance.running:
        return   # 이미 실행 중

    try:
        _scheduler_instance = build_scheduler()
        _scheduler_instance.start()
        logger.info("백그라운드 스케줄러 시작")

        # 앱 시작 시 즉시 1회 수집 (캐시 워밍업)
        import threading
        threading.Thread(target=task_collect_market_status, daemon=True).start()

    except Exception as e:
        logger.error(f"스케줄러 시작 실패: {e}")


def stop_scheduler() -> None:
    """스케줄러 종료 (앱 종료 시 호출)"""
    global _scheduler_instance
    if _scheduler_instance and _scheduler_instance.running:
        _scheduler_instance.shutdown(wait=False)
        logger.info("스케줄러 종료")


def get_scheduler_status() -> list[dict]:
    """실행 중인 스케줄 목록 반환 (사이드바 표시용)"""
    if _scheduler_instance is None or not _scheduler_instance.running:
        return []
    return [
        {
            "id":       job.id,
            "name":     job.name,
            "next_run": job.next_run_time.strftime("%m/%d %H:%M") if job.next_run_time else "-",
        }
        for job in _scheduler_instance.get_jobs()
    ]


# ════════════════════════════════════════════════════════
# 4. 독립 실행 (python scheduler.py)
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("═" * 50)
    logger.info("가족 자산 관제탑 — 자동 수집 스케줄러 시작")
    logger.info("═" * 50)

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger

        # 독립 실행용: BlockingScheduler (메인 스레드 점유)
        scheduler = BlockingScheduler(timezone=KST)

        # 동일 스케줄 등록
        scheduler.add_job(task_collect_market_status, CronTrigger(
            day_of_week="mon-fri", hour="9-15", minute="0,30", timezone=KST),
            id="market_intraday", name="장중 시장 지표")

        scheduler.add_job(task_collect_stock_prices, CronTrigger(
            day_of_week="mon-fri", hour=15, minute=35, timezone=KST),
            id="stock_eod", name="장 마감 주가")

        scheduler.add_job(task_collect_ohlcv, CronTrigger(
            day_of_week="mon-fri", hour=15, minute=45, timezone=KST),
            id="ohlcv_eod", name="장 마감 OHLCV")

        scheduler.add_job(task_purge_cache, CronTrigger(
            hour=0, minute=10, timezone=KST),
            id="purge_daily", name="캐시 정리")

        # 시작 즉시 1회 수집
        logger.info("초기 수집 시작...")
        task_collect_market_status()
        task_collect_stock_prices()

        logger.info("스케줄러 대기 중... (Ctrl+C 로 종료)")
        scheduler.start()

    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러 종료")
    except ImportError:
        print("APScheduler 미설치: pip install apscheduler>=3.10.0")
