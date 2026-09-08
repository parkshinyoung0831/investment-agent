"""서류철을 LLM 프롬프트용 Markdown으로 줄인다.

원본 서류철은 그대로 보존하고, 여기서만 분량 예산을 적용한다. 예산을 넘으면 잘라내되
**잘랐다는 사실을 본문에 남긴다** — 조용히 자르면 LLM이 없는 것을 없다고 판단한다.
"""
from __future__ import annotations

from typing import Any, Mapping

from investment_agent.trading.evidence.contracts import InvestmentDossier

# 프롬프트 한 장의 상한. 넘으면 뒤쪽 섹션부터 잘린다.
DEFAULT_CHAR_BUDGET = 6000
# 섹션 하나가 프롬프트를 통째로 먹지 못하게 하는 상한.
DEFAULT_SECTION_CHAR_BUDGET = 1200


def _format_number(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, (int, float)):
        if abs(float(value)) >= 1_000_000:
            return f"{float(value):,.0f}"
        if abs(float(value)) < 0.01 and value != 0:
            return f"{float(value):.4%}" if abs(float(value)) < 1 else f"{float(value):.4f}"
        return f"{float(value):,.4g}"
    return str(value)


def _render_mapping(payload: Mapping[str, Any], *, indent: str = "  ") -> list[str]:
    lines: list[str] = []
    for key, value in payload.items():
        if isinstance(value, Mapping):
            if not value:
                continue
            lines.append(f"{indent}- {key}:")
            lines.extend(_render_mapping(value, indent=indent + "  "))
        elif isinstance(value, list):
            if not value:
                continue
            lines.append(f"{indent}- {key}: {len(value)}건")
            for row in value[:5]:
                if isinstance(row, Mapping):
                    inner = ", ".join(
                        f"{name}={_format_number(item)}" for name, item in row.items()
                    )
                    lines.append(f"{indent}  · {inner}")
                else:
                    lines.append(f"{indent}  · {_format_number(row)}")
            if len(value) > 5:
                lines.append(f"{indent}  · … 외 {len(value) - 5}건 생략")
        else:
            lines.append(f"{indent}- {key}: {_format_number(value)}")
    return lines


def render_markdown(
    dossier: InvestmentDossier,
    *,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    section_char_budget: int = DEFAULT_SECTION_CHAR_BUDGET,
) -> str:
    """근거 ID를 함께 적은 사람이 읽을 수 있는 서류철을 만든다."""
    if char_budget < 200 or section_char_budget < 100:
        raise ValueError("dossier render budgets are too small to be useful")
    header = [
        f"# {dossier.ticker} 투자 서류철",
        f"- 기준시각: {dossier.as_of_at}",
        f"- 데이터 종류: {dossier.source_kind}",
        f"- 사용 가능 섹션: {len(dossier.quality.usable_sections)}/"
        f"{len(dossier.sections)} (coverage {dossier.quality.coverage_score:.0%})",
        f"- 서류철 ID: {dossier.dossier_id}",
        "",
    ]
    body: list[str] = []
    truncated_sections: list[str] = []
    for section in dossier.sections:
        block = [f"## {section.title}"]
        if not section.is_known:
            block.append(f"- 사용 불가: {section.missing_reason}")
            block.append("")
            body.extend(block)
            continue
        block.extend(_render_mapping(section.payload))
        block.append(f"- 근거: {', '.join(section.evidence_ids)}")
        block.append(f"- 가용시각: {section.available_at}")
        block.append("")
        text = "\n".join(block)
        if len(text) > section_char_budget:
            text = text[:section_char_budget].rstrip()
            text += f"\n- ⚠️ 이 섹션은 분량 예산({section_char_budget}자)으로 잘렸습니다\n"
            truncated_sections.append(section.section_id)
        body.append(text)

    if dossier.quality.warnings:
        body.append("## 주의")
        body.extend(f"- {text}" for text in dossier.quality.warnings)
        body.append("")

    document = "\n".join(header) + "\n".join(body)
    if len(document) > char_budget:
        document = document[:char_budget].rstrip()
        document += (
            f"\n\n⚠️ 전체 분량 예산({char_budget}자)을 넘어 뒷부분이 잘렸습니다. "
            "잘린 섹션은 없다고 판단하지 마세요."
        )
    elif truncated_sections:
        document += (
            "\n⚠️ 분량으로 잘린 섹션: " + ", ".join(truncated_sections)
            + " — 없다는 뜻이 아닙니다.\n"
        )
    return document


def render_prompt_payload(
    dossier: InvestmentDossier,
    *,
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> dict[str, Any]:
    """구조화 호출용. 본문과 근거 ID를 분리해 모델이 인용을 지어내지 못하게 한다."""
    return {
        "ticker": dossier.ticker,
        "as_of_at": dossier.as_of_at,
        "source_kind": dossier.source_kind,
        "dossier_id": dossier.dossier_id,
        "coverage_score": dossier.quality.coverage_score,
        "missing_sections": list(dossier.quality.missing_sections),
        "allowed_evidence_ids": list(dossier.evidence_ids),
        "markdown": render_markdown(dossier, char_budget=char_budget),
    }


__all__ = [
    "DEFAULT_CHAR_BUDGET",
    "DEFAULT_SECTION_CHAR_BUDGET",
    "render_markdown",
    "render_prompt_payload",
]
