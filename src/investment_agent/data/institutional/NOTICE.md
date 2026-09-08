# Third-party notice

이 파이프라인은 MIT 라이선스 프로젝트
[edgartools 5.36.0](https://github.com/dgunning/edgartools/tree/v5.36.0)를 두 방식으로 사용합니다.

1. **재구현(의존성 없음).** `value_units.py`의 13F 금액 단위 판별 방식은
   edgartools의 `edgar/thirteenf/models.py::_detect_value_in_thousands`를 참고해
   이 프로젝트의 `RawPosition` 모델에 맞게 의존성 없이 다시 구현했습니다.

2. **런타임 의존(shadow 파서).** `sources/edgartools_13f.py`는 edgartools를 직접
   import해 `edgar.thirteenf.parse_infotable_xml` / `parse_infotable_txt`로
   information table을 다시 파싱하고, 운영 직접 파서 결과와 사후 대조합니다
   (`GURUS_SHADOW_PARSER=on`일 때만 호출). 버전은 `pyproject.toml`의 `data`
   dependency-group에 `edgartools==5.36.0`으로 고정합니다.

Copyright (c) edgartools contributors. 원 프로젝트의 MIT 라이선스 조건을 따릅니다.
