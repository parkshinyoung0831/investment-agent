"""테스트 모듈의 최상위 namespace.

`unittest discover -s tests -t .`가 `tests/investment_agent`를 배포 패키지로 오인하지 않게
테스트를 `tests.*` 아래에서 발견한다.
"""

import os as _os
import tempfile as _tempfile

# 운영 컴퓨터에서 테스트를 돌려도 실제 로컬 사본(data/local/mirror)을 읽지 않게 한다. 사본을 읽으면 Supabase
# 조회를 흉내 낸 테스트가 가짜 대신 실데이터를 받아 환경에 따라 결과가 달라진다. 사본 테스트는 경로를 직접 준다.
_os.environ["AI_INVESTOR_LOCAL_MIRROR_ROOT"] = _os.path.join(_tempfile.gettempdir(), "investment-agent-tests-no-mirror")
