# 가져온 코드와 라이선스

- `pipeline/videocap/capture_engine.py`는 로컬 VideoCap 프로젝트의 커밋 `09830fb9e4b1e18d81c74437e00a09ed5ee0fa98`에서 가져왔다. Windows 샌드박스 경로 조회를 위한 두 곳의 변경과 원본/이식본 SHA-256을 `pipeline/videocap/provenance.json`에 기록했다. 업데이트는 원본과 비교하고 호환 테스트를 수행한 뒤 반영한다.
- 프레임 차이 검출의 원출처는 binh234/video2slides의 MIT 코드다. 라이선스 원문은 `pipeline/videocap/LICENSE-video2slides.txt`에 보존했다. VideoCap은 취소, 시각, 첫/마지막 프레임, 무손실 PNG 보존을 추가한 변형이다.
- `pipeline/videocap/bridge.py`의 대표 선택은 VideoCap의 인접 dHash 묶음/마지막 후보 정책을 옮긴 연결 코드다. UI·Qwen·llama.cpp·모델 추론 기능은 포함하지 않는다.
- OpenCV, NumPy, Pillow, pypdf는 Python 의존성이다. 설치된 패키지의 라이선스는 각 패키지에 포함된다. 버전은 requirements.txt에 고정했다. 전사용 선택 의존성(faster-whisper, httpx)은 requirements-stt.txt에 있다.
- `prompts/audioscript-refiner-1.5.3.md`는 사용자가 지정한 원본 프롬프트의 사본이다. 기존 외부 파일은 수정하지 않았다.
