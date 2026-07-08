# 0708 — Phase 1 파이프라인 검증 실험 기록

- **날짜**: 2026-07-08
- **목표**: `seg-engine` RV/LV 파이프라인이 실제 DICOM CT에서 end-to-end로 도는지, 생성된 SEG를 ODV-PE 뷰어가 읽는지 검증
- **결과**: ✅ 전 과정 성공 (세그멘테이션 → RV/LV 계산 → binary DICOM SEG → 뷰어 파서 roundtrip)
- **환경**: Apple Silicon Mac, macOS, Python 3.14, venv `seg-engine/.venv`

---

## 1. 환경 셋업

| 항목 | 내용 |
|---|---|
| TotalSegmentator | 2.15.0 |
| PyTorch | 2.12.1 |
| 라이선스 | 무료 학술 라이선스 발급 → `totalseg_set_license` 등록 (`~/.totalsegmentator/config.json`) |
| 가중치 | `download_task.py --task heartchambers_highres` → Task 301 (230MB) 다운로드 |

라이선스 미등록 시 `KeyError: 'license_number'` 발생 → 무료 학술 라이선스 필수임을 확인.

## 2. 사용한 모델

| 모델 | 크기 | 역할 |
|---|---|---|
| `Dataset297_TotalSegmentator_total_3mm` (nnU-Net v2) | 158MB | 저해상 전신 — 심장 위치 크롭용 1차 패스 |
| `Dataset301_heart_highres` (Task 301, nnU-Net v2) | 237MB | 고해상 심장 4챔버 분할 (RV/LV 본 작업, 라이선스 게이트) |
| `rvlv.py` | — | **모델 아님**. 순수 NumPy 룰 기반 비율 계산·분류 |

> Gemma 4 E4B (MLX, `mlx-community/gemma-4-E4B-it-4bit`)는 병합 코드에 있으나 이번 실험 미사용.

## 3. 테스트 데이터

- **출처**: TCIA NSCLC-Radiomics, subject `LUNG1-001`
- **종류**: 조영 흉부 CT (RCCTPET_THORAX_CONTRAST), SIEMENS Biograph 40
- **규모**: 134 슬라이스, 512×512, 33MB
- **라이선스**: CC BY-NC 3.0 (연구/테스트용, 재배포·커밋 금지)
- **재현**: `seg-engine/tests/fetch_sample_ct.sh` (TCIA REST API, 로그인 불필요)
- ⚠️ PE 환자가 아니라 폐암 환자 CT — 파이프라인 mechanics 검증용. 임상 정확도(PE/CTPA)는 별도.

## 4. 실행 & 결과

```bash
python3 run_segment.py --series /tmp/ctpe_test/dicom --out /tmp/pe2   # 전체(SEG 포함)
```

**RV/LV 지표** (`metrics.json`):

| 필드 | 값 |
|---|---|
| rv_lv_ratio | **1.12** |
| method | length (축상 PCA 최소축 직경비) |
| rv_measure / lv_measure | 44.6mm / 39.8mm |
| reference_slice | 43 |
| classification | rv_strain_suggested (1.12 ≥ 1.0) |

> 폐암(비-PE) 케이스라 1.12는 정상 범주. threshold 1.0을 살짝 넘어 분류된 예상된 동작.

**생성 SEG** (`segmentation.dcm`, 1.6MB) — pydicom 검증:
- SOPClassUID = Segmentation Storage, SegmentationType = **BINARY**
- 512×512, 2 세그먼트 (1=RV cavity, 2=LV cavity)
- 48 프레임 (마스크 있는 슬라이스만; RV 30장 / LV 18장)
- 소스 시리즈 UID + 134 인스턴스 참조
- set 픽셀 72,831

**뷰어 파서 roundtrip** — ODV-PE `DICOMAnnotationObjectParser`로 생성 SEG 재파싱:
- segmentFrames 48개 ✓
- 라벨 "RV cavity" / "LV cavity" ✓
- set 픽셀 72,831 (pydicom과 **정확히 일치**) ✓
- 전 프레임 512×512 + 소스 SOP 참조 ✓
- (임시 Swift 테스트로 확인 후 삭제 — NC 데이터라 미커밋)

## 5. 성능 (실측)

- nnU-Net은 **MPS 미사용, CPU로 실행** ("No GPU detected. Running on CPU")
- 케이스당 **약 2–3분** (crop 모델 + highres 모델 포함)
- → **유저 스터디는 라이브 추론 대신 오프라인 사전계산** 권고 확증 (추론 지연이 "작업시간" 지표 오염 방지)

## 6. 검증된 것 / 남은 것

**검증됨** ✅
- `run_segment.py`의 마스크 파일명 가정(`heart_ventricle_right/left.nii.gz`) 정확
- NIfTI → [z,y,x] 방향 변환 정상
- highdicom binary SEG 내보내기 + 슬라이스 대응 정상
- 뷰어 렌더 경로(파싱→`.mask` 지오메트리) 실데이터로 확인

**남은 것 (Phase 1.5)** ⏳
- 실제 PE/CTPA 코호트(FUMPE, RSNA-STR-PE 등)로 **임상 정확도** 검증
- 조영기(폐동맥기) 챔버 분할 정확도 육안 검수
- 자동 RV/LV vs 수동 측정 비교
- 앱 GUI에서 오버레이 육안 확인 (`swift run OpenDicomViewer` → `/tmp/ctpe_test/dicom` 열기; SEG는 `RVLV_SEG.dcm`로 동봉)

## 7. 관련 커밋

- `93b3565` Phase 1 pipeline validated end-to-end on real chest CT
- `ed815a4` license 요구사항 문서화
- `a71cf74` download_task.py 콘솔 스크립트 방식으로 수정
- `2077d12` Phase 1: seg-engine 추가
