# 전사 (음성 → raw transcript)

교정 단계는 타임스탬프가 있는 TXT를 입력으로 받는다. 그 TXT를 얻는 경로는 세 가지이며 결과 형식은 같다.

| 경로 | 언제 쓰나 | 비용 | 준비 |
| --- | --- | --- | --- |
| `external` | 이미 다른 앱(Clova Note, Otter 등)으로 전사했다 | 없음 | 내보낸 TXT를 `input/`에 둔다 |
| `whisper` | 로컬에서 끝내고 싶다, 네트워크·키가 없다 | 없음 (GPU 권장) | `pip install faster-whisper` |
| `soniox` | 한국어 품질과 속도를 우선한다 | API 과금 | `pip install httpx`, `SONIOX_API_KEY` 환경 변수 |

```powershell
python pipeline/lecture.py transcribe "<강의명>" --provider external
python pipeline/lecture.py transcribe "<강의명>" --media "input/강의.mp4" --provider whisper --language ko
python pipeline/lecture.py transcribe "<강의명>" --media "input/강의.mp3" --provider soniox --language ko
```

- 결과는 `work/transcribe/<파일명>.<provider>.txt`에 저장되고 `inspect`의 `raw_transcripts`에 자동으로 포함된다. 같은 입력·옵션이면 재실행해도 캐시를 재사용한다.
- 영상은 ffmpeg로 16kHz 모노 MP3를 먼저 뽑아 `work/transcribe/`에 둔다. ffmpeg는 PATH, `LECTURE_FFMPEG`, `--ffmpeg` 순으로 찾는다. 음성 파일만 있고 ffmpeg가 없으면 원본을 그대로 쓴다.
- `whisper` 기본 모델은 `large-v3-turbo`다. CPU만 있으면 `--model small --compute-type int8`로 시작한다. 모델은 처음 한 번 내려받는다.
- `soniox`는 교안 PDF에서 뽑은 영문 용어 목록을 context로 함께 보낸다. 끄려면 `--no-pdf-terms`. 업로드한 파일과 전사 결과는 완료 후 Soniox 쪽에서 삭제 요청한다.
- `external`은 아무것도 실행하지 않고 `input/`의 TXT와 타임스탬프 줄 수만 보고한다. 원본 TXT는 수정하지 않는다.

## 출력 형식

```text
<제목>
<provider / model / 총 길이>

00:00:00
첫 블록의 문장들.
...

00:00:45
다음 블록.
```

약 45초 단위로 `HH:MM:SS` 한 줄과 그 뒤의 문장들이 한 블록을 이룬다. 교정 프롬프트는 이 타임스탬프를 시간 메타데이터로만 쓰고 H2 구간 범위로 통합한다. 외부 앱의 TXT는 블록 단위가 달라도 같은 규칙으로 처리된다.

## 에이전트 지침

`prepare`가 `transcribe` 작업을 남기면 사용자에게 어느 경로를 쓸지 확인하고 명령을 실행한다. 전사 결과를 교정했다고 가장하지 않으며, 전사가 끝나면 `refinement.md`로 넘어간다. STT가 못 알아들은 구간은 교정 단계에서 매끈하게 만들지 말고 보존한다.
