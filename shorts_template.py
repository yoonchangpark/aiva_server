"""숏츠 고정 템플릿 — 졸라맨 진행자 + 데이터 카드 (2026-11-24 오너 확정 시안).

Pexels 스톡 영상 대신 매 장면을 같은 틀로 코드가 그린다. AI 그림 생성 없음.
시안: https://claude.ai/artifact/PU8Hiu3tfSaBpcaUJJRffE , 인터뷰 기록: ops-interview/shorts-template.md

장면 종류
- hook     : 첫 장면. 큰 졸라맨 + 종목명·핵심 문장
- card     : DART 확인 숫자 카드 + 작은 졸라맨 말풍선
- bars     : facts의 "A → B" 값을 전후 막대로
- headline : 네이버 뉴스 검색 최신 기사 제목·언론사·날짜를 다시 그린 카드 (기사 사진은 쓰지 않음 — 저작권)
- photo    : Wikimedia Commons 자유 이용 사진 + 촬영자 표기
- site     : 텐배거 사이트의 그 종목 분석 화면 캡처
- talk     : 졸라맨 + 종목 한 줄 (나머지 장면)

`CTX`가 채워져 있으면(텐배거 모드) 템플릿 모드다. 렌더 결과는 1080x1920 PNG이고,
자막은 영상 합성 단계가 아래 고정 영역(y≥1450)에 얹는다.
"""
from __future__ import annotations

import html
import io
import logging
import os
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("shorts_template")

W, H = 1080, 1920
CONTENT_BOTTOM = 1440  # 이 아래는 자막 자리
BG = (10, 15, 30)
HEADER_BG = (16, 22, 44)
CARD_BG = (20, 30, 58)
CARD_LINE = (60, 80, 130)
INK = (245, 245, 245)
ACCENT = (255, 196, 0)
UP = (255, 82, 82)
SUB = (150, 160, 180)

CTX: dict = {}  # name, ticker, sector, facts, kind_label, news, photo, site_png


def reset() -> None:
    CTX.clear()


def is_active() -> bool:
    return bool(CTX.get("name"))


_FONT_CANDIDATES = {
    True: ["malgunbd.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "NanumGothicBold.ttf"],
    False: ["malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "NanumGothic.ttf"],
}


def font(size: int, bold: bool = True):
    for f in _FONT_CANDIDATES[bold]:
        try:
            return ImageFont.truetype(f, size)
        except IOError:
            continue
    import qc
    qc.RUN["font_fallback"] = True
    return ImageFont.load_default()


# ---------- 그리기 부품 ----------

def figure(d, cx, top, s=1.0, mood="happy", pose="point", col=INK):
    """졸라맨. 표정 happy/surprised/neutral, 자세 point/up/down."""
    w = max(4, int(10 * s)); r = int(70 * s)
    d.ellipse([cx - r, top, cx + r, top + 2 * r], outline=col, width=w)
    ey = top + int(r * 0.85); ex = int(r * 0.35)
    if mood == "surprised":
        for x in (cx - ex, cx + ex):
            d.ellipse([x - 10 * s, ey - 14 * s, x + 10 * s, ey + 14 * s], fill=col)
        d.ellipse([cx - 16 * s, top + int(r * 1.3), cx + 16 * s, top + int(r * 1.6)], outline=col, width=max(3, int(6 * s)))
    else:
        for x in (cx - ex, cx + ex):
            d.ellipse([x - 9 * s, ey - 9 * s, x + 9 * s, ey + 9 * s], fill=col)
        if mood == "neutral":
            d.line([cx - 24 * s, top + int(r * 1.4), cx + 24 * s, top + int(r * 1.4)], fill=col, width=max(3, int(6 * s)))
        else:
            d.arc([cx - 30 * s, top + int(r * 1.05), cx + 30 * s, top + int(r * 1.55)], 10, 170, fill=col, width=max(3, int(6 * s)))
    neck = top + 2 * r; hip = neck + int(190 * s); sh = neck + int(45 * s)
    d.line([cx, neck, cx, hip], fill=col, width=w)
    arms = {
        "point": [(130, -70), (-80, 100)],
        "up": [(95, -130), (-95, -130)],
        "down": [(90, 90), (-90, 90)],
    }.get(pose, [(90, 90), (-90, 90)])
    for dx, dy in arms:
        d.line([cx, sh, cx + int(dx * s), sh + int(dy * s)], fill=col, width=w)
    for dx in (70, -70):
        d.line([cx, hip, cx + int(dx * s), hip + int(150 * s)], fill=col, width=w)


def figure_height(s: float) -> int:
    return int((140 + 190 + 150) * s)


def bubble(d, box, text, f):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=36, fill=INK)
    d.polygon([(x0 + 20, y1 - 40), (x0 + 50, y1), (x0 - 60, y1 - 10)], fill=INK)
    tw = d.textlength(text, font=f)
    d.text(((x0 + x1 - tw) / 2, (y0 + y1) / 2 - f.size * 0.6), text, font=f, fill=BG)


def fit_lines(d, text, f_size, max_w, max_lines=3, bold=True):
    """글자 폭에 맞춰 줄바꿈하고, 넘치면 글자 크기를 줄인다."""
    size = f_size
    while size >= 36:
        f = font(size, bold)
        words, lines, cur = text.split(), [], ""
        for w_ in words:
            t = (cur + " " + w_).strip()
            if d.textlength(t, font=f) <= max_w:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w_
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(d.textlength(l, font=f) <= max_w for l in lines):
            return f, lines
        size -= 6
    return font(36, bold), [text[:30]]


def base(kind_label: str = ""):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 230], fill=HEADER_BG)
    d.text((60, 62), CTX.get("name", ""), font=font(56), fill=INK)
    sub = " · ".join(x for x in (CTX.get("kind_label", ""), CTX.get("sector", "")) if x)
    d.text((60, 140), sub[:34], font=font(36, False), fill=SUB)
    return im, d


