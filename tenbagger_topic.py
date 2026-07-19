"""
텐배거 헌터 연동 모듈 — "미래 텐배거 추천" 모드
/api/v2/shorts-feed?mode=candidate 에서 탑다운 발굴 후보를 가져와
쇼츠 파이프라인의 (주제, 문맥 데이터) 형식으로 변환한다.

⚠️ 2026-07 변경: 예전엔 /api/screener?grade=TENBAGGER,COMPOUNDER (구 스코어링)를 썼으나,
포스트모템(scoring_postmortem.md)에서 그 등급이 실제 텐배거와 역상관임이 확인됐다.
그래서 이제는 tenbagger의 shorts-feed(mode=candidate) — 거시→산업→해자 탑다운 발굴 +
DART 재무로 검증한 소수 정예 후보 — 를 그대로 쓴다.

환경변수:
  TENBAGGER_API_BASE — 텐배거 API 주소 (기본: http://localhost:8000)
"""
import os
import logging
import httpx

from tenbagger_card import make_score_card

logger = logging.getLogger(__name__)

DISCLAIMER = "이 영상은 재무 데이터 기반 분석이며 투자 권유가 아닙니다. 투자 판단의 책임은 본인에게 있습니다."


def _fmt(v, suffix="", digits=1):
    if v is None:
        return "N/A"
    try:
        return f"{float(v):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def _build_context(c: dict) -> str:
    """shorts-feed candidate 항목 → GPT 대본용 팩트 문자열"""
    lines = [
        f"종목명: {c['name']} ({c['ticker']})",
        f"업종: {c.get('sector', '')}",
        f"발굴 논리(거시→산업→해자): {c.get('narrative', '')}",
        f"테마 유형: {c.get('thesis_type', '')}",
    ]
    for f in c.get("facts", []):
        period = f.get("period", "")
        lines.append(f"{f.get('label')}: {f.get('value')}" + (f" ({period})" if period else ""))
    if c.get("target_scenario"):
        lines.append(f"향후 시나리오: {c['target_scenario']}")
    if not c.get("dart_verified"):
        lines.append("※ 재무 배수 DART 대조 미검증 — 화면 숫자로 쓰지 말 것")
    return "\n".join(lines)


def _card_metrics(c: dict) -> list:
    """shorts-feed facts[] → 카드용 (라벨, 값, None) 리스트. facts는 이미 포맷된 문자열이라 미니바 비율은 없음."""
    return [(f.get("label"), f.get("value"), None) for f in c.get("facts", []) if f.get("label")]


