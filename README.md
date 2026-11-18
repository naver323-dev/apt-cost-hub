# 아파트 관리비 인사이트 (apt-cost-hub)

전국 아파트의 **관리비(㎡당)** 와 **아파트 매매 실거래(건수·중간가·평당가)** 를 시군구·단지 단위로
집계해 정적 사이트로 배포합니다. 서버·DB·유료 API 없이 파이썬 표준 라이브러리만 씁니다.

- 사이트: https://apt-cost-hub.pages.dev
- 저장소: https://github.com/naver323-dev/apt-cost-hub
- 데이터: 매일 05:30 KST GitHub Actions가 재생성 (`deploy` 브랜치로 배포)

## 자동 갱신 (매일 05:30 KST)

`.github/workflows/daily.yml` — 매일 05:30 KST(UTC 20:30)에 원자료를 다시 받아 사이트를 재생성하고 `deploy` 브랜치로 배포한다.

- K-apt 파일은 한국 밖 러너에서 접속이 막히는 경우가 있다. 이때는 커밋된 `data/committed/kapt_cache.json.gz`(마지막 정상 빌드)로 사이트를 유지하고, 사이트에 "수집 지연" 안내를 띄운다.
- 실거래 CSV는 `actions/cache`에 남기고 최근 2개월만 새로 받는다. 받지 못하면 `data/committed/trade_cache.json`을 쓴다.
- 어느 쪽이 실패해도 사이트는 이전 스냅샷으로 계속 서비스된다(빈 화면·오류 페이지 없음).

## 원자료

| 데이터 | 출처 | 갱신 |
|---|---|---|
| 단지 관리비·면적 | K-apt 공동주택관리정보시스템 자료실 (관리비공개의무단지 관리비정보·면적정보) | 주 1회 |
| 아파트 매매 실거래 | 국토교통부 실거래가공개시스템 자료제공 CSV (계약일 기준) | 월 1회 |

공공데이터포털 등록본: 국토교통부_공동주택 단지 관리비 정보(3039714), 국토교통부_공동주택 단지 면적 정보(15073269).
이용허락범위 제한 없음(출처 표시).

## 산식

- ㎡당 공용관리비 = 공용관리비 합계 ÷ 관리비부과면적
- 지역 값 = Σ공용관리비 ÷ Σ관리비부과면적 (면적 가중)
- 세대당 총관리비 = (공용관리비 + 개별사용료 + 장기수선충당금 월부과액) ÷ 세대수
- 평당가 = 거래금액 ÷ 전용면적 × 3.305785 (거래별 값의 중간값)
- 해제된 거래(해제사유발생일 존재)는 제외
- 관리비부과면적÷세대수가 10㎡ 미만·400㎡ 초과인 단지는 원자료 면적 오류로 보고 ㎡당 지표에서 제외

## 실행

```bash
python3 scripts/fetch_kapt.py     # K-apt 주간 파일 (세션 필요 → 스크립트가 처리)
python3 scripts/fetch_molit.py    # 실거래 CSV (기본 4개월, --months N) · 실패 시 기존 파일/캐시 유지
python3 scripts/build_data.py     # data/processed/dataset.json
python3 -m unittest discover -s tests -v
python3 scripts/build_site.py     # site/
python3 scripts/check_site.py     # 2,800+ 검사, 실패 시 exit 1
```

## GEO / 검색

- `/llms.txt`, `/api/regions.json`, `/api/regions/{slug}.json`, `/api/meta.json`
- 페이지마다 정적 표(JS 없이 보임), `Dataset`·`FAQPage`·`BreadcrumbList` JSON-LD
- `/robots.txt`에서 AI 크롤러 허용, `/sitemap.xml` 전체 URL
- GA4 `G-J80R3CFWY8`
