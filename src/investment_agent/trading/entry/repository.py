"""진입 계획의 단일 선점과 불변 재판단을 로컬 원장에 기록한다."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.platform.serialization import canonical_json, parse_datetime


class EntryRepository:
    def candidates(self):
        with runtime_connection() as connection:
            return [json.loads(row[0]) for row in connection.execute('SELECT payload_json FROM entry_candidates ORDER BY next_check_at,signal_id')]

    def save(self, row):
        with runtime_connection() as connection:
            if row.get('claim_token'):
                old=connection.execute('SELECT payload_json FROM entry_candidates WHERE signal_id=?',(row['signal_id'],)).fetchone()
                if old and json.loads(old[0]).get('claim_token') != row['claim_token']:
                    raise ValueError('entry claim superseded by another worker')
            connection.execute('INSERT INTO entry_candidates VALUES(?,?,?,?,?) ON CONFLICT(signal_id) DO UPDATE SET status=excluded.status,next_check_at=excluded.next_check_at,payload_json=excluded.payload_json',
                (row['signal_id'],row['ticker'],row['status'],row['next_check_at'],canonical_json(row)))

    def claim(self, row, *, now):
        with runtime_connection() as connection:
            old = connection.execute('SELECT next_check_at,status FROM entry_candidates WHERE signal_id=?',(row['signal_id'],)).fetchone()
            if old and (parse_datetime(old[0]) > now or old[1] in ('ready','cancelled','expired','consumed','superseded')):
                return False
            row['claim_token']=uuid.uuid4().hex
            row = {**row, 'next_check_at':(now+timedelta(minutes=10)).isoformat()}
            connection.execute('INSERT INTO entry_candidates VALUES(?,?,?,?,?) ON CONFLICT(signal_id) DO UPDATE SET next_check_at=excluded.next_check_at,payload_json=excluded.payload_json',
                (row['signal_id'],row['ticker'],row['status'],row['next_check_at'],canonical_json(row)))
        return True

    def save_review(self, row):
        with runtime_connection() as connection:
            connection.execute('INSERT OR IGNORE INTO entry_reviews VALUES(?,?,?,?)',
                (row['review_id'],row['signal_id'],row['reviewed_at'],canonical_json(row)))

    def ready(self, *, now):
        from investment_agent.execution.db import funding_followup_batch_ids
        with runtime_connection(read_only=True) as connection:
            claimed = {row[0] for row in connection.execute(
                "SELECT record_key FROM runtime_records WHERE record_type='signal_batch_execution'")}
        # 자금 확보 매도가 끝난 batch는 새 계좌로 한 번 더 구성할 수 있게 대기열에 되돌린다.
        claimed -= funding_followup_batch_ids()
        return [row for row in self.candidates() if row['status']=='ready'
                and row.get('batch_id') not in claimed
                and parse_datetime(row['review']['expires_at']) > now]

    def save_guard(self, batch_id, row):
        guard = dict(ticker=row['ticker'], plan=row['plan'], review=row['review'], source_signal_id=row['signal_id'])
        with runtime_connection() as connection:
            connection.execute('INSERT OR IGNORE INTO runtime_records VALUES(?,?,?,?,?)',
                ('entry_guard', batch_id, canonical_json(guard), row['review']['reviewed_at'], row['review']['reviewed_at']))
