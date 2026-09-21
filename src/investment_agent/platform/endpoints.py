"""외부 provider의 기준 주소를 한 곳에 둔다.

같은 주소를 모듈마다 다시 적으면 provider가 API 버전을 올릴 때(Discord v10 → 다음 버전) 일부만 고쳐져, 어떤
경로는 옛 버전으로 계속 도는 것이 에러 없이 지나간다. 각 provider 모듈은 여기서 가져와 자기 이름(`_BASE` 등)에
받아 쓴다 — 모듈 안의 이름은 테스트가 바꿔 끼울 수 있게 그대로 남는다.
"""
from __future__ import annotations

TOSS_OPENAPI_BASE = "https://openapi.tossinvest.com"
DISCORD_API_BASE = "https://discord.com/api/v10"
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
ECOS_STATISTIC_SEARCH_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
SEC_DATA_BASE = "https://data.sec.gov"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives"
