"""발행된 영상 검토 기록 — 스크린샷 저장 + 발행 목록 관리.

오너가 영상을 매번 다 보지 않고도 발행된 것을 스크린샷으로 훑어보고,
조회수·좋아요·댓글 추이(analytics/youtube_metrics.refresh_all_metrics)로
품질을 판단할 수 있게 한다.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("review_capture")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "review", "screenshots")
VIDEOS_LOG_FILE = os.path.join(BASE_DIR, "data", "videos.json")


async def capture_publish_screenshot(video_id: str) -> str | None:
    """발행된 YouTube 쇼츠 페이지를 스크린샷으로 저장하고 파일 경로를 반환한다.

    실패해도 예외를 던지지 않는다 — 검토용 부가 기능이라 실패해도 업로드
    자체(auto_loop)를 막아서는 안 된다.
    """
    from playwright.async_api import async_playwright

    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    screenshot_path = os.path.join(SCREENSHOT_DIR, f"{video_id}.png")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="ko-KR",
                viewport={"width": 480, "height": 900},
            )
            await page.goto(
                f"https://www.youtube.com/shorts/{video_id}",
                wait_until="networkidle",
                timeout=30000,
            )
            await page.screenshot(path=screenshot_path)
            await browser.close()
        logger.info(f"발행 스크린샷 저장: {screenshot_path}")
        return screenshot_path
    except Exception as e:
        logger.error(f"발행 스크린샷 캡처 실패 ({video_id}): {e}")
        return None


def log_published_video(video_id: str, title: str, screenshot_path: str | None) -> None:
    """발행 기록을 data/videos.json에 누적한다 — 메트릭 추이 추적의 기준 목록."""
    try:
        with open(VIDEOS_LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            records = json.loads(content) if content else []
    except (FileNotFoundError, json.JSONDecodeError):
        records = []

    records.append({
        "video_id": video_id,
        "title": title,
        "url": f"https://youtube.com/shorts/{video_id}",
        "uploaded_at": datetime.now().isoformat(),
        "screenshot_path": screenshot_path,
    })

    with open(VIDEOS_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def load_published_videos() -> list[dict]:
    """지금까지 발행된 영상 기록을 반환한다."""
    try:
        with open(VIDEOS_LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            return json.loads(content) if content else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []
