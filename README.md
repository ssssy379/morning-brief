# 아침 신문 브리핑

매일 오전 8:30(한국시간)에 **뉴욕타임즈 · 워싱턴포스트 · 한국경제**의 중요 기사 5개씩을 골라
한국어로 요약(영문 기사는 번역)하고 원문 링크를 달아 주는 모바일 웹앱입니다.
갤럭시 폰에서 홈 화면에 추가하면 앱처럼 쓸 수 있어요.

## 구성

| 파일 | 역할 |
|---|---|
| `scripts/fetch_news.py` | 신문사 RSS에서 오늘 기사를 모으고, Claude로 5개 선정·요약·번역 → `docs/data/*.json` 저장 |
| `.github/workflows/daily-brief.yml` | 매일 08:30 KST에 위 스크립트를 자동 실행 |
| `docs/` | 휴대폰에서 보는 화면 (PWA: 홈 화면 설치, 오프라인 보기 지원) |

## 설치 방법 (한 번만)

1. **Anthropic API 키 발급** — https://console.anthropic.com 에서 키를 만듭니다.
2. **GitHub 저장소 만들기** — 이 폴더 전체를 새 저장소에 올립니다.
3. **키 등록** — 저장소 → Settings → Secrets and variables → Actions → New repository secret
   - Name: `ANTHROPIC_API_KEY`, Value: 발급받은 키
4. **사이트 공개** — Settings → Pages → Source: *Deploy from a branch*, Branch: `main`, 폴더 `/docs` → Save
   - 잠시 후 `https://<아이디>.github.io/<저장소이름>/` 주소가 생깁니다.
5. **첫 실행 테스트** — Actions 탭 → "아침 신문 브리핑" → *Run workflow*
6. **갤럭시 홈 화면에 추가** — 삼성 인터넷이나 크롬으로 위 주소를 열고
   메뉴 → **"현재 페이지 추가" → "홈 화면"** (크롬은 "홈 화면에 추가"/"앱 설치")

## 알아두면 좋은 점

- **8:30 정각 보장 아님**: GitHub 예약 실행은 몰릴 때 몇 분~수십 분 늦어질 수 있어요.
  더 일찍 받아보고 싶으면 워크플로의 cron 시간을 앞당기세요 (예: `0 23 * * *` = 08:00).
- **요약 근거**: NYT·WP는 유료 기사라 본문을 가져오지 않고, RSS의 제목·리드 문장만으로 요약합니다.
  링크는 항상 실제 기사로 연결되도록 코드에서 검증해요.
- **워싱턴포스트 피드**: 공식 RSS가 불안정해서 실패하면 구글 뉴스 검색 피드로 대신 가져옵니다.
  이 경우 링크가 구글 뉴스를 거쳐 WP 기사로 이동하고, 리드 문장이 없어 요약이 짧아질 수 있어요.
- **비용**: 매일 Claude 호출 3번 (`claude-opus-5-5`, 신문당 1회). 거절 응답 시 자동으로 다른 모델이 이어받는
  fallback 옵션이 켜져 있어요.
- **로컬에서 실행**: `pip install -r requirements.txt` 후 `ANTHROPIC_API_KEY=... python scripts/fetch_news.py`,
  화면은 `python -m http.server -d docs` 후 http://localhost:8000