# ---------- 장면 ----------

def frame_hook(narration: str):
    im, d = base()
    d.text((70, 330), "텐배거 헌터", font=font(52), fill=ACCENT)
    f, lines = fit_lines(d, CTX.get("name", ""), 120, W - 140, 1)
    d.text((70, 410), lines[0], font=f, fill=INK)
    f2, lines2 = fit_lines(d, CTX.get("hook_line") or narration, 70, W - 140, 2)
    y = 580
    for l in lines2:
        d.text((70, y), l, font=f2, fill=UP if any(c.isdigit() for c in l) else INK); y += f2.size + 24
    figure(d, W // 2, CONTENT_BOTTOM - figure_height(1.2) - 20, 1.2, "surprised", "up")
    return im


def frame_card():
    facts = [f for f in CTX.get("facts", []) if f.get("label")][:4]
    if not facts:
        return None
    im, d = base()
    x0, y0, x1 = 60, 290, 1020
    y1 = y0 + 150 + 170 * max(1, len(facts))
    d.rounded_rectangle([x0, y0, x1, y1], radius=40, fill=CARD_BG, outline=CARD_LINE, width=4)
    d.text((110, y0 + 45), "DART로 확인한 숫자", font=font(44), fill=ACCENT)
    y = y0 + 150
    for f in facts:
        label = f"{f['label']}" + (f" ({f['period']})" if f.get("period") else "")
        d.text((110, y), label, font=font(40, False), fill=SUB)
        fv, lv = fit_lines(d, str(f.get("value", "")), 58, x1 - x0 - 100, 1)
        d.text((110, y + 55), lv[0], font=fv, fill=INK)
        y += 170
    fy = max(y1 + 40, CONTENT_BOTTOM - figure_height(0.8) - 10)
    figure(d, 200, fy, 0.8, "happy", "point")
    bubble(d, (390, fy + 20, 1010, fy + 170), "숫자로 보면 이렇습니다", font(46))
    return im


_NUM = r"(-?[\d,.]+)\s*(조|억)?"


def _to_eok(num: str, unit: str | None) -> float | None:
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    return v * 10000 if unit == "조" else v


def parse_before_after(value: str):
    """'7.1조 → 11.2조 (1.6배)', '4,003억 → 1조7,319억' 같은 값을 (전, 후) 억 단위로. 못 읽으면 None."""
    if "→" not in value:
        return None
    left, right = value.split("→", 1)
    right = right.split("(")[0]

    def read(s):
        s = s.replace("(적자)", "").replace("(흑자전환)", "").strip()
        m = re.fullmatch(r"(-?[\d,.]+)조\s*([\d,.]+)억", s.replace(" ", ""))
        if m:
            return float(m.group(1).replace(",", "")) * 10000 + float(m.group(2).replace(",", ""))
        m = re.search(_NUM, s)
        return _to_eok(m.group(1), m.group(2)) if m else None

    a, b = read(left), read(right)
    return (a, b) if a is not None and b is not None else None


def frame_bars():
    """facts 중 '전 → 후' 형식인 항목을 막대로. 그릴 게 없으면 None."""
    pairs = []
    for f in CTX.get("facts", []):
        ba = parse_before_after(str(f.get("value", "")))
        if ba:
            pairs.append((f["label"], f.get("period", ""), ba, str(f["value"])))
    if not pairs:
        return None
    im, d = base()
    d.text((70, 290), "전후 비교 (DART)", font=font(48), fill=ACCENT)
    pairs = pairs[:2]
    col_w = (W - 140) // len(pairs)
    top, bottom = 480, 1000
    for i, (label, period, (a, b), raw) in enumerate(pairs):
        cx = 70 + col_w * i + col_w // 2
        mx = max(abs(a), abs(b), 1)
        for j, (v, colr) in enumerate(((a, SUB), (b, UP))):
            h = int((bottom - top - 60) * max(abs(v), 0) / mx)
            bx = cx - 120 + j * 140
            d.rectangle([bx, bottom - h, bx + 100, bottom], fill=colr if v >= 0 else (90, 110, 170))
        d.line([cx - 160, bottom, cx + 160, bottom], fill=CARD_LINE, width=3)
        ps = period.split("→") if "→" in period else ["전", "후"]
        d.text((cx - 120, bottom + 14), ps[0].strip()[:6], font=font(32, False), fill=SUB)
        d.text((cx + 20, bottom + 14), ps[-1].strip()[:6], font=font(32, False), fill=INK)
        tw = d.textlength(label, font=font(50))
        d.text((cx - tw / 2, bottom + 70), label, font=font(50), fill=INK)
        m = re.search(r"\(([\d.]+배)\)", raw)
        if m:
            tw = d.textlength(m.group(1), font=font(64))
            d.text((cx - tw / 2, top - 70), m.group(1), font=font(64), fill=UP)
    figure(d, W // 2, CONTENT_BOTTOM - figure_height(0.6) - 10, 0.6, "happy", "up")
    return im


def frame_headline():
    news = CTX.get("news")
    if not news:
        return None
    im, d = base()
    x0, y0, x1 = 60, 300, 1020
    f, lines = fit_lines(d, news["title"], 68, x1 - x0 - 120, 4)
    y1 = y0 + 160 + len(lines) * (f.size + 28) + 140
    d.rounded_rectangle([x0, y0, x1, y1], radius=30, fill=(250, 250, 247))
    d.rectangle([x0, y0 + 60, x0 + 14, y0 + 260], fill=UP)
    d.text((x0 + 60, y0 + 50), "NEWS", font=font(40), fill=UP)
    y = y0 + 140
    for l in lines:
        d.text((x0 + 60, y), l, font=f, fill=(20, 20, 30)); y += f.size + 28
    d.line([x0 + 60, y1 - 120, x1 - 60, y1 - 120], fill=(210, 210, 215), width=3)
    d.text((x0 + 60, y1 - 95), f"{news['source']} · {news['date']}", font=font(38, False), fill=(110, 110, 120))
    figure(d, 860, CONTENT_BOTTOM - figure_height(0.8) - 10, 0.8, "surprised", "down")
    return im


def frame_photo():
    p = CTX.get("photo")
    if not p:
        return None
    im, d = base()
    box = (90, 290, 990, 1060)
    try:
        ph = Image.open(io.BytesIO(p["bytes"])).convert("RGB")
        bw, bh = box[2] - box[0], box[3] - box[1]
        scale = max(bw / ph.width, bh / ph.height)
        ph = ph.resize((int(ph.width * scale), int(ph.height * scale)))
        l = (ph.width - bw) // 2; t = (ph.height - bh) // 2
        im.paste(ph.crop((l, t, l + bw, t + bh)), box[:2])
    except Exception as e:
        logger.warning(f"사진 합성 실패: {e}")
        return None
    d.rectangle([box[0], box[3] - 110, box[2], box[3]], fill=(0, 0, 0))
    fc, lc = fit_lines(d, p.get("caption", CTX.get("name", "")), 48, box[2] - box[0] - 60, 1)
    d.text((box[0] + 30, box[3] - 90), lc[0], font=fc, fill=INK)
    fcr, lcr = fit_lines(d, f"사진: {p.get('credit', '')} / Wikimedia Commons ({p.get('license', '')})", 28, W - 180, 1, bold=False)
    d.text((box[0], box[3] + 16), lcr[0], font=fcr, fill=SUB)
    figure(d, 150, CONTENT_BOTTOM - figure_height(0.6) - 10, 0.6, "happy", "point")
    return im


def frame_site():
    png = CTX.get("site_png")
    if not png or not os.path.exists(png):
        return None
    im, d = base()
    d.text((70, 280), "텐배거에서 직접 확인", font=font(48), fill=ACCENT)
    shot = Image.open(png).convert("RGB")
    pw = 640; ph_ = int(pw * shot.height / shot.width)
    ph_ = min(ph_, 1040)
    shot = shot.resize((pw, int(pw * shot.height / shot.width))).crop((0, 0, pw, ph_))
    x = (W - pw) // 2; y = 370
    d.rounded_rectangle([x - 16, y - 16, x + pw + 16, y + ph_ + 16], radius=36, fill=(40, 50, 80))
    im.paste(shot, (x, y))
    figure(d, 140, CONTENT_BOTTOM - figure_height(0.6) - 10, 0.6, "happy", "point")
    return im


_POSES = [("happy", "point"), ("neutral", "down"), ("happy", "up"), ("surprised", "down")]


def frame_talk(narration: str, idx: int):
    im, d = base()
    mood, pose = _POSES[idx % len(_POSES)]
    if any(k in narration for k in ("위험", "리스크", "주의", "하락", "적자")):
        mood, pose = "surprised", "down"
    nums = re.findall(r"[\d,.]+\s*(?:조|억|%|배|년)", narration)
    if nums:
        f, lines = fit_lines(d, nums[0], 160, W - 140, 1)
        tw = d.textlength(lines[0], font=f)
        d.text(((W - tw) / 2, 360), lines[0], font=f, fill=UP)
    figure(d, W // 2, CONTENT_BOTTOM - figure_height(1.0) - 20, 1.0, mood, pose)
    return im


# ---------- 배치 ----------

def assign_kinds(n_scenes: int, card_idx: int | None) -> list[str]:
    """장면 순서에 템플릿 종류를 배정한다. 0=hook, card 뒤=bars, 중간=headline/photo, 끝에서 두 번째=site."""
    kinds = ["talk"] * n_scenes
    if n_scenes == 0:
        return kinds
    kinds[0] = "hook"
    if card_idx is None:
        card_idx = min(2, n_scenes - 1)
    used = {0}
    if card_idx not in used:
        kinds[card_idx] = "card"; used.add(card_idx)
    # 합성 단계가 짧은 장면을 둘씩 묶어 한 그림만 보여 주므로, 특별 장면끼리는 한 칸 이상 띄운다.
    def free(p):
        return 0 < p < n_scenes and not ({p - 1, p, p + 1} & used)

    # 우선순위: 막대 > 텐배거 화면(오너: "실제 우리 시스템을 보여주니 실감난다") > 헤드라인 > 사진
    for k, pos in (("bars", card_idx + 2), ("site", n_scenes - 2), ("headline", n_scenes // 2), ("photo", (n_scenes * 2) // 3)):
        p = pos
        while not free(p) and p < n_scenes - 1:
            p += 1
        if free(p):
            kinds[p] = k; used.add(p)
    return kinds


def render_scene(kind: str, narration: str, idx: int, out_path: str) -> bool:
    """장면 1개를 PNG로 저장. 재료가 없는 종류(뉴스·사진·사이트 실패 등)는 talk로 대신한다."""
    try:
        im = None
        if kind == "hook":
            im = frame_hook(narration)
        elif kind == "card":
            im = frame_card()
        elif kind == "bars":
            im = frame_bars()
        elif kind == "headline":
            im = frame_headline()
        elif kind == "photo":
            im = frame_photo()
        elif kind == "site":
            im = frame_site()
        if im is None:
            im = frame_talk(narration, idx)
        im.save(out_path)
        return True
    except Exception as e:
        logger.warning(f"템플릿 장면 렌더 실패({kind}): {e}")
        return False


# ---------- 재료 수집 (실패해도 파이프라인은 계속) ----------

def fetch_news(query: str) -> dict | None:
    """네이버 뉴스 검색 최신 1건 → {title, source, date}. 기사 사진은 가져오지 않는다."""
    cid, secret = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if not (cid and secret):
        return None
    import httpx
    try:
        r = httpx.get("https://openapi.naver.com/v1/search/news.json",
                      params={"query": query, "display": 5, "sort": "date"},
                      headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret}, timeout=10.0)
        r.raise_for_status()
        for it in r.json().get("items", []):
            title = html.unescape(re.sub(r"<[^>]+>", "", it.get("title", ""))).strip()
            if query.split()[0] not in title:
                continue
            link = it.get("originallink") or it.get("link") or ""
            source = re.sub(r"^www\.", "", re.sub(r"^https?://", "", link).split("/")[0])
            try:
                date = parsedate_to_datetime(it["pubDate"]).strftime("%Y.%m.%d")
            except Exception:
                date = datetime.now().strftime("%Y.%m.%d")
            return {"title": title, "source": source, "date": date}
    except Exception as e:
        logger.warning(f"뉴스 검색 실패: {e}")
    return None


_FREE_LICENSES = ("CC BY", "CC0", "Public domain", "CC-BY", "PD")


def fetch_commons_photo(query: str) -> dict | None:
    """Wikimedia Commons에서 자유 이용 사진 1장 → {bytes, credit, license, caption}."""
    import httpx
    headers = {"User-Agent": "tenbagger-shorts/1.0 (automated video renderer)"}
    try:
        r = httpx.get("https://commons.wikimedia.org/w/api.php", headers=headers, timeout=15.0, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": 6, "gsrlimit": 8, "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 1200,
        })
        r.raise_for_status()
        pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for p in pages:
            info = (p.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            lic = meta.get("LicenseShortName", {}).get("value", "")
            if not any(lic.startswith(x) for x in _FREE_LICENSES) or info.get("width", 0) < 600:
                continue
            artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip() or "작자 미상"
            img = httpx.get(info.get("thumburl") or info["url"], headers=headers, timeout=20.0)
            img.raise_for_status()
            return {"bytes": img.content, "credit": artist[:40], "license": lic, "caption": CTX.get("name", query),
                    "page": info.get("descriptionurl", "")}
    except Exception as e:
        logger.warning(f"Commons 사진 검색 실패: {e}")
    return None


async def capture_site(ticker: str, out_path: str) -> bool:
    """텐배거 사이트의 종목 분석 화면을 캡처한다."""
    base_url = os.getenv("TENBAGGER_PUBLIC_URL") or os.getenv("TENBAGGER_API_BASE", "")
    if not base_url:
        return False
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 430, "height": 760}, device_scale_factor=2)
            await page.goto(f"{base_url.rstrip('/')}/index.html?ticker={ticker}", timeout=30000)
            await page.wait_for_timeout(8000)
            await page.screenshot(path=out_path)
            await browser.close()
        return True
    except Exception as e:
        logger.warning(f"텐배거 화면 캡처 실패: {e}")
        return False


async def prepare(c: dict, kind_label: str, work_dir: str) -> None:
    """텐배거 후보 c로 템플릿 재료를 모은다. 하나라도 실패하면 그 장면만 talk로 대신한다."""
    import asyncio
    CTX.clear()
    CTX.update({
        "name": c.get("name", ""), "ticker": c.get("ticker", ""), "sector": c.get("sector", ""),
        "facts": c.get("facts", []) if c.get("dart_verified") else [], "kind_label": kind_label,
        "hook_line": c.get("narrative", "").split("→")[-1].strip(),
    })
    CTX["news"] = await asyncio.to_thread(fetch_news, c.get("name", ""))
    CTX["photo"] = await asyncio.to_thread(fetch_commons_photo, c.get("name", ""))
    os.makedirs(work_dir, exist_ok=True)
    site_png = os.path.join(work_dir, f"site_{c.get('ticker', 'x')}.png")
    if await capture_site(c.get("ticker", ""), site_png):
        CTX["site_png"] = site_png
    logger.info(
        f"[템플릿 재료] 뉴스 {'O' if CTX.get('news') else 'X'} / 사진 {'O' if CTX.get('photo') else 'X'} / "
        f"사이트 {'O' if CTX.get('site_png') else 'X'} / 숫자 {len(CTX['facts'])}개"
    )


def photo_credit_line() -> str:
    p = CTX.get("photo")
    if not p:
        return ""
    return f"사진: {p.get('credit', '')}, {p.get('license', '')}, Wikimedia Commons {p.get('page', '')}".strip()
