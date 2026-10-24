# lecture-handout

강의 녹음(또는 녹화)과 교안 PDF를 넣으면, 교정된 서면 강의록에 교안·화면 이미지가 본문 흐름에 맞게 들어간 Markdown 한 벌이 나온다.

추론 API를 내장하지 않는다. 교정과 이미지 대응 같은 의미 판단은 **사용자가 쓰는 코딩 에이전트**(Claude Code, Codex, Gemini CLI 등)가 `AGENTS.md`와 `docs/`를 읽고 수행한다. 이 저장소의 코드는 그 앞뒤의 기계적인 일만 맡는다. PDF 렌더링, 영상 슬라이드 캡처, 전사, 이미지 삽입과 해시 검증.

```text
lectures/<강의명>/
├─ input/     원본 PDF·MP4·MP3·전사 TXT·제공된 Markdown·캡처 이미지 (변경하지 않음)
├─ work/      전사·렌더링·대응표·검증 기록 (캐시, 재실행 가능)
└─ output/    완성본 Markdown과 images/ (이 폴더만 복사하면 열림)
```

## 준비

- Python 3.12, `pip install -r requirements.txt`
- Poppler (`pdftoppm`): PATH에 두거나 `LECTURE_PDFTOPPM`에 실행 파일 경로를 설정한다.
- 선택: ffmpeg (영상에서 음성 추출), `pip install -r requirements-stt.txt` (로컬 whisper 또는 Soniox 전사)

## 사용법

### 1. 에이전트에게 맡기기 (기본)

강의 폴더를 만들고 자료를 넣는다.

```powershell
python pipeline/lecture.py init "algorithms-7W-1"
```

`lectures/algorithms-7W-1/input/`에 녹음 MP3 또는 영상 MP4, 교안 PDF를 넣는다. 다른 앱(Clova Note 등)으로 이미 전사했다면 그 TXT도 함께 넣는다.

이 저장소를 연 코딩 에이전트에게 한 줄로 요청한다.

```text
강의 algorithms-7W-1 작업해줘
```

`AGENTS.md`가 에이전트를 안내한다. 에이전트는 `inspect`로 자료를 확인하고, 전사 TXT가 없으면 전사 경로를 물어본 뒤 `transcribe`를 실행하고, `prepare`로 PDF 페이지와 영상 슬라이드를 뽑고, `prompts/`의 프롬프트로 전사를 교정하고, 이미지를 본문 문단에 대응시켜 `work/mapping.json`을 쓴 뒤 `apply`와 `verify`까지 진행한다.

끝나면 `lectures/algorithms-7W-1/output/`을 통째로 가져간다. Markdown 하나와 `images/`가 들어 있고 Obsidian, Typora 등에서 바로 열린다.

### 2. 기계적인 단계만 직접 돌리기

에이전트 없이 쓸 수도 있다.

```powershell
python pipeline/lecture.py transcribe "algorithms-7W-1" --media "input/lecture.mp4" --provider whisper --language ko
python pipeline/lecture.py prepare "algorithms-7W-1"
```

`work/transcribe/`에 전사 TXT, `work/pdf-pages/`에 교안 페이지 PNG, `work/capture/`에 슬라이드 캡처가 생기고, `work/prepare.json`에 남은 의미 작업(교정, 이미지 대응)이 기록된다. 교정은 `prompts/audioscript-refiner-1.5.3.md`를 아무 LLM에 붙여 수행하고, 대응표 `work/mapping.json`을 [도구 사용](docs/commands.md)의 형식으로 쓴 뒤 `apply`와 `verify`를 실행한다.

### 전사 경로

| 경로 | 준비 | 비용 |
| --- | --- | --- |
| `external` | 외부 앱에서 내보낸 타임스탬프 TXT를 `input/`에 둔다 | 없음 |
| `whisper` | `pip install faster-whisper` (GPU 권장) | 없음 |
| `soniox` | `pip install httpx`, 환경 변수 `SONIOX_API_KEY` | API 과금 |

셋 다 같은 형식의 TXT를 만들며, 이후 단계는 출처를 구분하지 않는다. 자세한 옵션은 [전사](docs/transcription.md)에 있다.

### 단계별 명령

| 명령 | 하는 일 |
| --- | --- |
| `init` | 강의 폴더 생성 |
| `inspect` | 입력 자료 목록과 해시 기록 |
| `transcribe` | 음성·영상을 타임스탬프 TXT로 |
| `prepare` | PDF 렌더링, 영상 슬라이드 캡처, 남은 작업 기록 |
| `capture`, `extract-pdf`, `contact-sheet` | prepare의 개별 단계와 검토용 썸네일 |
| `apply` | 교정본과 대응표로 합본 생성 (해시 검증) |
| `verify` | 링크·이미지·본문 보존 검사 |

처리 순서는 [workflow.md](docs/workflow.md), 이미지 대응 기준은 [matching.md](docs/matching.md)에 있다.

## 설계 원칙

- 기계가 할 일과 의미 판단을 분리한다. 스크립트는 교정했다고 가장하지 않고, 남은 작업을 기록으로 남긴다.
- 원본은 바꾸지 않고, 완성본은 교정본 해시와 묶여 검증된다. 교정본이 바뀌면 대응표를 다시 검토해야 한다.
- 캐시는 입력 해시로 구분한다. 같은 입력이면 재실행해도 다시 계산하지 않는다.

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

가져온 코드와 라이선스는 [THIRD_PARTY.md](THIRD_PARTY.md)에 있다.
