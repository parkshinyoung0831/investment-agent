"""네이티브 Market/Fundamental/Macro/Event desk."""
from __future__ import annotations

from investment_agent.trading.decision.desks.event import analyze_event
from investment_agent.trading.decision.desks.fundamental import analyze_fundamental
from investment_agent.trading.decision.desks.macro import analyze_macro
from investment_agent.trading.decision.desks.market import analyze_market

__all__ = ["analyze_event", "analyze_fundamental", "analyze_macro", "analyze_market"]
