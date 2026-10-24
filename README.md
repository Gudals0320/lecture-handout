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

## 흐름

1. `python pipeline/lecture.py init "<강의명>"` 후 `input/`에 자료를 넣는다.
2. 녹음만 있으면 전사한다. 외부 앱에서 내보낸 TXT, 로컬 faster-whisper, Soniox API 중 고른다. [전사](docs/transcription.md)
3. `prepare`가 PDF 페이지와 영상 슬라이드를 렌더링하고, 남은 의미 작업을 `work/prepare.json`에 적는다.
4. 에이전트가 `prompts/`의 교정 프롬프트로 전사를 교정하고, 이미지와 본문 문단을 대응시켜 `work/mapping.json`을 쓴다.
5. `apply`가 해시를 검증하며 합본을 만들고 `verify`가 결과를 점검한다.

에이전트에게 "강의 <강의명> 작업해줘"라고 요청하면 `AGENTS.md`가 이 순서를 안내한다. 명령 전체는 [도구 사용](docs/commands.md), 순서는 [처리 순서](docs/workflow.md)에 있다.

## 설계 원칙

- 기계가 할 일과 의미 판단을 분리한다. 스크립트는 교정했다고 가장하지 않고, 남은 작업을 기록으로 남긴다.
- 원본은 바꾸지 않고, 완성본은 교정본 해시와 묶여 검증된다. 교정본이 바뀌면 대응표를 다시 검토해야 한다.
- 캐시는 입력 해시로 구분한다. 같은 입력이면 재실행해도 다시 계산하지 않는다.

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

가져온 코드와 라이선스는 [THIRD_PARTY.md](THIRD_PARTY.md)에 있다.
