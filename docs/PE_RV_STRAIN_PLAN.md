# PE RV/LV Strain 결정지원 시스템 — 개발 체크리스트

폐색전증(PE) 환자의 우심실(RV) strain 진단 보조를 위해, **ODV-Annotate**(OpenDicomViewer 포크, 로컬 MLX 사이드카 탑재)에
**TotalSegmentator 세그멘테이션**을 **플러그인 스토어** 방식으로 통합한다.

- **플랫폼**: Apple Silicon Mac, 온디바이스, 무클라우드
- **임상 목표**: CT에서 RV/LV ratio 자동 측정 → 룰 기반 분류 → 가이드라인 권고
- **유저 스터디**: 레지던트 1~3년차 각 ~10명, 모호 케이스(C-D) 30개, 지표 = 작업시간·확신도·스트레스·정확도

> 관련 설계 논의 요약은 이 문서 하단 [부록 A](#부록-a-핵심-설계-결정) 참고.

---

## Phase 0 — 베이스 병합 (SEG 렌더링 확보) ✅ 완료

포크는 오래된 upstream에서 분기되어 `DICOMDerivedObject`/`DICOMAnnotationObject`(binary SEG 렌더링) 등
이후 커밋이 빠져 있음. 최신 upstream 위에 AI 레이어를 재이식한다.
→ 실제로는 공통 조상(`461336a`) 기반 **3-way git 머지**로 두 히스토리를 보존하며 병합했다.

### 0.1 준비
- [x] 최신 upstream(`jnheo-md/open-dicom-viewer`)을 베이스로 새 레포 `ODV-PE` 생성
- [x] ODV-Annotate 전체 히스토리 클론, fork 분기점(`461336a`) 확인
- [x] 병합 전 upstream 기준선 확인

### 0.2 AI 레이어 이식 (머지로 자동 반영)
- [x] `AIService.swift` / `AIServerManager.swift` (신규 파일, 클린 머지)
- [x] `mlx-server/` 전체 (신규, 클린 머지)
- [x] `scripts/package_app.sh` — 번들 Python 3.11 + notarize (버전 2.0.0/build1로 통합)
- [x] `scripts/OpenDicomViewer.entitlements` — sandbox off, unsigned-exec, disable-library-validation, network client

### 0.3 공유 파일 충돌 해소 (5개 파일)
- [x] `PanelState.swift` — Cine/멀티프레임 상태 + AI 상태 둘 다 유지
- [x] `DICOMModel.swift` — Cine 메서드 + AI 분석 메서드 둘 다 유지
- [x] `ContentView.swift` — upstream 키 라우팅 채택 + 인스펙터를 `activeInspector` switch로 병합(`.tags`에 파생객체 로직 통합)
- [x] `MultiPanelContainer.swift` — `ImportedDICOMOverlay`(SEG) + `AIInspectorView` 둘 다 유지
- [x] `App.swift` — AI 메뉴 + `checkExistingServer()` (클린 머지)
- [x] "g" 단축키(AI 인스펙터 토글)를 3개 keyDown 핸들러에 배선 (`DICOMModel.toggleAIInspector()` 헬퍼)

### 0.4 검증 (Phase 0 완료 기준)
- [x] `swift build` 성공
- [x] `swift test` 통과 (67 XCTest + 21 swift-testing; `ActiveTool` 카운트 9→10 수정)
- [x] SEG 렌더러 자동 검증: 실제 binary SEG 픽스처(`highdicom_SEG/seg_image_ct_binary.dcm`) 파싱 → 16×16 마스크·127픽셀 → `ImportedDICOMOverlay`의 `.mask` 렌더 케이스까지 경로 확인 (`testPublicHighdicomSEGFixtureParsesBinaryMasks`)
- [x] 기존 Gemma AI 분석(bbox) 컴파일/경로 유지
- [x] `main` 브랜치로 병합·푸시 (`lemonardo1/ODV-PE`)
- [ ] ⚠️ 최종 픽셀 육안 확인은 GUI 실행 필요(사용자가 실제 SEG를 열어 확인) — 자동 검증 범위 밖

---

## Phase 1 — Segmentation 엔진 (one-shot)

상주 서버 아님. Swift가 파이썬 스크립트를 one-shot으로 스폰 (기존 `runSetupProcess` 패턴 재사용).
→ Gemma 상주 + seg 동시 상주로 인한 16GB RAM 초과 회피.

### 1.1 파이썬 환경 스캐폴딩 `seg-engine/` ✅
- [x] `seg-engine/requirements.txt` (torch, TotalSegmentator, nibabel, SimpleITK, pydicom, highdicom, numpy)
- [x] `seg-engine/download_task.py` — 태스크별 가중치 다운로드, `--list`, 진행률 stdout
- [x] `seg-engine/run_segment.py` — 핵심 실행기 (아래 사양)
- [x] `seg-engine/rvlv.py` — 순수 NumPy 계산 모듈 (heavy dep 분리 → 단위 테스트 가능)
- [x] `seg-engine/tests/test_rvlv.py` — NumPy-only 테스트 **8/8 통과**

### 1.2 `run_segment.py` 사양 ✅ (코드 완료)
- [x] 입력 인자: `--series` `--task` `--out` `--method length|volume` `--threshold` `--no-seg` `--fast`
- [x] (1) TotalSegmentator 실행 → NIfTI 마스크 (heavy dep은 지연 import)
- [x] (2) RV/LV ratio 계산 — length(축상 PCA 최소축 직경비, 기본) / volume(voxel 볼륨비)
- [x] (3) 룰 분류 + 가이드라인 권고문 (threshold 설정 가능, 기본 ≥ 1.0)
- [x] (4) binary DICOM SEG 내보내기 (highdicom, 소스 SOP 참조; RV=seg1, LV=seg2)
- [x] 출력 `<out>/metrics.json` (+ `segmentation.dcm`), 경로 기반 전송, graceful error → metrics.json `error` 필드
- [x] CLI 스모크: `--help`/`--list`/잘못된 경로 처리 확인 (heavy dep 없이)

### 1.3 검증 (Phase 1.5로 이관 — 사용자 환경 필요)
> `rvlv.py` 핵심 로직은 검증됨. 전체 파이프라인 실행은 torch+TotalSegmentator(~3GB) 설치 + CT 데이터가 필요해 이 세션에서 불가.
- [ ] (사용자 환경) `pip install -r seg-engine/requirements.txt` + `download_task.py --task heartchambers_highres`
- [ ] (사용자 환경) CLI로 케이스 1개 실행 → `segmentation.dcm` + `metrics.json` 산출
- [ ] (사용자 환경) SEG 파일을 뷰어에 로드 → RV/LV 마스크 오버레이 육안 확인
- [ ] length vs volume 결과 비교 (수 케이스)

---

## Phase 1.5 — ⚠️ 정확도 검증 (최우선 리스크)

> 나머지 통합 배관은 대부분 재사용이라, 진짜 불확실성은 "모델이 CTPA에서 RV/LV를 제대로 잡는가"에 있음.

- [ ] 공개 PE/CTPA 데이터셋에서 5~10 케이스 선별
- [ ] `heartchambers_highres`로 세그멘테이션 실행
- [ ] **조영기 불일치 영향 평가**: CTPA(폐동맥기)는 우심계 조영 강하고 좌심계 옅음 → 챔버 분할 오류 여부 육안 검수
- [ ] RV/LV 자동값 vs 수동 측정 비교 (상관/오차)
- [ ] **결정 게이트**: 정확도 부족 시 → (a) 전처리/윈도잉 보정, (b) 다른 태스크/모델, (c) 반자동(사용자 보정) 검토
- [ ] 결과를 문서화 (스터디 방법론 근거)

---

## Phase 2 — 플러그인 스토어

`AIServerManager`를 다중 엔진으로 일반화하고, 매니페스트 기반 설치 UI를 사이드바에 추가.

### 2.1 매니페스트
- [ ] `Resources/plugins.json` 작성 (엔진 → 태스크 트리; 로컬 고정, 원격 코드 실행 없음)
- [ ] 각 태스크 메타: `id, name, size_gb, ram_gb, output(bbox|seg), license, downloader/weights`
- [ ] 최소 등록 태스크: `gemma-4-e4b`(기존), `heartchambers_highres`(신규 우선)

### 2.2 `EngineManager` (기존 `AIServerManager` 일반화)
- [ ] 엔진 dict 구조로 리팩터 (엔진별 port / venv / setupState)
- [ ] 서버형 엔진(MLX): 기존 상주 로직 유지
- [ ] one-shot 엔진(seg): 스폰 → 대기 → 종료 실행기 추가
- [ ] venv를 **엔진별로 분리** (mlx venv / seg venv) — torch·mlx 의존성 충돌 방지
- [ ] 프로세스/로그/pip 설치 코드는 기존 것 재사용

### 2.3 설치 플로우
- [ ] 엔진 venv 없으면 → 생성 + `pip install -r requirements.txt` (진행률 스트리밍, 기존 `setupLog` UI 재사용)
- [ ] 태스크 선택 → `download_task.py` one-shot → 가중치 다운로드 (진행률)
- [ ] 설치 상태를 App Support의 JSON에 영속 (`notInstalled/downloading/installing/ready/failed` + 디스크 사용량)
- [ ] 태스크 삭제(가중치 제거) 지원

### 2.4 스토어 UI `PluginStoreView`
- [ ] 신규 `PluginStore` (ObservableObject) — 매니페스트 로드, 태스크별 상태
- [ ] 신규 `PluginStoreView` — 사이드바 섹션 or AI 메뉴에서 여는 시트
- [ ] 엔진 → 태스크 리스트, 각 행: 크기/RAM/상태 + Install/Remove + 진행률 바
- [ ] 라이선스 배지 (Gemma=Apache-2.0, TotalSeg=연구용)
- [ ] "가중치만 다운로드, 환자 데이터 전송 없음" 안내 문구

### 2.5 검증
- [ ] 신규 설치 상태에서 스토어로 `heartchambers` 태스크 설치 완주
- [ ] 설치 후 상태 영속 확인 (앱 재시작 후 `ready` 유지)

---

## Phase 3 — 임상 표시 (SEG 오버레이 + RV/LV 패널)

### 3.1 Swift 연결
- [ ] 신규 `SegmentationService` — `run_segment.py` 스폰, `metrics.json` 파싱, SEG를 스터디 폴더에 배치
- [ ] `DICOMModel`에 `triggerSegmentation(series:task:)` 추가
- [ ] seg 실행 전 MLX 서버 일시 정지 옵션 (RAM 안전) — `EngineManager`에 훅

### 3.2 결과 UI
- [ ] SEG 오버레이 표시 (병합해온 `DICOMAnnotationObject` 렌더러 활용)
- [ ] 신규 `RVStrainPanel` — RV/LV 비율, 분류, 가이드라인 권고문, **면책 문구**("research/educational only, NOT clinical diagnosis")
- [ ] threshold 설정 UI (기본 1.0, 근거 문헌 표기)
- [ ] length 측정 시각화 (축상 슬라이스의 RV/LV 직경선)

### 3.3 검증
- [ ] 30 케이스 중 표본으로 오버레이 + 패널 end-to-end 확인
- [ ] 잘못된 세그멘테이션 케이스에서 graceful 처리 (에러/경고)

---

## Phase 4 — 유저 스터디 패키징

### 4.1 데이터 파이프라인
- [ ] 공개 데이터셋에서 30 케이스 선별 (C-D 모호 케이스, 교수 3명 중 2명 이상 동의)
- [ ] **오프라인 사전계산**: 30 케이스 seg 결과를 미리 생성 → 라이브 추론 지연이 "작업시간" 지표를 오염시키지 않도록
- [ ] 케이스별 정답/레퍼런스 라벨 준비

### 4.2 평가 하네스
- [ ] 작업 완료 시간 로깅
- [ ] 확신도(confidence) 입력 UI
- [ ] 스트레스 레벨 입력 UI
- [ ] 의사결정 정확도 기록
- [ ] 로그를 로컬 파일로 익스포트 (익명화)

### 4.3 배포
- [ ] `package_app.sh --notarize`로 notarized DMG 빌드
- [ ] 파일럿 1명으로 전체 플로우 리허설
- [ ] 스터디 프로토콜 문서화

---

## 상시 주의 / 결정 항목

- [ ] **RAM**: Gemma 상주 + seg 실행 동시 겹침 최소화 (one-shot + 실행 전 서버 pause 옵션)
- [ ] **라이선스**: TotalSegmentator 가중치 = 비상업/연구용. 상용화 시 재라이선싱 필요. UI에 배지 표기
- [ ] **네트워크**: 가중치 다운로드만 egress (환자 데이터 아님). 문구로 명시
- [ ] **규제 포지션**: "decision support", "NOT diagnosis" 유지. 매니페스트는 로컬 고정(원격 코드 실행 금지)
- [ ] **스터디 우선**: 스토어를 과도하게 만들다 과학 일정 늦추지 말 것. 태스크 1개(heartchambers)로 출시 가능
- [ ] **RV/LV 방식**: length(가이드라인 표준, 기본) vs volume(정확). Phase 1에서 비교 후 확정

---

## 부록 A: 핵심 설계 결정

| 결정 | 선택 | 이유 |
|---|---|---|
| 추론 위치 | 온디바이스 사이드카 | 무클라우드·프라이버시, 상용 API 미사용 |
| seg 실행 방식 | **one-shot 서브프로세스** (상주 서버 아님) | 스터디당 1회 실행, 이중 모델 RAM 초과 회피 |
| 데이터 전송 | 폴더 **경로** 기반 (base64 아님) | 3D+HU 확보, 환자 데이터 머신 밖 유출 없음 |
| venv 분리 | 엔진별 (mlx / seg) | torch·mlx 의존성 충돌 방지 |
| RV/LV 계산 위치 | 파이썬 (`run_segment.py`) | 마스크+spacing이 여기 있음 |
| RV/LV 방식 | length(축상 직경비) 기본 | PE 가이드라인 표준(≥1.0), 가볍고 방어적 |
| 결과 렌더링 | upstream binary DICOM SEG 렌더러 | Phase 0 병합으로 확보, 신규 렌더 코드 불필요 |
| 자동 세그 모델 | TotalSegmentator `heartchambers_highres` | 4챔버 자동 분할. SAM2/3는 프롬프트 기반이라 부적합 |
| 스터디 추론 | 오프라인 사전계산 | 추론 지연이 작업시간 지표 오염 방지 |

## 부록 B: 파일 변경 요약

**신규 파일**
- `seg-engine/{requirements.txt, download_task.py, run_segment.py}`
- `Resources/plugins.json`
- `Sources/OpenDicomViewer/{PluginStore.swift, PluginStoreView.swift, SegmentationService.swift, RVStrainPanel.swift}`

**수정 파일**
- `AIServerManager.swift` → `EngineManager`로 일반화
- `DICOMModel.swift` — `triggerSegmentation`
- `ContentView.swift` — 스토어 사이드바 진입점
- `App.swift` — 메뉴 항목
