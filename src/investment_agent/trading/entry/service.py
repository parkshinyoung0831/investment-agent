"""가격 감시와 비용 제한 LLM 진입 재판단. 주문 권한은 갖지 않는다."""
from __future__ import annotations

from datetime import timedelta
from investment_agent.platform.serialization import parse_datetime, stable_id
from investment_agent.trading.entry.rules import create_plan, trigger_status, validate_review


def scan(*, book, store, quotes, analyze, publish, now, max_llm_calls=2):
    """작은 호출 예산 내에서 계획을 만들고 조건 도달 후보만 다시 검토한다."""
    existing = {row['signal_id']:row for row in store.candidates()}
    derived = {row.get('batch_id') for row in existing.values()}
    # 파생 실행 배치를 다시 분석 후보로 넣지 않는다.
    records = [record for record in book.records if record.batch_id not in derived and record.is_valid_at(now)]
    latest = {}
    for record in records:
        if record.proposal.ticker not in latest or record.recorded_at > latest[record.proposal.ticker].recorded_at:
            latest[record.proposal.ticker] = record
    calls = 0
    for row in existing.values():
        if row['status']=='ready' and parse_datetime(row['review']['expires_at']) <= now:
            row.update(status='expired',next_check_at=now.isoformat())
            store.save(row)
        if row['status'] in ('ready','watching') and row['ticker'] in latest and latest[row['ticker']].signal_id != row['signal_id']:
            row.update(status='superseded',next_check_at=now.isoformat())
            store.save(row)
    for record in sorted(latest.values(), key=lambda r: (existing.get(r.signal_id,{}).get('next_check_at',''),r.recorded_at,r.signal_id)):
        if record.proposal.signal not in ('open','increase','reduce','exit'):
            continue
        row = existing.get(record.signal_id,dict(signal_id=record.signal_id,ticker=record.proposal.ticker,
            source_batch_id=record.batch_id,status='new',next_check_at=now.isoformat()))
        if row['status'] in ('cancelled','expired','ready','consumed','superseded') or parse_datetime(row['next_check_at']) > now:
            continue
        price, quoted_at = quotes.get(row['ticker'], (None,None))
        if price is None or quoted_at is None or not 0 <= (now-parse_datetime(quoted_at)).total_seconds() <= 120:
            continue
        if record.proposal.signal in ('reduce','exit') and not row.get('plan'):
            row['plan']=dict(lower_price=price*.99,upper_price=price*1.01,invalidate_below=price*.5,
                expires_at=record.expires_at,created_at=now.isoformat(),reason='축소·청산 판단은 매수 대기 없이 현재 시점에서 재검토')
        if not row.get('plan'):
            if calls >= max_llm_calls or not store.claim(row,now=now):
                continue
            calls += 1
            raw = analyze('plan',record,dict(price=price,quoted_at=quoted_at),None)
            evaluated_at=parse_datetime(raw.get('evaluated_at',now.isoformat()))
            row['plan'] = create_plan(raw,reference_price=price,now=evaluated_at,source_expires_at=record.expires_at)
            row['plan'].update({key:raw[key] for key in ('model','evidence_hash') if key in raw})
            row.update(status='watching',next_check_at=(now+timedelta(minutes=1)).isoformat())
            store.save(row)
            continue
        status = trigger_status(row['plan'],price=price,quoted_at=quoted_at,now=now)
        if status in ('cancelled','expired'):
            row.update(status=status,next_check_at=now.isoformat())
            store.save(row)
        elif status == 'triggered' and calls < max_llm_calls and store.claim(row,now=now):
            calls += 1
            raw = analyze('review',record,dict(price=price,quoted_at=quoted_at),row['plan'])
            evaluated_at=parse_datetime(raw.get('evaluated_at',now.isoformat()))
            quote=raw.get('fresh_quote',dict(price=price,quoted_at=quoted_at))
            if quote.get('price') is None or trigger_status(row['plan'],price=quote['price'],quoted_at=quote.get('quoted_at'),now=evaluated_at) != 'triggered':
                raw={**raw,'decision':'wait','reason':'재판단 중 가격 또는 시세 유효성이 변경됨'}
            review = validate_review(raw,now=evaluated_at,expires_at=row['plan']['expires_at'])
            review.update({key:raw[key] for key in ('model','evidence_hash') if key in raw})
            review.update(signal_id=record.signal_id,original_decision=record.proposal.to_dict(),quote=quote)
            review['review_id'] = stable_id('entry_review',review)
            store.save_review(review)
            row.update(review=review,next_check_at=(now+timedelta(minutes=15)).isoformat())
            if review['decision']=='enter':
                row['batch_id'] = publish(record,review=review)
                store.save_guard(row['batch_id'],row)
                row['status']='ready'
            else:
                row['status']='cancelled' if review['decision']=='cancel' else 'watching'
            store.save(row)
    return dict(llm_calls=calls,ready=len(store.ready(now=now)))
