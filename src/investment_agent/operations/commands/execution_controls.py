"""로컬 실행 제어 원장의 초기 설치와 명시적인 운영자 설정."""
from __future__ import annotations

import argparse
from dataclasses import asdict

from investment_agent.execution.db import ExecutionRepository
from investment_agent.platform.logging import get_logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--initialize', action='store_true')
    actions.add_argument('--manual', choices=('on', 'off'))
    parser.add_argument('--expected-version', type=int)
    parser.add_argument('--reason', default='')
    parser.add_argument('--confirm', default='')
    args = parser.parse_args(argv)
    repository = ExecutionRepository()
    if args.initialize:
        state = repository.initialize_control_state()
    elif args.manual is not None:
        if args.expected_version is None or not args.reason.strip():
            parser.error('--expected-version and --reason are required')
        if args.manual == 'on' and args.confirm != 'I_CONFIRM_MANUAL_APPROVAL_EXECUTION':
            parser.error('manual enabling requires --confirm I_CONFIRM_MANUAL_APPROVAL_EXECUTION')
        state = repository.set_manual_control_state(expected_version=args.expected_version,
            is_enabled=args.manual == 'on', reason=args.reason)
    else:
        state = repository.load_control_state()
    get_logger(__name__).info('execution controls: %s', asdict(state))
    return 0


if __name__ == '__main__':
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
