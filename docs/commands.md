# 도구 사용과 검증

프로젝트 루트에서 프로젝트의 Python(가상환경이 있으면 그 인터프리터)을 사용한다. 공통 진입점은 `pipeline/lecture.py`이며 강의 이름을 인수로 받는다.

```powershell
python pipeline/lecture.py init "algorithms-7W-1"
python pipeline/lecture.py inspect "algorithms-7W-1" --output
python pipeline/lecture.py transcribe "algorithms-7W-1" --media "input/강의.mp3" --provider whisper --language ko
python pipeline/lecture.py prepare "algorithms-7W-1"
python pipeline/lecture.py capture "vision-7W-1" --video "input/강의.mp4"
python pipeline/lecture.py extract-pdf "algorithms-7W-1" --pdf "input/교안.pdf"
python pipeline/lecture.py contact-sheet "algorithms-7W-1" --source work/pdf-pages
python pipeline/lecture.py apply "algorithms-7W-1"
python pipeline/lecture.py verify "algorithms-7W-1"
```

위의 강의명과 파일명은 예시다. 실제 요청의 이름과 `inspect` 결과를 사용한다. PDF 도구는 `--renderer`, 환경 변수 `LECTURE_PDFTOPPM`, PATH의 `pdftoppm` 순으로 찾는다. 전사 옵션은 [전사](transcription.md)에 있다. capture의 `--threshold` 기본은 8이다. `--ffprobe`를 지정하지 않아도 OpenCV 경로로 실행할 수 있다.

`prepare`는 기계적 준비만 수행한다. 녹취록을 교정한 척하거나 본문 대응을 자동 추정하지 않고 남은 의미 작업을 기록한다. 기존 work/transcript.md가 새 입력과 맞는지 에이전트가 확인한다. 새 입력으로 바뀐 경우 예전 교정본·대응표를 그대로 출판하지 않는다.

## work/mapping.json

```json
{
  "version": 2,
  "lecture": "algorithms-7W-1",
  "pdf_coverage": [
    {"pdf": "input/교안.pdf", "mode": "all"}
  ],
  "documents": [
    {
      "markdown": "work/transcript.md",
      "output": "output/algorithms-7W-1.md",
      "expected_sha256": "inspect에서 확인한 후처리 Markdown의 SHA-256",
      "sections": [
        {
          "section": 1,
          "heading": "## 원문 H2 제목",
          "images": [
            {
              "source": "work/pdf-pages/실제-추출파일-p001.png",
              "alt": "이미지의 내용",
              "reason": "본문의 도표·수식·예제와 맞는 이유"
            },
            {
              "source": "input/screenshots/원본.png",
              "name": "lecture-notes-s013.png",
              "alt": "중요한 확대 필기",
              "reason": "전체 화면을 보완하는 별도 정보"
            }
          ]
        }
      ]
    }
  ]
}
```

- 경로는 해당 강의 폴더 기준이며 폴더 밖으로 나갈 수 없다. 출판할 Markdown은 work에 있고 결과는 output 바로 아래에 둔다.
- H2 순번은 1부터 센다. 코드 블록 안의 가짜 제목은 세지 않으며, 실제 제목 원문도 함께 확인한다. 타임스탬프 유무에 관계없이 같은 형식을 쓴다.
- `source`는 실제 원본/추출 이미지 경로다. 긴 이름·한글 이름의 캡처는 `name`으로 짧은 ASCII 출력 이름을 지정한다. PDF 이미지는 추출 결과의 경로를 그대로 사용할 수 있다.
- `pdf_coverage`에는 모든 제공 PDF를 기록한다. selected는 영상 참고 교안, 사용자 지정 일부 사용, 공유 강의 분할 등의 명확한 이유를 함께 적는다. PDF만 제공되었다면 기본은 all이다.
- 이미지 수를 강제하지 않는다. 정보가 보완되면 한 H2에 여러 장을 넣고, 같은 파일을 여러 절에서 재사용할 수 있다.
- 본문에서 해당 이미지의 설명이 시작되거나 테마가 전환되는 위치를 판단해 이미지 항목에 `before_paragraph`를 추가한다. 새 작업에서도 이 배치를 기본으로 검토한다. 값은 해당 H2 안에서 한 번만 나오는 대상 문단의 원문 전체이며 그림은 그 문단 직전에 들어간다. 절 처음부터 대응하는 대표 화면만 이 필드를 생략해 H2 아래에 둔다. 절의 마지막 문단 뒤에 와야 하는 마무리·참고 교안 페이지는 `before_paragraph` 대신 `after_paragraph`에 그 문단 원문 전체를 적는다. 본문 해시가 바뀌면 재검토한다.
- 본문 중간 이미지도 관리 구간으로 추적하며, verify는 대응표에 기록된 본문 위치와 그림 순서까지 검사한다. 재배치만 요청받으면 이미지 링크의 중복 수까지 포함한 전체 목록과 파일 해시가 작업 전후 동일한지 추가로 비교한다.

## 출판과 재작업

apply는 후처리본을 수정하지 않고 새 합본을 만든다. SHA-256, H2, 모든 이미지, 파일명 충돌과 PDF coverage를 사전 검사한다. 기존 output이 사용자에 의해 수정되었거나 관리 상태가 없으면 덮어쓰지 않는다. 같은 대응표는 재검증 후 중복 없이 재사용하고 새 대응표는 관리 이미지 구간을 다시 구성한다.

작업 중 다른 단계가 실패하면 기존 output을 검증 완료로 보고하지 않는다. 이미지 파일 복사가 먼저 수행될 수 있으나 기존 문서 교체는 마지막 단계다. 내부 백업은 work/backups에 있으며 별도 history 구조를 만들지 않는다. 사용하지 않는 이전 캐시 이미지를 자동으로 삭제하지 않는다.

verify는 이미지 링크와 실제 파일, 원본 이미지와 복사본 해시, 후처리본의 본문 바이트, H2 배치, 입력 변경과 PDF 누락을 검사한다. 고유 이미지 수와 재사용 링크 수를 구분한다. 코드·필기 가독성과 의미 대응은 별도로 화면을 확인한다.

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

테스트는 임시 강의와 합성 MP4를 사용하며 실제 강의에는 테스트 데이터를 넣지 않는다. 기존 자료는 migration 상태로 가져왔으며 첫 재출판 시 새 관리 구간 형식으로 자연스럽게 전환된다.
