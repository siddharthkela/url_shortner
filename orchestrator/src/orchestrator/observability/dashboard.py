"""Self-contained HTML dashboard: a DAG diagram colored by final node
status, a per-node timing table, and the reliability metrics as stat tiles.
Pure inline SVG/HTML/CSS — no external JS, no server, opens directly in any
browser. This is the "observability dashboard" deliverable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from orchestrator.engine.dag import DAG, NodeStatus
from orchestrator.observability.metrics import ReliabilityMetrics

STATUS_COLORS = {
    NodeStatus.SUCCEEDED: "#2e7d32",
    NodeStatus.FAILED: "#c62828",
    NodeStatus.BLOCKED: "#ef6c00",
    NodeStatus.RUNNING: "#1565c0",
    NodeStatus.PENDING: "#9e9e9e",
}

NODE_W, NODE_H = 150, 44
COL_GAP, ROW_GAP = 210, 70
MARGIN = 30


def compute_layers(dag: DAG) -> Dict[str, int]:
    """Layer = 0 for root nodes, else 1 + max(layer of dependencies).
    Assumes dag.validate() has already confirmed there's no cycle.
    """
    layers: Dict[str, int] = {}

    def layer_of(node_id: str) -> int:
        if node_id in layers:
            return layers[node_id]
        node = dag.nodes[node_id]
        if not node.depends_on:
            layers[node_id] = 0
        else:
            layers[node_id] = 1 + max(layer_of(dep) for dep in node.depends_on)
        return layers[node_id]

    for node_id in dag.nodes:
        layer_of(node_id)
    return layers


def render_dag_svg(dag: DAG) -> str:
    layers = compute_layers(dag)
    by_layer: Dict[int, List[str]] = {}
    for node_id, layer in layers.items():
        by_layer.setdefault(layer, []).append(node_id)
    for ids in by_layer.values():
        ids.sort()

    positions: Dict[str, tuple] = {}
    for layer, node_ids in by_layer.items():
        for row, node_id in enumerate(node_ids):
            x = MARGIN + layer * COL_GAP
            y = MARGIN + row * ROW_GAP
            positions[node_id] = (x, y)

    max_layer = max(by_layer.keys(), default=0)
    max_rows = max((len(v) for v in by_layer.values()), default=1)
    width = MARGIN * 2 + (max_layer + 1) * COL_GAP
    height = MARGIN * 2 + max_rows * ROW_GAP

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" style="max-width:{width}px" font-family="ui-monospace,monospace">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#888"/></marker></defs>',
    ]

    for node in dag.nodes.values():
        x2, y2 = positions[node.id]
        for dep in node.depends_on:
            x1, y1 = positions[dep]
            start_x, start_y = x1 + NODE_W, y1 + NODE_H / 2
            end_x, end_y = x2, y2 + NODE_H / 2
            parts.append(
                f'<line x1="{start_x}" y1="{start_y}" x2="{end_x}" y2="{end_y}" '
                f'stroke="#888" stroke-width="1.5" marker-end="url(#arrow)" />'
            )

    for node in dag.nodes.values():
        x, y = positions[node.id]
        color = STATUS_COLORS.get(node.status, "#9e9e9e")
        badge = "✓" if node.requires_approval else ""
        parts.append(
            f'<g>'
            f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="6" '
            f'fill="{color}" fill-opacity="0.15" stroke="{color}" stroke-width="2"/>'
            f'<text x="{x + NODE_W / 2}" y="{y + NODE_H / 2 - 4}" text-anchor="middle" '
            f'font-size="13" fill="#111">{node.id}</text>'
            f'<text x="{x + NODE_W / 2}" y="{y + NODE_H / 2 + 12}" text-anchor="middle" '
            f'font-size="11" fill="{color}">{node.status.value}{" (approval)" if badge else ""}</text>'
            f'</g>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _stat_tile(label: str, value: str) -> str:
    return (
        f'<div style="border:1px solid #ddd;border-radius:8px;padding:12px 16px;min-width:140px">'
        f'<div style="font-size:12px;color:#666;text-transform:uppercase;letter-spacing:.04em">{label}</div>'
        f'<div style="font-size:24px;font-weight:600;margin-top:4px">{value}</div>'
        f'</div>'
    )


def render_dashboard_html(run_id: str, dag: DAG, metrics: ReliabilityMetrics) -> str:
    tiles = [
        _stat_tile("Success rate", f"{metrics.success_rate * 100:.0f}%"),
        _stat_tile("Nodes", f"{metrics.succeeded_nodes}/{metrics.total_nodes}"),
        _stat_tile("Retries", str(metrics.retry_count)),
        _stat_tile("Rollbacks", str(metrics.rollback_count)),
        _stat_tile("MTTR", f"{metrics.mttr_seconds:.2f}s" if metrics.mttr_seconds is not None else "n/a"),
        _stat_tile(
            "Total latency",
            f"{metrics.total_latency_seconds:.2f}s" if metrics.total_latency_seconds is not None else "n/a",
        ),
    ]

    rows = "".join(
        f"<tr><td>{node_id}</td><td>{latency:.3f}s</td></tr>"
        for node_id, latency in sorted(metrics.per_node_latency_seconds.items())
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Orchestrator run {run_id}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 24px; color: #111; background: #fafafa; }}
  h1 {{ font-size: 20px; }}
  h2 {{ font-size: 15px; margin-top: 32px; }}
  .tiles {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0 24px; }}
  table {{ border-collapse: collapse; font-size: 13px; }}
  td, th {{ border: 1px solid #ddd; padding: 4px 10px; text-align: left; }}
  .dag-container {{ background: white; border: 1px solid #eee; border-radius: 8px; padding: 12px; overflow-x: auto; }}
</style>
</head>
<body>
<h1>Orchestrator run: {run_id}</h1>

<div class="tiles">{"".join(tiles)}</div>

<h2>Execution DAG (final status)</h2>
<div class="dag-container">{render_dag_svg(dag)}</div>

<h2>Per-node latency</h2>
<table><tr><th>Node</th><th>Duration</th></tr>{rows}</table>

</body>
</html>
"""


def write_dashboard(path: Path, run_id: str, dag: DAG, metrics: ReliabilityMetrics) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dashboard_html(run_id, dag, metrics))
