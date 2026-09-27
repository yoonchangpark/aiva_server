# Railway Cron Job 전용 이미지 — run_scheduled_publish.py를 요일 지정 시각에
# 1회 실행하고 끝난다(상시 서버 아님). Playwright(스크린샷 검토용)가 필요해
# 공식 Playwright 이미지를 베이스로 쓴다 — 브라우저·시스템 의존성이 이미 맞춰져 있다.
FROM mcr.microsoft.com/playwright/python:v1.51.0-jammy

WORKDIR /app

# moviepy(imageio_ffmpeg)가 실행 중에 내려받을 수도 있지만, 매 Cron 실행마다
# 다시 받지 않도록 이미지에 미리 넣어둔다.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "run_scheduled_publish.py"]
