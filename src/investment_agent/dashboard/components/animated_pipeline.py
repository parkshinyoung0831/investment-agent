"""Alpha Lab의 실행 단계를 움직이는 흐름으로 보여주는 Streamlit 컴포넌트."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import streamlit as st
from streamlit.errors import StreamlitAPIException


_HTML = """
<section class="pipeline-shell" aria-label="투자 엔진 흐름 미리보기">
  <header class="pipeline-header">
    <div>
      <span class="pipeline-kicker">운영 경로</span>
      <strong>근거가 투자 판단으로 바뀌는 과정</strong>
    </div>
    <button class="pipeline-control" type="button" aria-pressed="false">멈추기</button>
  </header>
  <div class="pipeline-stage">
    <svg class="pipeline-edges" aria-hidden="true"></svg>
    <div class="pipeline-grid"></div>
  </div>
  <aside class="pipeline-detail" aria-live="off">
    <span class="detail-index"></span>
    <div>
      <strong class="detail-title"></strong>
      <p class="detail-copy"></p>
    </div>
    <span class="detail-value"></span>
  </aside>
  <p class="pipeline-note">현재 저장된 사실과 코드 구조를 함께 보여줘요. 이 화면에서는 주문을 실행하지 않아요.</p>
</section>
"""


_CSS = """
:host {
  display: block;
  color: var(--st-text-color);
  font-family: var(--st-font);
}

* { box-sizing: border-box; }

.pipeline-shell {
  border: 1px solid var(--st-border-color);
  border-radius: 20px;
  background: var(--st-background-color);
  padding: 20px;
  overflow: hidden;
}

.pipeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.pipeline-header > div {
  display: grid;
  gap: 5px;
}

.pipeline-kicker {
  color: var(--st-primary-color);
  font-family: var(--st-code-font);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .04em;
}

.pipeline-header strong {
  color: var(--st-heading-color);
  font-size: 17px;
  line-height: 1.35;
}

.pipeline-control {
  min-width: 76px;
  min-height: 44px;
  border: 1px solid var(--st-widget-border-color);
  border-radius: var(--st-button-radius);
  background: var(--st-secondary-background-color);
  color: var(--st-text-color);
  font: 600 13px/1 var(--st-font);
  cursor: pointer;
  transition: border-color 200ms cubic-bezier(.22,.61,.36,1), background 200ms cubic-bezier(.22,.61,.36,1);
}

.pipeline-control:hover { border-color: var(--st-primary-color); }
.pipeline-control:focus-visible,
.pipeline-node:focus-visible {
  outline: 2px solid var(--st-primary-color);
  outline-offset: 2px;
}

.pipeline-stage {
  position: relative;
  isolation: isolate;
}

.pipeline-edges {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
  z-index: 0;
}

.edge-base,
.edge-flow {
  fill: none;
  vector-effect: non-scaling-stroke;
}

.edge-base {
  stroke: var(--st-border-color);
  stroke-width: 1.5;
}

.edge-flow {
  stroke: var(--st-primary-color);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-dasharray: 5 13;
  opacity: .28;
  animation: pipeline-flow 1.1s linear infinite;
  transition: opacity 200ms cubic-bezier(.22,.61,.36,1), stroke-width 200ms cubic-bezier(.22,.61,.36,1);
}

.edge-flow.is-current {
  opacity: .9;
  stroke-width: 2.5;
}

@keyframes pipeline-flow { to { stroke-dashoffset: -18; } }

.pipeline-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 24px 36px;
}

.pipeline-node {
  position: relative;
  min-width: 0;
  min-height: 116px;
  border: 1px solid var(--st-border-color);
  border-radius: 16px;
  background: var(--st-secondary-background-color);
  color: var(--st-text-color);
  padding: 14px 16px;
  text-align: left;
  cursor: pointer;
  box-shadow: none;
  transition: border-color 200ms cubic-bezier(.22,.61,.36,1), transform 200ms cubic-bezier(.22,.61,.36,1), background 200ms cubic-bezier(.22,.61,.36,1);
}

.pipeline-node:hover { border-color: var(--st-widget-border-color); }
.pipeline-node.is-active {
  border-color: var(--st-primary-color);
  transform: translateY(-2px);
}

.pipeline-node.is-active::after {
  content: "";
  position: absolute;
  width: 9px;
  height: 9px;
  top: 14px;
  right: 14px;
  border-radius: 999px;
  background: var(--st-primary-color);
  animation: pipeline-pulse 1.1s ease-out infinite;
}

@keyframes pipeline-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--st-primary-color) 34%, transparent); }
  70%, 100% { box-shadow: 0 0 0 9px transparent; }
}

.node-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.node-index,
.node-value,
.detail-index,
.detail-value {
  font-family: var(--st-code-font);
  font-variant-numeric: tabular-nums;
}

.node-index {
  color: var(--st-primary-color);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .06em;
}

