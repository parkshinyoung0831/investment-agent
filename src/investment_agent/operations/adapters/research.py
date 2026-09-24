"""Research-owner harness stage adapters."""
from __future__ import annotations

from investment_agent.operations.harness.commands import PythonModuleCommand
from investment_agent.operations.harness.contracts import StageContext, StageOutcome


class ResearchAdapters:
    def refresh_indicators(self, context: StageContext) -> StageOutcome:
        """이 장비의 로컬 RSI·MACD 저장소를 최신 가격까지 갱신한다.

        feature snapshot과 판단 서류철이 이 저장소를 읽는다. Actions의 tech_indicators는
        러너 artifact에만 쓰므로 로컬 사본은 이 단계가 아니면 갱신되지 않는다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.features.daily",
                (),
                self.timeouts.get("refresh_indicators", 20 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"indicators_refreshed_at": self.now().isoformat()})
    def build_valuations(self, context: StageContext) -> StageOutcome:
        """PIT 밸류에이션 관측값을 원장에 적재한다.

        live_shadow만 만든다 — 과거 시점은 가격 적재시각과 TTM vintage를 증명할 수
        없어 진입점이 거부한다. feature 단계보다 먼저 둬서 이후 feature 세대가 이
        관측값을 읽을 수 있게 한다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_valuations",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_valuations", 60 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"valued_at": self.now().isoformat()})
    def build_features(self, context: StageContext) -> StageOutcome:
        """tracked universe의 PIT feature snapshot을 ResearchStore에 적재한다.

        주문이 아니라 데이터 생산이라 거래 kill switch·거래 창과 무관하게 돈다.
        결과는 versioned `rl_feature_snapshots` dataset에 기록되고, 재실행은 같은 키를
        upsert한다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_features",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_features", 60 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"built_at": self.now().isoformat()})
    def build_training_samples(self, context: StageContext) -> StageOutcome:
        """확정된 label을 비용 반영 학습 표본으로 바꿔 쌓는다.

        label 단계 뒤에 붙는다. gross 수익률을 그대로 학습하면 모델이 회전율을
        과대평가하므로, 여기서 왕복 수수료·슬리피지를 적용한 net label을 만든다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_training_samples",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_training_samples", 60 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"sampled_at": self.now().isoformat()})
    def build_decision_experiences(self, context: StageContext) -> StageOutcome:
        """승인 여부와 무관하게 원본 판단의 확정된 결과를 경험 원장에 기록한다(추천 성과 보고의 원천)."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.operations.commands.build_decision_experiences",
            ("--as-of", context.now.isoformat()),
            self.timeouts.get("build_decision_experiences", 60 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"experiences_built_at": self.now().isoformat()})
    def run_ml_challengers(self, context: StageContext) -> StageOutcome:
        """쌓인 feature·label로 ML 후보를 다시 학습하고, 기준을 넘으면 채택·순위 능력을 잃으면 해제한다."""
        self.command_runner.run(PythonModuleCommand(
            "investment_agent.research.commands.ml_challengers",
            ("--as-of", context.now.isoformat()),
            self.timeouts.get("ml_challengers", 3 * 60 * 60),
        ), stop_event=context.stop_event)
        return StageOutcome.succeeded({"ml_challengers_run_at": self.now().isoformat()})
    def evaluate_decisions(self, context: StageContext) -> StageOutcome:
        """성숙한 과거 Shadow 판단을 SPY 대비 5·20·60 거래일로 채점한다.

        주문이 아니라 채점이라 거래 kill switch와 무관하다. 이 결과가
        `decision_evaluations`에 쌓여야 `CaseMemory`가 다음 판단에 과거 성적을
        넘길 수 있다 — 돌지 않으면 학습 루프가 열린 채로 남는다.
        같은 case의 같은 horizon은 다시 쓰지 않으므로 매일 돌려도 안전하다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.evaluate_decisions",
                (),
                self.timeouts.get("evaluate_decisions", 30 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"evaluated_at": self.now().isoformat()})
    def evaluate_system(self, context: StageContext) -> StageOutcome:
        """최신 System artifact의 승격 증거를 만든다(5년 재현 + 운영 NAV). 읽기와 평가 원장 쓰기뿐이다."""
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.system_evaluations",
                (),
                self.timeouts.get("evaluate_system", 90 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"evaluated_at": self.now().isoformat()})
    def measure_factor_ic(self, context: StageContext) -> StageOutcome:
        """factor별 IC를 명령의 기본 기간(5·20·60·126거래일)으로 다시 잰다. 결과는 artifacts/research/factor_ic에 쌓인다."""
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.factor_research",
                (),
                self.timeouts.get("measure_factor_ic", 30 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"measured_at": self.now().isoformat()})
    def diagnose_system(self, context: StageContext) -> StageOutcome:
        """System 목표를 5·20·60·120거래일 실현 수익으로 채점해 어느 단계가 틀렸는지 남긴다.

        읽기 전용 채점이라 거래 kill switch와 무관하다. 판정은 기록만 하고 정책을 바꾸지 않는다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.operations.commands.system_diagnosis",
                (),
                self.timeouts.get("diagnose_system", 30 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"diagnosed_at": self.now().isoformat()})
    def build_events(self, context: StageContext) -> StageOutcome:
        """로컬 뉴스·소셜 원문을 사건과 event feature로 압축해 원장에 남긴다.

        원문은 Supabase로 가지 않는다. 올라가는 것은 사건 단위 요약뿐이라 이 단계가
        없으면 Research local dataset `events`가 비고, 대시보드의 사건 패널도 빈 채로 남는다.
        원천이 90일치 로컬 캐시라 실패해도 나중에 다시 만들 수 있어 맨 뒤에 둔다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_events",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_events", 15 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"events_built_at": self.now().isoformat()})
    def build_labels(self, context: StageContext) -> StageOutcome:
        """미래 구간이 끝난 snapshot에만 forward return label을 붙인다.

        feature 적재 뒤에 이어 붙는다. 구간이 아직 열려 있는 snapshot은 건드리지
        않으므로 매일 돌려도 같은 행을 다시 만들지 않는다.
        """
        self.command_runner.run(
            PythonModuleCommand(
                "investment_agent.research.commands.build_labels",
                ("--as-of", context.now.isoformat()),
                self.timeouts.get("build_labels", 60 * 60),
            ),
            stop_event=context.stop_event,
        )
        return StageOutcome.succeeded({"labeled_at": self.now().isoformat()})
