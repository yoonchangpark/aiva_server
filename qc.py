"""업로드 전 자동 점검(QC).

2026-11-23 첫 정상 업로드에서 오너가 직접 잡아낸 문제들을 서버가 스스로 잡아 업로드를 막는다.
- 목소리 혼합: ElevenLabs가 실패한 문장만 gTTS(기계음)로 바뀜
- 자막 깨짐: 한글 글꼴을 못 찾아 기본 비트맵 글꼴로 렌더
- 영상과 내용 불일치: 배경 영상이 나레이션과 무관
- 주제 겹침: 최근 올린 숏츠와 같은 주제

렌더 단계가 `RUN` dict에 사실을 적고, run_one_cycle()이 업로드 직전에 `blocking_reasons()`로 판정한다.
Railway Cron은 한 번 실행되고 끝나는 프로세스라 모듈 전역 dict로 충분하다.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger("qc")

RUN: dict = {}

# 장면의 절반 넘게 "안 맞음"이면 막는다.
MISMATCH_BLOCK_RATIO = 0.5
MATCH_MIN_SCORE = 5  # 1~10점, 이 점수 미만이면 "안 맞음"


def reset() -> None:
    RUN.clear()
    RUN.update({"tts_fallback_scenes": [], "tts_total": 0, "font_fallback": False, "alignment": []})


reset()


def _openai_json(content: list, timeout: float = 60.0) -> dict:
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}", "Content-Type": "application/json"},
        json={
            "model": "gpt-4o-mini",
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": content}],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


# ---------- 주제 겹침 ----------

def recent_channel_titles(limit: int = 10) -> list[str]:
    """채널 공개 RSS에서 최근 업로드 제목을 읽는다. 채널 ID는 YOUTUBE_CHANNEL_ID로 바꿀 수 있다.
    서버에 저장 공간이 없어 '이미 쓴 주제' 기록이 매 실행 지워지므로, 채널 자체를 기록으로 쓴다."""
    channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "UCGGuQPJfcNclcsM08UunCkg").strip()  # 기본값: 오너 채널(공개 ID)
    if not channel_id:
        logger.warning("QC: YOUTUBE_CHANNEL_ID가 없어 주제 겹침을 확인할 수 없습니다.")
        return []
    try:
        resp = httpx.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", timeout=15.0)
        resp.raise_for_status()
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.content)
        return [e.findtext("a:title", "", ns) for e in root.findall("a:entry", ns)][:limit]
    except Exception as e:
        logger.warning(f"QC: 채널 최근 업로드 목록 조회 실패: {e}")
        return []


def overlapping_title(topic: str, recent_titles: list[str]) -> str | None:
    """topic이 최근 제목 중 하나와 같은 주제(같은 종목·같은 사건)면 그 제목을, 아니면 None."""
    if not recent_titles:
        return None
    prompt = (
        "새 숏츠 주제가 최근 올린 숏츠 중 하나와 같은 주제(같은 종목, 같은 회사, 같은 사건)인지 판단하세요.\n"
        f"[새 주제]: {topic}\n[최근 제목]:\n" + "\n".join(f"- {t}" for t in recent_titles) +
        '\n순수 JSON으로만 답하세요: {"overlap": true/false, "title": "겹치는 제목 또는 빈 문자열"}'
    )
    try:
        data = _openai_json([{"type": "text", "text": prompt}], timeout=30.0)
        return (data.get("title") or recent_titles[0]) if data.get("overlap") else None
    except Exception as e:
        logger.warning(f"QC: 주제 겹침 판정 실패(겹침 없음으로 처리): {e}")
        return None


# ---------- 영상과 내용 일치 ----------

def score_alignment(video_path: str, samples: list[tuple[float, str]]) -> list[dict]:
    """완성 영상에서 장면마다 한 장씩 캡처해 나레이션과 맞는지 1~10점으로 채점한다."""
    if not samples:
        return []
    from moviepy.editor import VideoFileClip
    from PIL import Image

    content = [{
        "type": "text",
        "text": (
            "숏츠 영상의 장면 캡처와 그 장면의 나레이션입니다. 화면 속 배경 영상이 나레이션 내용과 얼마나 맞는지 "
            "장면마다 1~10점으로 채점하세요(자막 글자는 무시하고 배경 그림만 보세요). "
            '순수 JSON으로만 답하세요: {"scores": [{"scene": 1, "score": 7, "reason": "한 줄"}]}'
        ),
    }]
    clip = VideoFileClip(video_path)
    try:
        for n, (t, narration) in enumerate(samples, 1):
            frame = clip.get_frame(min(t, clip.duration - 0.05))
            buf = io.BytesIO()
            Image.fromarray(frame).convert("RGB").resize((360, 640)).save(buf, format="JPEG", quality=70)
            b64 = base64.b64encode(buf.getvalue()).decode()
            content.append({"type": "text", "text": f"[장면 {n}] 나레이션: {narration}"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}})
    finally:
        clip.close()
    try:
        return _openai_json(content).get("scores", [])
    except Exception as e:
        logger.warning(f"QC: 장면-나레이션 채점 실패: {e}")
        return []


# ---------- 판정 ----------

def blocking_reasons() -> list[str]:
    reasons = []
    fb = RUN.get("tts_fallback_scenes", [])
    if fb:
        reasons.append(f"목소리 혼합: {RUN.get('tts_total', 0)}문장 중 {len(fb)}문장이 기계음(gTTS) (장면 {', '.join(str(i) for i in fb)})")
    if RUN.get("font_fallback"):
        reasons.append("자막 글꼴: 한글 글꼴을 못 찾아 기본 글꼴로 렌더됨")
    scores = RUN.get("alignment", [])
    # 템플릿 모드는 배경이 스톡 영상이 아니라 직접 그린 카드·졸라맨이라 "배경-나레이션 불일치" 기준이 맞지 않는다.
    # 점수는 기록만 하고 차단하지 않는다.
    if scores and not RUN.get("template"):
        bad = [s for s in scores if int(s.get("score", 10)) < MATCH_MIN_SCORE]
        if len(bad) / len(scores) > MISMATCH_BLOCK_RATIO:
            reasons.append(f"영상-내용 불일치: {len(scores)}장면 중 {len(bad)}장면이 {MATCH_MIN_SCORE}점 미만")
    return reasons


def summary_line(status: str, title: str = "") -> str:
    """주간 점검 보고서가 로그에서 바로 읽을 수 있는 한 줄."""
    scores = [int(s.get("score", 0)) for s in RUN.get("alignment", [])]
    return "QC_RESULT " + json.dumps({
        "status": status,
        "title": title,
        "tts_fallback": len(RUN.get("tts_fallback_scenes", [])),
        "tts_total": RUN.get("tts_total", 0),
        "font_fallback": RUN.get("font_fallback", False),
        "alignment_avg": round(sum(scores) / len(scores), 1) if scores else None,
        "topic_overlap": RUN.get("topic_overlap"),
        "reasons": blocking_reasons(),
    }, ensure_ascii=False)
