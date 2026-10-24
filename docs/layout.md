# 구조와 입력

강의 폴더 이름이 결과 Markdown 이름이 된다. `<과목>-<주>W-<차>` 형식을 권장한다(예: `algorithms-7W-1`, `vision-6W-2`). 사용자가 다른 규칙을 쓰면 그 규칙을 따르고, 요청이 짧은 이름으로 와도 기존 폴더에 대응한다. 차수가 불명확하면 확인 가능한 정보만 사용하고, 비슷한 강의가 여럿이면 내용을 먼저 확인한다.

- `input/`: 원본 PDF, 영상, raw-transcript TXT, 제공된 Markdown, 원본 캡처 PNG/manifest. 원본을 변경하지 않는다.
- `work/transcript.md`: 교정·구조화된 본문. 이미 후처리된 Markdown이라면 내용과 인코딩을 그대로 사용한다.
- `work/pdf-pages/`, `work/capture/`: PDF 렌더링과 VideoCap의 후보·대표 PNG·manifest. 캐시는 입력 해시로 구분하며 실행 번호를 만들지 않는다.
- `work/previews/`, `work/mapping.json`, `work/state.json`, `work/validation.json`: 검토와 재실행에 필요한 관리 자료.
- `output/<강의명>.md`, `output/images/`: 검증된 완성본. 이미지 링크는 `./images/...`이며 output 전체를 다른 곳으로 복사해도 열린다.

같은 교안이 여러 강의에 걸치면 각 강의의 input에 사본을 두고 본문에 해당하는 부분을 사용한다. 공유 사실과 선택 이유는 대응표에 기록한다. 전체 페이지 사용이 요구된 공유 교안의 전역 누락 여부도 확인한다.

자료를 새로 받으면 기존 input을 덮어쓰지 말고 충돌을 확인한다. work의 캐시는 새 입력과 같을 때만 재사용한다. 기존 결과가 수정되었으면 사용자의 수정을 먼저 보존한다.
