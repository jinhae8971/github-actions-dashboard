# 🎬 Gemini Veo 비디오 생성기

Gemini API의 Veo 모델을 활용하여 텍스트/이미지로부터 AI 비디오를 생성하는 Python 도구입니다.

---

## 지원 모델

| 모델 | 해상도 | 오디오 | 특징 |
|-------|--------|--------|------|
| `veo-3.1-generate-preview` | 720p / 1080p / 4K | ✅ 네이티브 | 최신, 세로영상, 영상연장, 참조이미지(3장) |
| `veo-3.0-generate-preview` | 720p / 1080p / 4K | ✅ 네이티브 | 안정 버전 |
| `veo-2.0-generate-001` | 720p / 1080p | ❌ | 레거시 |

## 설치

```bash
# 권장: google-genai SDK 설치
pip install google-genai

# SDK 없이도 REST API로 동작합니다 (추가 설치 불필요)
```

## 사용법

### 기본: 텍스트 → 비디오
```bash
python veo_video_generator.py \
  --api-key YOUR_GEMINI_API_KEY \
  --prompt "A cinematic drone shot flying over Seoul at night with neon lights reflecting on the Han River"
```

### 이미지 → 비디오
```bash
python veo_video_generator.py \
  --api-key YOUR_GEMINI_API_KEY \
  --prompt "Camera slowly zooms in, cherry blossoms fall gently" \
  --image cherry_blossom.png
```

### 4K 세로 영상 (Veo 3.1)
```bash
python veo_video_generator.py \
  --api-key YOUR_GEMINI_API_KEY \
  --model veo-3.1-generate-preview \
  --prompt "A vertical product showcase video for a smartphone" \
  --resolution 4k \
  --aspect-ratio 9:16
```

### 전체 옵션
```bash
python veo_video_generator.py \
  --api-key YOUR_KEY \
  --prompt "프롬프트 (영어 권장)" \
  --model veo-3.0-generate-preview \
  --image input.png \
  --resolution 1080p \
  --aspect-ratio 16:9 \
  --duration 8 \
  --negative-prompt "blurry, text, watermark" \
  --output my_video.mp4
```

## 파라미터 정리

| 파라미터 | 필수 | 기본값 | 설명 |
|---------|------|--------|------|
| `--api-key` | ✅ | - | Gemini API 키 |
| `--prompt` | ✅ | - | 영상 생성 프롬프트 (영어 권장) |
| `--model` | ❌ | veo-3.0-generate-preview | 모델 선택 |
| `--image` | ❌ | - | 입력 이미지 (이미지→비디오) |
| `--resolution` | ❌ | 720p | 720p / 1080p / 4k |
| `--aspect-ratio` | ❌ | 16:9 | 16:9 또는 9:16 |
| `--duration` | ❌ | 8 | 4~8초 |
| `--negative-prompt` | ❌ | - | 제외할 요소 |
| `--output` | ❌ | output_video.mp4 | 출력 파일명 |

## 프롬프트 작성 팁

1. **영어로 작성** — 영어 프롬프트가 훨씬 좋은 결과를 냅니다
2. **시네마틱 디테일** — 카메라 앵글, 조명, 분위기를 명시하세요
3. **네거티브 프롬프트 활용** — 원하지 않는 요소를 명시적으로 제외
4. **짧고 구체적으로** — 핵심 장면 하나에 집중

### 좋은 프롬프트 예시
```
"A slow-motion cinematic shot of rain drops falling on a traditional Korean roof tile,
 warm golden hour lighting, shallow depth of field, serene atmosphere"
```

## 비용 참고

- Veo는 **유료 프리뷰** 모델입니다
- Google AI Studio에서 API 키 발급: https://aistudio.google.com/apikey
- 비용은 생성 요청 단위로 과금됩니다
- 자세한 가격: https://ai.google.dev/pricing

## 주의사항

- 생성에 **1~5분 소요**될 수 있습니다 (해상도에 따라)
- 생성된 영상에는 **SynthID 워터마크**가 포함됩니다
- 일부 국가/지역에서 제한될 수 있습니다
- 사람 얼굴 생성에는 안전 제한이 적용됩니다
