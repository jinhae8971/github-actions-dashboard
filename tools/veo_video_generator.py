#!/usr/bin/env python3
"""
Gemini API Veo 비디오 생성기
- Veo 3.1 / Veo 3.0 모델 지원
- 텍스트 → 비디오, 이미지 → 비디오 생성
- 해상도: 720p / 1080p / 4K (모델에 따라)
- 비율: 16:9 (landscape) / 9:16 (portrait)

사용법:
  python veo_video_generator.py --api-key YOUR_API_KEY --prompt "프롬프트"
  python veo_video_generator.py --api-key YOUR_API_KEY --prompt "프롬프트" --image input.png
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

try:
    from google import genai
    from google.genai import types
    USE_SDK = True
except ImportError:
    USE_SDK = False

# REST API fallback
import urllib.request
import urllib.error


# ──────────────────────────────────────────────
# 설정 상수
# ──────────────────────────────────────────────
DEFAULT_MODEL = "veo-3.0-generate-preview"
AVAILABLE_MODELS = [
    "veo-3.1-generate-preview",   # 최신 (4K 지원, 네이티브 오디오)
    "veo-3.0-generate-preview",   # 안정 버전
    "veo-2.0-generate-001",       # 레거시
]
POLL_INTERVAL = 15  # seconds
MAX_POLL_ATTEMPTS = 80  # 최대 ~20분 대기
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


# ──────────────────────────────────────────────
# SDK 방식 (google-genai 패키지 사용)
# ──────────────────────────────────────────────
def generate_video_sdk(
    api_key: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    image_path: str = None,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    duration: int = 8,
    negative_prompt: str = None,
    output_path: str = "output_video.mp4",
):
    """google-genai SDK를 사용한 비디오 생성"""
    client = genai.Client(api_key=api_key)

    # Config 구성
    config_params = {}

    if negative_prompt:
        config_params["negative_prompt"] = negative_prompt
    if aspect_ratio:
        config_params["aspect_ratio"] = aspect_ratio
    if duration:
        config_params["duration"] = duration

    # Veo 3.x만 해상도 파라미터 지원
    if "3." in model:
        config_params["resolution"] = resolution

    config = types.GenerateVideosConfig(**config_params) if config_params else None

    # 이미지 입력 처리
    image = None
    if image_path:
        img_path = Path(image_path)
        if not img_path.exists():
            print(f"❌ 이미지 파일을 찾을 수 없습니다: {image_path}")
            sys.exit(1)
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime = mime_map.get(img_path.suffix.lower(), "image/png")
        with open(img_path, "rb") as f:
            img_bytes = f.read()
        image = types.Image(image_bytes=img_bytes, mime_type=mime)
        print(f"🖼️  입력 이미지: {image_path} ({mime})")

    print(f"\n🎬 비디오 생성 시작...")
    print(f"   모델: {model}")
    print(f"   프롬프트: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print(f"   해상도: {resolution} | 비율: {aspect_ratio} | 길이: {duration}초")
    print()

    # 비디오 생성 요청
    operation = client.models.generate_videos(
        model=model,
        prompt=prompt,
        image=image,
        config=config,
    )

    # 폴링
    attempt = 0
    while not operation.done:
        attempt += 1
        if attempt > MAX_POLL_ATTEMPTS:
            print("❌ 타임아웃: 비디오 생성이 너무 오래 걸립니다.")
            sys.exit(1)
        elapsed = attempt * POLL_INTERVAL
        mins, secs = divmod(elapsed, 60)
        print(f"   ⏳ 생성 중... ({mins}분 {secs}초 경과)", end="\r")
        time.sleep(POLL_INTERVAL)
        operation = client.operations.get(operation)

    print(f"\n✅ 비디오 생성 완료!")

    # 저장
    if operation.response and operation.response.generated_videos:
        for i, video in enumerate(operation.response.generated_videos):
            if len(operation.response.generated_videos) > 1:
                name = Path(output_path)
                save_path = str(name.parent / f"{name.stem}_{i+1}{name.suffix}")
            else:
                save_path = output_path

            video.video.save(save_path)
            print(f"💾 저장됨: {save_path}")
    else:
        print("⚠️  생성된 비디오가 없습니다. 프롬프트를 확인해 주세요.")


# ──────────────────────────────────────────────
# REST API 방식 (SDK 없이 사용)
# ──────────────────────────────────────────────
def generate_video_rest(
    api_key: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    image_path: str = None,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    duration: int = 8,
    negative_prompt: str = None,
    output_path: str = "output_video.mp4",
):
    """REST API를 사용한 비디오 생성 (SDK 미설치 시 fallback)"""

    url = f"{BASE_URL}/models/{model}:generateVideos?key={api_key}"

    # 요청 본문 구성
    body = {
        "instances": [{"prompt": prompt}],
        "generationConfig": {
            "aspectRatio": aspect_ratio,
            "duration": str(duration),
        },
    }

    if negative_prompt:
        body["generationConfig"]["negativePrompt"] = negative_prompt
    if "3." in model:
        body["generationConfig"]["resolution"] = resolution

    # 이미지 입력
    if image_path:
        img_path = Path(image_path)
        if not img_path.exists():
            print(f"❌ 이미지 파일을 찾을 수 없습니다: {image_path}")
            sys.exit(1)
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime = mime_map.get(img_path.suffix.lower(), "image/png")
        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        body["instances"][0]["image"] = {
            "bytesBase64Encoded": img_b64,
            "mimeType": mime,
        }
        print(f"🖼️  입력 이미지: {image_path}")

    print(f"\n🎬 비디오 생성 시작 (REST API)...")
    print(f"   모델: {model}")
    print(f"   프롬프트: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print(f"   해상도: {resolution} | 비율: {aspect_ratio} | 길이: {duration}초")
    print()

    # 요청 전송
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"❌ API 오류 ({e.code}): {error_body}")
        sys.exit(1)

    operation_name = result.get("name")
    if not operation_name:
        print(f"❌ 예상치 못한 응답: {json.dumps(result, indent=2)}")
        sys.exit(1)

    # 폴링
    attempt = 0
    while True:
        attempt += 1
        if attempt > MAX_POLL_ATTEMPTS:
            print("❌ 타임아웃")
            sys.exit(1)

        elapsed = attempt * POLL_INTERVAL
        mins, secs = divmod(elapsed, 60)
        print(f"   ⏳ 생성 중... ({mins}분 {secs}초 경과)", end="\r")
        time.sleep(POLL_INTERVAL)

        status_url = f"{BASE_URL}/{operation_name}?key={api_key}"
        with urllib.request.urlopen(status_url) as resp:
            status = json.loads(resp.read().decode())

        if status.get("done"):
            break

    print(f"\n✅ 비디오 생성 완료!")

    # 다운로드
    videos = status.get("response", {}).get("generatedVideos", [])
    if not videos:
        print("⚠️  생성된 비디오가 없습니다.")
        sys.exit(1)

    for i, vid in enumerate(videos):
        download_uri = vid.get("video", {}).get("uri")
        if not download_uri:
            # 인라인 바이트인 경우
            b64_data = vid.get("video", {}).get("bytesBase64Encoded")
            if b64_data:
                if len(videos) > 1:
                    name = Path(output_path)
                    save_path = str(name.parent / f"{name.stem}_{i+1}{name.suffix}")
                else:
                    save_path = output_path
                with open(save_path, "wb") as f:
                    f.write(base64.b64decode(b64_data))
                print(f"💾 저장됨: {save_path}")
            continue

        # URI로 다운로드
        if len(videos) > 1:
            name = Path(output_path)
            save_path = str(name.parent / f"{name.stem}_{i+1}{name.suffix}")
        else:
            save_path = output_path

        dl_url = f"{download_uri}&key={api_key}" if "?" in download_uri else f"{download_uri}?key={api_key}"
        urllib.request.urlretrieve(dl_url, save_path)
        print(f"💾 저장됨: {save_path}")


# ──────────────────────────────────────────────
# CLI 엔트리포인트
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="🎬 Gemini API Veo 비디오 생성기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 기본 텍스트 → 비디오
  python veo_video_generator.py --api-key YOUR_KEY \\
    --prompt "서울 남산타워의 야경, 시네마틱 드론 촬영"

  # 이미지 → 비디오 (이미지 기반)
  python veo_video_generator.py --api-key YOUR_KEY \\
    --prompt "카메라가 천천히 줌인하면서 벚꽃이 날린다" \\
    --image cherry_blossom.png

  # 4K 세로 영상 (Veo 3.1)
  python veo_video_generator.py --api-key YOUR_KEY \\
    --model veo-3.1-generate-preview \\
    --prompt "스마트폰용 제품 소개 영상" \\
    --resolution 4k --aspect-ratio 9:16

  # 네거티브 프롬프트 포함
  python veo_video_generator.py --api-key YOUR_KEY \\
    --prompt "평화로운 해변 일몰 장면" \\
    --negative-prompt "사람, 텍스트, 워터마크"
        """,
    )

    parser.add_argument("--api-key", required=True, help="Gemini API 키")
    parser.add_argument("--prompt", required=True, help="영상 생성 프롬프트 (영어 권장)")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=AVAILABLE_MODELS, help=f"모델 선택 (기본: {DEFAULT_MODEL})")
    parser.add_argument("--image", default=None, help="입력 이미지 경로 (이미지→비디오)")
    parser.add_argument("--resolution", default="720p", choices=["720p", "1080p", "4k"], help="해상도 (기본: 720p)")
    parser.add_argument("--aspect-ratio", default="16:9", choices=["16:9", "9:16"], help="화면 비율 (기본: 16:9)")
    parser.add_argument("--duration", type=int, default=8, choices=[4, 5, 6, 7, 8], help="영상 길이 초 (기본: 8)")
    parser.add_argument("--negative-prompt", default=None, help="제외할 요소 (네거티브 프롬프트)")
    parser.add_argument("--output", default="output_video.mp4", help="출력 파일명 (기본: output_video.mp4)")

    args = parser.parse_args()

    print("=" * 60)
    print("  🎬 Gemini Veo 비디오 생성기")
    print("=" * 60)

    if USE_SDK:
        print("📦 google-genai SDK 감지됨 → SDK 모드")
        generate_video_sdk(
            api_key=args.api_key,
            prompt=args.prompt,
            model=args.model,
            image_path=args.image,
            resolution=args.resolution,
            aspect_ratio=args.aspect_ratio,
            duration=args.duration,
            negative_prompt=args.negative_prompt,
            output_path=args.output,
        )
    else:
        print("📦 google-genai SDK 미설치 → REST API 모드")
        print("   (SDK 설치: pip install google-genai)")
        generate_video_rest(
            api_key=args.api_key,
            prompt=args.prompt,
            model=args.model,
            image_path=args.image,
            resolution=args.resolution,
            aspect_ratio=args.aspect_ratio,
            duration=args.duration,
            negative_prompt=args.negative_prompt,
            output_path=args.output,
        )

    print("\n🎉 완료!")


if __name__ == "__main__":
    main()
