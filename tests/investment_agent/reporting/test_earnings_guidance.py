from __future__ import annotations

import unittest

from investment_agent.notifications.earnings_flash import embeds
from investment_agent.reporting.services.earnings.guidance import format_guidance_headline

RAISE = "🟢 연간 실적 전망 상향 (Raises Outlook)"
LOWER = "🔴 연간 실적 전망 하향 (Lowers Outlook)"
MAINTAIN = "🔵 연간 실적 전망 유지 (Maintains Outlook)"
NEXT_QUARTER = "📌 다음 분기 가이던스 제시"


class EarningsGuidanceHeadlineTest(unittest.TestCase):
    """속보 embed와 실적 화면이 같은 가이던스 문장을 주장하는지."""

    def test_no_guidance_text_yields_nothing(self) -> None:
        self.assertIsNone(format_guidance_headline(None))
        self.assertIsNone(format_guidance_headline(""))

    def test_active_verb_taking_the_outlook_noun_sets_the_direction(self) -> None:
        self.assertEqual(RAISE, format_guidance_headline("Company raises full-year outlook"))
        self.assertEqual(LOWER, format_guidance_headline("Company lowers full-year outlook"))
        self.assertEqual(MAINTAIN, format_guidance_headline("Company reaffirms full-year outlook"))
        # 동사와 명사 사이의 수식어를 넘어서도 잡는다.
        self.assertEqual(
            RAISE,
            format_guidance_headline("The Company raised its full-year 2026 revenue guidance to $10.2 billion."),
        )

    def test_passive_form_needs_an_auxiliary(self) -> None:
        self.assertEqual(
            LOWER,
            format_guidance_headline("Full-year guidance was lowered to reflect currency headwinds."),
        )
        # 조동사 없는 명사구는 방향이 아니다 — "cost cut"은 비용 절감이지 전망 하향이 아니다.
        self.assertIsNone(
            format_guidance_headline("Full-year guidance reflects cost cut initiatives announced in May.")
        )

    def test_unchanged_reads_as_maintained_without_an_auxiliary(self) -> None:
        self.assertEqual(MAINTAIN, format_guidance_headline("Full-year outlook remains unchanged."))
        self.assertEqual(MAINTAIN, format_guidance_headline("Full-year revenue outlook unchanged"))

    def test_performance_sentences_never_claim_a_direction(self) -> None:
        """실적 서술은 전망이 아니다.

        원문은 보도자료 문단을 이어 붙인 것이라 실적 서술과 전망이 같이 들어온다. 예전
        구현은 `increased`/`cut` 포함 여부만 봐서 이런 문장에 상향·하향 배지를 달았다.
        """
        for sentence in (
            "Revenue increased 12% year over year to $4.1 billion.",
            "Operating costs were cut by $200 million during the quarter.",
            "Diluted EPS increased to $1.42 from $1.19.",
        ):
            headline = format_guidance_headline(sentence)
            self.assertNotIn(headline, (RAISE, LOWER, MAINTAIN), sentence)

    def test_direction_does_not_cross_the_paragraph_separator(self) -> None:
        # 같은 문단 안의 전망만 읽는다.
        self.assertEqual(
            RAISE,
            format_guidance_headline("Q3 revenue increased 12% | The company raised its outlook."),
        )
        # 앞 문단의 동사가 뒤 문단의 명사를 잡지는 못한다.
        self.assertNotIn(
            format_guidance_headline("The company cut 200 jobs this quarter | Full-year revenue was $4.1 billion."),
            (RAISE, LOWER, MAINTAIN),
        )

    def test_next_quarter_guidance_is_added_to_the_direction_badge(self) -> None:
        self.assertEqual(
            f"{RAISE} · {NEXT_QUARTER}",
            format_guidance_headline("Raises FY outlook and issues guidance for Q4"),
        )
        self.assertEqual(
            NEXT_QUARTER,
            format_guidance_headline("The company issues guidance for the fourth quarter."),
        )

    def test_unmatched_text_falls_back_to_the_first_short_segment(self) -> None:
        self.assertEqual(
            "Full-year revenue was $4.1 billion",
            format_guidance_headline("- Full-year revenue was $4.1 billion | 기타 세부내역"),
        )
        self.assertIsNone(format_guidance_headline("x" * 61))

    def test_notify_embed_reexports_the_reporting_contract(self) -> None:
        self.assertIs(embeds.format_guidance_headline, format_guidance_headline)
