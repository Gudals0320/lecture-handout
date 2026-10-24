# 처리 순서

1. 요청된 강의 이름을 확정하고 input을 조사한다. PDF·MP4·TXT·Markdown·캡처 PNG와 manifest의 실제 파일을 확인한다.
2. `init`로 강의 폴더를 만들거나 기존 폴더를 사용한다. 첨부된 원본을 input에 넣는다. `inspect --output`으로 조사 기록을 저장한다.
3. 전사 TXT가 없고 녹음·영상만 있으면 `transcription.md`를 읽고 사용자가 고른 경로(외부 TXT, 로컬 whisper, Soniox)로 `transcribe`를 실행한다. TXT/raw-transcript가 있으면 `refinement.md`를 읽고 프롬프트에 따라 `work/transcript.md`를 작성한다. 이미 후처리된 Markdown이면 재교정하지 않는다. 타임스탬프 유무에 따라 시간을 생성하지 않는다.
4. PDF는 `pdf.md`, MP4/PNG는 `video.md`에 따라 준비한다. `prepare`는 렌더링과 캡처를 묶어서 실행하며 필요한 의미 작업을 `work/prepare.json`에 남긴다. 영상이 없으면 현장강의 경로로 진행한다.
5. `matching.md`를 읽고 본문·교안·화면 흐름을 대조한다. Contact sheet로 전체를 본 뒤 중요한 후보는 원본 해상도에서 확인한다. H2를 대응 범위로 삼고, 각 이미지가 설명되는 본문 문단·테마 전환 위치를 정해 분산 배치한다.
6. `commands.md` 형식으로 `work/mapping.json`을 작성하고 `apply`한다. 모든 출력 문서를 함께 기록해 재작업에서 기존 결과가 빠지지 않게 한다.
7. `verify` 후 본문, 링크, PDF 범위와 이미지의 주석·코드 가독성을 확인한다. 결과 경로와 수량, 필요한 제한만 보고한다.

처리 도중 실패하면 기존 output을 완성본으로 교체하지 않는다. 실제 파일과 상태를 확인해 필요한 단계만 재실행한다. 폴더 이름이나 이전 강의의 페이지 대응표를 새 자료에 적용하지 않는다.
