# Graphify MCP Server — 코드 지식 그래프 연동 가이드

이 문서는 이 저장소의 지식 그래프(`graphify-out/graph.json`)를 MCP(Model Context Protocol) 서버로 노출하여, AI 에이전트(Google Antigravity, Claude Desktop, Cursor 등)가 네이티브 도구 호출로 코드베이스 구조를 질의할 수 있도록 설정하는 방법을 설명합니다.

---

## 1. 개요

Graphify는 `graphify.serve` 모듈을 통해 표준 입출력(stdio) 기반의 MCP 서버를 제공합니다.
이를 통해 에이전트는 26MB 이상의 원시 JSON을 직접 읽거나 검색하는 대신, 최적화된 부분 그래프 쿼리 도구를 사용합니다.

### 제공되는 핵심 MCP 도구

| 도구 이름 | 설명 | 매개변수 |
|---|---|---|
| `query_graph` | 자연어 질문 기반 그래프 탐색 (BFS/DFS) | `question`, `mode` (bfs/dfs), `budget` |
| `shortest_path` | 두 노드/심볼 간의 최단 호출/의존성 경로 계산 | `source`, `target` |
| `get_node` | 특정 노드의 메타데이터 및 상세 정보 조회 | `node_id` |
| `get_neighbors` | 특정 노드에 인접한 입출력 이웃 노드 및 관계 조회 | `node_id`, `direction` (in/out/both) |
| `get_community` | 특정 커뮤니티 ID에 속한 노드 목록 및 요약 조회 | `community_id` |
| `god_nodes` | 가장 높은 중심성(Degree/Betweenness)을 가진 핵심 추상화 노드 목록 | `limit` |
| `graph_stats` | 전체 노드 수, 엣지 수, 커뮤니티 수 등 그래프 통계 | 없음 |

---

## 2. 수동 실행 및 테스트

명령줄에서 직접 MCP 서버가 정상 작동하는지 테스트할 수 있습니다.

```powershell
# Python 인터프리터를 사용하여 graphify-out/graph.json 서빙
& (Get-Content graphify-out\.graphify_python) -m graphify.serve graphify-out/graph.json
```

---

## 3. 에이전트 클라이언트 설정

### A. Claude Desktop (`claude_desktop_config.json`)

`%APPDATA%\Claude\claude_desktop_config.json` 파일의 `mcpServers` 블록에 아래 설정을 추가합니다:

```json
{
  "mcpServers": {
    "graphify": {
      "command": "C:\\Users\\parks\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": [
        "-m",
        "graphify.serve",
        "C:\\Users\\parks\\Documents\\개인폴더\\투자 ai\\investment-agent-main\\graphify-out\\graph.json"
      ]
    }
  }
}
```

### B. Google Antigravity / Gemini CLI

Antigravity의 MCP 설정 파일(`mcp.json` 또는 sidecar 설정)에 동일한 명령행과 인자를 등록하여 사용할 수 있습니다.

---

## 4. 자가 학습 작업 메모리 (`save-result` & `reflect`)

에이전트가 복잡한 아키텍처 탐색 결과를 얻었을 때, 다음 명령으로 지식을 저장하고 세션 간에 공유할 수 있습니다:

```bash
# 유용한 탐색 결과 저장
python -m graphify save-result --question "ResearchStore와 Dashboard의 연결 관계" --answer "..." --type query --nodes ResearchStore dashboard/db.py --outcome useful

# 세션 시작 시 축적된 교훈 반영
python -m graphify reflect --if-stale
```

결과는 `graphify-out/reflections/LESSONS.md`에 지속적으로 누적됩니다.