async def _fetch_qualitative(base: str, ticker: str) -> str:
    """AI 정성 분석 (사업모델·해자) — 실패해도 파이프라인은 계속 (빈 문자열 반환). shorts-feed의 narrative를 보강하는 용도."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base}/api/v2/company/{ticker}/qualitative", timeout=60.0
            )
            resp.raise_for_status()
            q = resp.json()
        moat = q.get("moat_detail") or {}
        parts = []
        if q.get("business_model"):
            parts.append(f"사업모델: {q['business_model']}")
        if q.get("moat_score") is not None:
            parts.append(f"경쟁우위(해자) 점수: {q['moat_score']}/10 — {moat.get('summary', '')}")
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"정성 분석 조회 실패 (shorts-feed 데이터만으로 진행): {e}")
        return ""


async def _fetch_candidates(base: str, limit: int = 20) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base}/api/v2/shorts-feed",
            params={"mode": "candidate", "limit": limit},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])


async def pick_tenbagger_topic(exclude_topics: list[str] | None = None,
                               clip_dir: str = ".",
                               render_clips: bool = True) -> tuple[str, str, dict]:
    """
    shorts-feed(mode=candidate) 목록 중 히스토리에 없는 첫 종목을 골라 (주제, 문맥, asset_clips) 반환.
    asset_clips: {'card': mp4경로} — 영상의 source_type=='card' 씬에 삽입됨.
    render_clips=False 면 카드 mp4 렌더를 건너뛴다(대본 프리뷰용 — 빠름).
    실패 시 ValueError — 호출 측에서 기존 트렌드 모드로 폴백할 것.
    """
    exclude = exclude_topics or []
    base = os.getenv("TENBAGGER_API_BASE", "http://localhost:8000").rstrip("/")

    candidates = await _fetch_candidates(base)
    if not candidates:
        raise ValueError("텐배거 후보 없음 — tenbagger의 shorts-feed(mode=candidate) 목록이 비어 있음")

    for c in candidates:
        if any(c["name"] in t for t in exclude):
            continue
        topic = f"{c['name']}, 지금 텐배거 후보로 보이는 이유"

        qualitative = await _fetch_qualitative(base, c["ticker"])
        narrative_block = f"\n[AI 정성 분석 — 보강]\n{qualitative}\n" if qualitative else ""

        # 텐배거 분석 카드 클립 생성 (영상 source_type=='card' 씬에 삽입)
        asset_clips = {}
        if render_clips:
            os.makedirs(clip_dir, exist_ok=True)
            card_path = os.path.join(clip_dir, f"card_{c['ticker']}.mp4")
            card_data = {
                "name": c["name"],
                "ticker": c["ticker"],
                "subtitle": c.get("sector", ""),
                "metrics": _card_metrics(c),
            }
            if make_score_card(card_data, card_path):
                asset_clips["card"] = card_path

        card_rule = (
            "3-1. Scene 2 또는 3 중 하나는 반드시 source_type을 'card'로 지정하라 "
            "(DART 재무로 검증한 해자 지표 카드가 화면에 뜬다). "
            "해당 narration은 '재무 데이터로 검증한 결과' 맥락으로, 카드를 가리키듯 말하라 "
            "(예: \"숫자로만 보면 이렇습니다\").\n"
            if asset_clips.get("card") else ""
        )
        context = (
            f"{_build_context(c)}\n{narrative_block}\n"
            f"[대본 작성 가이드 — 탑다운 발굴 구조: 거시 → 산업 독점 → 실적 폭발(숫자)]\n"
            f"1. 훅(첫 Scene): {c['name']}을(를) 한 문장으로 각인시켜라. "
            f"'{c.get('narrative', '')}' 라는 발굴 논리를 임팩트 있게 던져라. "
            f"단조로운 수치 나열로 시작하지 마라.\n"
            f"2. 거시 흐름 → 그 산업이 필연적으로 커질 수밖에 없는 이유 → 이 회사가 그 산업에서 "
            f"독점/과점적 위치인 이유 순서로 논리를 쌓아라 (거시→산업→해자 구조).\n"
            f"3. 위 facts(DART 실공시)만 화면 숫자로 인용하라. 근거 없는 목표주가·확정적 전망은 "
            f"절대 말하지 마라 — 이건 확정된 과거가 아니라 '지금 시점의 시나리오'다.\n"
            f"{card_rule}"
            f"4. ★필수: 이 종목은 아직 결과가 나오지 않은 미래 시나리오다. "
            f"'무조건 오른다', '텐배거 확정' 같은 단정적 표현을 절대 쓰지 마라. "
            f"'~할 가능성', '~라는 시나리오가 있다', '지켜볼 지점' 같은 절제된 표현을 써라.\n"
            f"5. 전체 분량 60~75초. 빠른 리듬으로 끝까지 끌고 가라.\n"
            f"6. 마지막 Scene은 source_type을 반드시 'disclaimer'로 지정하고 narration에 다음 문구를 넣어라: "
            f"\"{c.get('risk_note', DISCLAIMER)} {DISCLAIMER}\" "
            "(이 씬은 TTS 낭독 없이 영상 하단 자막으로만 표시된다.)"
        )
        logger.info(f"텐배거 후보 주제 선정: {topic} (테마: {c.get('thesis_type')})")
        return (topic, context, asset_clips)

    raise ValueError("미사용 텐배거 후보 없음 — shorts-feed candidate 리스트 소진, tenbagger 쪽에 신규 후보 추가 필요")
