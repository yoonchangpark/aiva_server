"""Railway Cron 전용 진입점 — 요일 지정 시각에 1회 실행되고 끝난다.

서버를 상시 띄워두는 대신, Railway의 Cron Schedule(예: "30 9 * * 1,3,5" = KST
월/수/금 18:30)이 이 스크립트를 그 시각에만 실행한다. Railway Cron Job은 실제로
돌아간 시간만큼만 과금되므로, `server.py`의 auto_loop처럼 계속 켜둔 채 대기하는
것보다 훨씬 저렴하다.

로컬에서는 필요 없다 — 로컬은 `server.py`의 auto_loop(기본은 비활성화)이나
수동 실행으로 충분하다.
"""
from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_scheduled_publish")


async def main() -> None:
    from server import refresh_published_metrics, run_one_cycle

    await refresh_published_metrics()
    status = await run_one_cycle()
    logger.info(f"실행 결과: {status}")


if __name__ == "__main__":
    asyncio.run(main())
