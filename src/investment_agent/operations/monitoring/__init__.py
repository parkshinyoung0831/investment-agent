"""예정된 것이 실제로 돌았고 실제로 도착했는지 본다.

여기 있는 것은 파이프라인을 돌리지 않는다 — 돈 결과를 읽고 사람에게 말한다.
cron이 발화했는지(`cron`), Actions가 성공했는지(`github_actions`), 카드가 채널에
닿았는지(`discord`), 조용한 채널이 있는지(`channels`·`counters`), 그리고 그것을
한 장으로 접는 것(`digest`·`incidents`).
"""
from __future__ import annotations
