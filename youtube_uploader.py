"""YouTube 업로드 자동화 (YouTube Data API v3, videos.insert).

OAuth2 사용자 인증이 필요하다 — 이미 쓰고 있는 YOUTUBE_API_KEY(단순 API 키, 읽기 전용
통계 조회에만 씀, analytics/youtube_metrics.py)로는 업로드가 안 된다. 채널 소유자
권한으로 영상을 올리려면 OAuth2 사용자 동의가 최초 한 번 필요하다.

최초 설정 (로컬에서, 한 번만):
  1. Google Cloud Console에서 프로젝트를 만들고 YouTube Data API v3를 활성화한다.
  2. OAuth 동의 화면을 구성하고, "데스크톱 앱" 유형의 OAuth 클라이언트 ID를 만든다.
  3. 다운로드한 JSON을 이 폴더에 client_secret.json으로 저장한다 (.gitignore에 이미
     등록되어 있다 — 커밋되지 않는다).
  4. `python youtube_uploader.py --auth`를 실행하면 브라우저가 열리고, 업로드할
     채널 계정으로 로그인·동의하면 token.json에 갱신 토큰이 저장된다. 이후로는
     자동 갱신되어(만료 시 refresh_token 사용) 다시 로그인할 필요가 없다.

사용법:
  python youtube_uploader.py --auth                              # 최초 1회 인증
  python youtube_uploader.py --upload video.mp4 --title "제목"     # 수동 업로드 테스트
"""
from __future__ import annotations

import argparse
import logging
import os

logger = logging.getLogger("youtube_uploader")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "client_secret.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# tenbagger_topic.py의 DISCLAIMER와 같은 문구 — 설명란에도 동일하게 남긴다.
DEFAULT_DISCLAIMER = "이 영상은 재무 데이터 기반 분석이며 투자 권유가 아닙니다. 투자 판단의 책임은 본인에게 있습니다."


def _load_credentials():
    """저장된 토큰으로 인증 정보를 만든다. 만료됐으면 자동 갱신한다."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not os.path.exists(TOKEN_FILE):
        return None

    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds)
    return creds if creds and creds.valid else None


def _save_credentials(creds) -> None:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def run_auth_flow() -> None:
    """브라우저를 열어 채널 소유자 동의를 받는다. 로컬에서 한 번만 실행하면 된다."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(CLIENT_SECRET_FILE):
        raise FileNotFoundError(
            f"{CLIENT_SECRET_FILE}가 없습니다. Google Cloud Console에서 만든 OAuth 클라이언트"
            "(데스크톱 앱) JSON을 이 이름으로 저장하세요."
        )
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    logger.info(f"인증 완료 — 토큰을 {TOKEN_FILE}에 저장했습니다.")


def is_authorized() -> bool:
    """auto_loop 등에서 업로드 가능 여부를 미리 확인할 때 쓴다."""
    return _load_credentials() is not None


def upload_video(
    video_path: str,
    title: str,
    description: str = "",
    tags: list | None = None,
    category_id: str = "25",  # News & Politics — 시황·기업분석류에 가장 가깝다
    privacy_status: str = "public",
) -> str:
    """영상을 채널에 올리고 video_id를 돌려준다.

    영상 인코딩·자막 합성은 이미 끝난 로컬 mp4 파일을 그대로 올리기만 한다.
    실패하면 예외를 던진다 — 호출부(auto_loop)가 잡아서 이번 회차만 건너뛰게 한다.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = _load_credentials()
    if not creds:
        raise RuntimeError(
            "YouTube 인증 토큰이 없습니다. 로컬에서 `python youtube_uploader.py --auth`를 "
            "먼저 실행해 채널 소유자 동의를 받으세요."
        )

    full_description = description.strip()
    if DEFAULT_DISCLAIMER not in full_description:
        full_description = (full_description + "\n\n" + DEFAULT_DISCLAIMER).strip()

    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title[:100],  # YouTube 제목 상한
            "description": full_description[:5000],
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"업로드 진행률: {int(status.progress() * 100)}%")

    video_id = response["id"]
    logger.info(f"업로드 완료: https://youtube.com/shorts/{video_id}")
    return video_id


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--auth", action="store_true", help="최초 1회 OAuth 인증")
    parser.add_argument("--upload", metavar="VIDEO_PATH", help="영상 파일을 수동으로 업로드 테스트")
    parser.add_argument("--title", default="텐배거 헌터 숏츠", help="--upload와 함께 쓰는 제목")
    parser.add_argument("--privacy", default="private", choices=["public", "unlisted", "private"],
                        help="--upload 테스트 시 기본은 private (실수로 공개되지 않게)")
    args = parser.parse_args()

    if args.auth:
        run_auth_flow()
        return 0

    if args.upload:
        video_id = upload_video(args.upload, args.title, privacy_status=args.privacy)
        print(f"업로드 완료: https://youtube.com/shorts/{video_id}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
