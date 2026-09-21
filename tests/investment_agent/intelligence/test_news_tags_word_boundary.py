"""화면용 뉴스 태그는 단어 경계로 찾는다 — 부분 문자열은 흔한 단어를 위험 태그로 오분류한다(IN-4)."""
from __future__ import annotations

import unittest

from investment_agent.intelligence.infrastructure.sources.news.provider import _sentiment_and_risk


class NewsTagTest(unittest.TestCase):
    def test_common_words_that_contain_a_keyword_are_not_tagged(self) -> None:
        for text in (
            "software awareness warning for users",   # war
            "the company generates corporates buzz",  # rates
            "offered a new product",                  # fed
            "cutting-edge execute plan",              # cut
            "a pitfall and fallout in the plan",      # fall
        ):
            with self.subTest(text=text):
                sentiment, tags = _sentiment_and_risk(text, "")
                self.assertEqual([], tags)
                self.assertEqual("불확실", sentiment)

    def test_real_keywords_and_their_common_endings_are_still_found(self) -> None:
        self.assertEqual(["지정학"], _sentiment_and_risk("War and sanctions escalate", "")[1])
        self.assertEqual(["매크로"], _sentiment_and_risk("Fed holds rates", "")[1])
        self.assertEqual("부정", _sentiment_and_risk("Shares fall after downgrade", "")[0])
        self.assertEqual("긍정", _sentiment_and_risk("Record profit as sales surge", "")[0])

    def test_korean_terms_keep_substring_matching(self) -> None:
        self.assertEqual(["규제"], _sentiment_and_risk("당국 규제 강화", "")[1])


if __name__ == "__main__":
    unittest.main()