.node-status {
  color: var(--st-gray-text-color);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-status.is-ready { color: var(--st-green-text-color); }
.node-status.is-blocked { color: var(--st-red-text-color); }
.node-status.is-waiting { color: var(--st-gray-text-color); }

.node-title {
  display: block;
  margin-bottom: 9px;
  color: var(--st-heading-color);
  font-size: 15px;
  line-height: 1.35;
}

.node-value {
  display: block;
  color: var(--st-text-color);
  font-size: 16px;
  font-weight: 700;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.pipeline-detail {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  min-height: 64px;
  margin-top: 16px;
  padding: 12px 16px;
  border: 1px solid var(--st-border-color-light);
  border-radius: 14px;
  background: var(--st-secondary-background-color);
}

.detail-index {
  color: var(--st-primary-color);
  font-size: 12px;
  font-weight: 700;
}

.pipeline-detail strong {
  display: block;
  color: var(--st-heading-color);
  font-size: 13px;
}

.pipeline-detail p {
  margin: 3px 0 0;
  color: var(--st-gray-text-color);
  font-size: 12px;
  line-height: 1.4;
}

.detail-value {
  max-width: 190px;
  color: var(--st-text-color);
  font-size: 13px;
  font-weight: 700;
  overflow-wrap: anywhere;
  text-align: right;
}

.pipeline-note {
  margin: 8px 2px 0;
  color: var(--st-gray-text-color);
  font-size: 12px;
  line-height: 1.45;
}

@media (max-width: 900px) {
  .pipeline-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px 42px; }
}

@media (max-width: 560px) {
  .pipeline-shell { padding: 16px; }
  .pipeline-header { align-items: flex-start; }
  .pipeline-grid { grid-template-columns: minmax(0, 1fr); gap: 26px; }
  .pipeline-node { min-height: 124px; }
  .pipeline-detail { grid-template-columns: auto minmax(0, 1fr); }
  .detail-value { grid-column: 2; max-width: none; text-align: left; }
}

@media (prefers-reduced-motion: reduce) {
  .edge-flow { animation: none; stroke-dasharray: none; }
  .pipeline-node,
  .pipeline-control { transition: none; }
  .pipeline-node.is-active { transform: none; }
  .pipeline-node.is-active::after { animation: none; }
}
"""


_JS = """
export default function(component) {
  const { data, parentElement } = component
  const root = parentElement.querySelector('.pipeline-shell')
  const grid = parentElement.querySelector('.pipeline-grid')
  const svg = parentElement.querySelector('.pipeline-edges')
  const control = parentElement.querySelector('.pipeline-control')
  const detailIndex = parentElement.querySelector('.detail-index')
  const detailTitle = parentElement.querySelector('.detail-title')
  const detailCopy = parentElement.querySelector('.detail-copy')
  const detailValue = parentElement.querySelector('.detail-value')
  const note = parentElement.querySelector('.pipeline-note')
  if (!root || !grid || !svg || !control) return

  if (note) note.hidden = data?.show_note === false

  const steps = Array.isArray(data?.steps) ? data.steps : []
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  let activeIndex = Math.max(0, Math.min(Number(data?.active_index ?? 0), steps.length - 1))
  let isPaused = reducedMotion || !Boolean(data?.preview)
  let timer = null
  let frame = null

  grid.replaceChildren()
  svg.replaceChildren()

  const nodes = steps.map((step, index) => {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'pipeline-node'
    button.dataset.index = String(index)
    button.setAttribute('aria-label', `${index + 1}단계 ${step.title}. ${step.value}. 상태 ${step.status}`)

    const top = document.createElement('span')
    top.className = 'node-top'
    const number = document.createElement('span')
    number.className = 'node-index'
    number.textContent = String(index + 1).padStart(2, '0')
    const status = document.createElement('span')
    status.className = 'node-status'
    status.textContent = step.status
    const statusText = String(step.status || '').toLowerCase()
    if (/완료|운영|통과|유효|연결/.test(statusText)) status.classList.add('is-ready')
    else if (/차단|실패|거절|위반/.test(statusText)) status.classList.add('is-blocked')
    else status.classList.add('is-waiting')
    top.append(number, status)

    const title = document.createElement('strong')
    title.className = 'node-title'
    title.textContent = step.title
    const value = document.createElement('span')
    value.className = 'node-value'
    value.textContent = step.value
    button.append(top, title, value)
    grid.appendChild(button)
    return button
  })

  const edgeFlows = []

  function pathBetween(from, to) {
    const stageRect = grid.getBoundingClientRect()
    const fromRect = from.getBoundingClientRect()
    const toRect = to.getBoundingClientRect()
    const fromCenterX = fromRect.left - stageRect.left + fromRect.width / 2
    const toCenterX = toRect.left - stageRect.left + toRect.width / 2
    const fromCenterY = fromRect.top - stageRect.top + fromRect.height / 2
    const toCenterY = toRect.top - stageRect.top + toRect.height / 2
    const sameRow = Math.abs(fromCenterY - toCenterY) < 20
    const x1 = sameRow ? fromRect.right - stageRect.left : fromCenterX
    const y1 = sameRow ? fromCenterY : fromRect.bottom - stageRect.top
    const x2 = sameRow ? toRect.left - stageRect.left : toCenterX
    const y2 = sameRow ? toCenterY : toRect.top - stageRect.top
    if (sameRow) {
      const bend = Math.max(24, Math.abs(x2 - x1) * .45)
      return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`
    }
    const bend = Math.max(28, Math.abs(y2 - y1) * .48)
    return `M ${x1} ${y1} C ${x1} ${y1 + bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`
  }

  function drawEdges() {
    svg.replaceChildren()
    edgeFlows.length = 0
    svg.setAttribute('viewBox', `0 0 ${grid.clientWidth} ${grid.clientHeight}`)
    for (let index = 0; index < nodes.length - 1; index += 1) {
      const d = pathBetween(nodes[index], nodes[index + 1])
      const base = document.createElementNS('http://www.w3.org/2000/svg', 'path')
      base.setAttribute('class', 'edge-base')
      base.setAttribute('d', d)
      const flow = document.createElementNS('http://www.w3.org/2000/svg', 'path')
      flow.setAttribute('class', 'edge-flow')
      flow.setAttribute('d', d)
      flow.dataset.to = String(index + 1)
      svg.append(base, flow)
      edgeFlows.push(flow)
    }
    updateActive()
  }

  function updateActive() {
    nodes.forEach((node, index) => {
      const isActive = index === activeIndex
      node.classList.toggle('is-active', isActive)
      node.setAttribute('aria-pressed', String(isActive))
    })
    edgeFlows.forEach((edge) => edge.classList.toggle('is-current', Number(edge.dataset.to) === activeIndex))
    const step = steps[activeIndex]
    if (!step) return
    detailIndex.textContent = String(activeIndex + 1).padStart(2, '0')
    detailTitle.textContent = step.title
    detailCopy.textContent = step.detail
    detailValue.textContent = step.value
  }

  function syncControl() {
    control.textContent = isPaused ? '다시 재생' : '멈추기'
    control.setAttribute('aria-pressed', String(isPaused))
  }

  function startTimer() {
    if (timer) window.clearInterval(timer)
    timer = null
    if (!isPaused && steps.length > 1) {
      timer = window.setInterval(() => {
        activeIndex = (activeIndex + 1) % steps.length
        updateActive()
      }, 1250)
    }
    syncControl()
  }

  nodes.forEach((node, index) => {
    node.onclick = () => {
      activeIndex = index
      isPaused = true
      updateActive()
      startTimer()
    }
  })

  control.onclick = () => {
    if (reducedMotion) return
    isPaused = !isPaused
    startTimer()
  }

  if (reducedMotion) {
    control.textContent = '모션 줄임'
    control.disabled = true
  } else {
    startTimer()
  }

  updateActive()
  frame = window.requestAnimationFrame(drawEdges)
  const observer = new ResizeObserver(() => {
    if (frame) window.cancelAnimationFrame(frame)
    frame = window.requestAnimationFrame(drawEdges)
  })
  observer.observe(grid)

  return () => {
    if (timer) window.clearInterval(timer)
    if (frame) window.cancelAnimationFrame(frame)
    observer.disconnect()
  }
}
"""


def _register_component():
    """현재 Streamlit 런타임에 컴포넌트를 등록한다."""

    return st.components.v2.component(
        "atlas_animated_pipeline_v2",
        html=_HTML,
        css=_CSS,
        js=_JS,
    )


_ANIMATED_PIPELINE = _register_component()


def normalise_pipeline_steps(steps: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """외부 값을 HTML로 해석하지 않고 짧은 화면 문자열로 제한한다."""

    keys = ("title", "value", "detail", "status")
    return [
        {key: str(step.get(key) or "—")[:240] for key in keys}
        for step in steps
    ]


def animated_pipeline(
    steps: Sequence[Mapping[str, Any]],
    *,
    key: str,
    preview: bool = True,
    active_index: int = 0,
    show_note: bool = True,
) -> None:
    """Python 상태를 전달하고 애니메이션은 브라우저 안에서만 실행한다."""

    global _ANIMATED_PIPELINE
    mount_options = {
        "key": key,
        "data": {
            "steps": normalise_pipeline_steps(steps),
            "preview": preview,
            "active_index": max(0, int(active_index)),
            "show_note": bool(show_note),
        },
        "width": "stretch",
        "height": "content",
    }
    try:
        _ANIMATED_PIPELINE(**mount_options)
    except StreamlitAPIException as exc:
        # AppTest는 테스트별로 런타임 레지스트리를 비우지만 Python 모듈은
        # 재사용한다. 실제 앱의 일반 rerun에는 재등록하지 않는다.
        if "is not registered" not in str(exc):
            raise
        _ANIMATED_PIPELINE = _register_component()
        _ANIMATED_PIPELINE(**mount_options)


__all__ = ["animated_pipeline", "normalise_pipeline_steps"]
