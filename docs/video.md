# 영상 처리와 VideoCap 호환

`pipeline/videocap/capture_engine.py`는 VideoCap의 추출 엔진을 가져온 것이다. Windows 샌드박스의 경로 조회 호환성을 위해 두 곳의 strict 경로 해석만 조정했다. 파일 존재와 영상 디코딩 검사는 유지하며 검출·시각·내보내기 형식은 동일하다. 버전과 원본/이식본 SHA-256은 provenance.json에 기록했다. GUI, 대기열 UI, 모델 비교, Qwen/llama 런타임은 가져오지 않았다.

- MP4를 input에 넣고 capture 또는 prepare를 실행한다. 대표 선택은 현재 VideoCap과 같은 인접 후보 dHash 비교, 기본 차이 8비트 이하 묶음, 묶음별 마지막 후보 방식이다.
- 대표 PNG와 native manifest를 기본 입력으로 검토한다. 대표만 있어도 작업할 수 있으며 전체 후보를 필수로 요구하지 않는다.
- PNG 수는 영상에 따라 달라진다. 100장 이상을 보장하거나 숫자를 맞추기 위해 화면을 추가하지 않는다.
- 후보는 work/capture에 보존한다. 대표 이미지에서 중요한 필기가 빠진 것으로 판단될 때만 후보를 역추적한다. 입력이 같고 파일 해시가 정상인 완료 추출은 재사용한다.
- VideoCap이 생성한 PNG+manifest를 이미 받았다면 input/screenshots 같은 폴더에 그대로 두고 사용한다. 이름이 길거나 바뀌었을 수 있으므로 manifest와 실제 파일을 대조한다.
- `.incomplete`가 있는 내보내기는 완료 결과로 사용하지 않는다. MP4 원본·크기·시각·프레임 순번·해시를 추적하며 임의의 시각을 만들지 않는다.
- dHash는 의미 판정이 아니다. 대표 선택이 필기 보존을 보장하지 않으므로 최종 내용 검토는 matching.md를 따른다.
- ffprobe는 선택 경로이며 `--ffprobe`로 지정할 수 있다. 없으면 원래 엔진의 OpenCV 메타데이터 경로를 사용한다.
