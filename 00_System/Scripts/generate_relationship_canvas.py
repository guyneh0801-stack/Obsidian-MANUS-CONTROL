#!/usr/bin/env python3
"""
Position-preserving relationship Canvas generator for MANUS CONTROL.

The relationship notes in 04_Relationships are the source of truth for edges.
The existing Canvas files are the source of truth for manual node layout.

Practical behavior:
- Existing text nodes keep their current id, x, y, width, height, and color.
- New entities found in Relationship Notes are added automatically.
- Edges are regenerated from Relationship Notes on each run.
- Existing manual/non-source nodes are kept.
- Automatically generated case group nodes are refreshed on each run.
- If an existing Canvas is malformed, it is backed up before a new file is written.
- Generates a global Canvas, per-case Canvas files, per-case edge lists, and a Markdown dashboard.
"""

from pathlib import Path
from datetime import datetime
import hashlib
import json
import math
import re
import shutil
from collections import defaultdict

BASE = Path(__file__).resolve().parents[2]
REL_DIR = BASE / "04_Relationships"
DASHBOARD = REL_DIR / "Relationship Map Dashboard.md"

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)
DEFAULT_NODE_WIDTH = 260
DEFAULT_NODE_HEIGHT = 90
DEFAULT_NODE_COLOR = "2"
MULTI_CASE_NODE_COLOR = "6"
GROUP_MARGIN = 160
GRID_SIZE = 20
CASE_COLOR_PALETTE = ["1", "2", "3", "4", "5", "6"]
AUTO_CASE_GROUP_PREFIX = "Case: "
AUTO_CASE_LEGEND_LABEL = "Case Color Legend"


def parse_simple_yaml(text: str):
    """Parse the simple frontmatter style used by MANUS CONTROL templates."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}

    raw = m.group(1)
    data = {}
    current_key = None

    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue

        if re.match(r"^[A-Za-z0-9_\-]+:\s*", line):
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            current_key = key

            if val == "[]":
                data[key] = []
            elif val == "":
                data[key] = ""
            else:
                data[key] = val.strip("\"").strip("\'")
        elif current_key and line.strip().startswith("-"):
            data.setdefault(current_key, [])
            if not isinstance(data[current_key], list):
                data[current_key] = [data[current_key]] if data[current_key] else []
            data[current_key].append(line.strip()[1:].strip().strip("\"").strip("\'"))

    return data


def clean_entity(value: str):
    """Normalize entity values, including Obsidian wikilinks."""
    if not value:
        return ""

    value = str(value).strip().strip("\"").strip("\'")
    m = re.match(r"^\[\[([^\]|]+)(?:\|([^\]]+))?\]\]$", value)
    if m:
        return (m.group(2) or m.group(1)).strip()

    return value


def case_slug(case_name: str):
    """Create a filesystem-safe case slug while keeping Hebrew and other Unicode letters readable."""
    clean = clean_entity(case_name).strip()
    clean = re.sub(r"[\\/:*?\"<>|]+", "_", clean)
    clean = re.sub(r"\s+", "_", clean)
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean or "Unassigned"


def canvas_wikilink(path: Path):
    """Return an Obsidian wikilink target for a file in the relationship folder."""
    return f"[[{path.name}]]"


def edge_confidence_color(confidence, status):
    """Legacy confidence/status edge coloring for relationships without a case."""
    status = (status or "").lower()
    confidence = (confidence or "").lower()

    if status == "rejected":
        return "6"
    if confidence == "high" or status == "confirmed":
        return "4"
    if confidence == "medium" or status == "probable":
        return "3"
    if confidence == "low" or status == "hypothesis":
        return "1"

    return "2"


def slug_id(seed: str, used_ids: set[str]):
    """Create a Canvas-safe 16-character lowercase hexadecimal id."""
    attempt = 0
    while True:
        suffix = f"::{attempt}" if attempt else ""
        candidate = hashlib.sha256((seed + suffix).encode("utf-8")).hexdigest()[:16]
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        attempt += 1


def snap(value: float):
    """Snap generated coordinates to a readable grid without touching manual positions."""
    return int(round(value / GRID_SIZE) * GRID_SIZE)


def load_existing_canvas(canvas_path: Path, warnings: list[str]):
    """Load the current Canvas if possible. Back it up if it is malformed."""
    if not canvas_path.exists():
        return {"nodes": [], "edges": []}

    try:
        canvas = json.loads(canvas_path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception as exc:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = canvas_path.with_suffix(f".invalid-{timestamp}.canvas")
        shutil.copy2(canvas_path, backup)
        warnings.append(f"Existing Canvas JSON at {canvas_path.name} could not be parsed; backup created at {backup.name}. Error: {exc}")
        return {"nodes": [], "edges": []}

    if not isinstance(canvas, dict):
        warnings.append(f"Existing Canvas root at {canvas_path.name} was not a JSON object; starting from an empty Canvas structure.")
        return {"nodes": [], "edges": []}

    nodes = canvas.get("nodes", [])
    edges = canvas.get("edges", [])

    if not isinstance(nodes, list):
        warnings.append(f"Existing Canvas nodes field at {canvas_path.name} was not a list; existing nodes could not be preserved.")
        nodes = []
    if not isinstance(edges, list):
        warnings.append(f"Existing Canvas edges field at {canvas_path.name} was not a list; existing edges ignored.")
        edges = []

    return {"nodes": nodes, "edges": edges}


def read_relationships(warnings: list[str]):
    """Read all relationship-note files from the relationships folder."""
    relationships = []

    for path in sorted(REL_DIR.glob("*.md")):
        if path.name.startswith("Relationship Edge List") or path.name.startswith("Case - ") or path.name == DASHBOARD.name:
            continue

        text = path.read_text(encoding="utf-8-sig", errors="replace")
        meta = parse_simple_yaml(text)

        if meta.get("type") != "relationship-note":
            continue

        frm = clean_entity(meta.get("from_entity", ""))
        to = clean_entity(meta.get("to_entity", ""))
        rel = str(meta.get("relationship_type", "unknown") or "unknown").strip().strip("\"")
        conf = str(meta.get("confidence", "unassessed") or "unassessed").strip()
        status = str(meta.get("status", "hypothesis") or "hypothesis").strip()
        case = clean_entity(meta.get("related_case", ""))

        if not frm or not to:
            warnings.append(f"Missing from/to in {path.name}")
            continue

        relationships.append(
            {
                "file": path,
                "from": frm,
                "to": to,
                "relationship_type": rel,
                "confidence": conf,
                "status": status,
                "case": case,
            }
        )

    return relationships


def normalize_existing_node(node: dict, used_ids: set[str]):
    """Return a copy of an existing node with minimally valid required fields."""
    clean = dict(node)
    node_id = str(clean.get("id") or "").strip()

    if not node_id or node_id in used_ids:
        node_id = slug_id(f"preserved-node::{json.dumps(clean, ensure_ascii=False, sort_keys=True)}", used_ids)
        clean["id"] = node_id
    else:
        used_ids.add(node_id)

    clean.setdefault("type", "text")
    clean.setdefault("x", 0)
    clean.setdefault("y", 0)
    clean.setdefault("width", DEFAULT_NODE_WIDTH)
    clean.setdefault("height", DEFAULT_NODE_HEIGHT)

    return clean


def is_auto_case_group(node: dict):
    """Detect generated case group/legend nodes so they can be refreshed without duplication."""
    if not isinstance(node, dict):
        return False
    if node.get("type") != "group":
        return False
    label = str(node.get("label", "")).strip()
    return label.startswith(AUTO_CASE_GROUP_PREFIX) or label == AUTO_CASE_LEGEND_LABEL


def build_case_color_map(case_names: list[str]):
    """Assign deterministic Obsidian Canvas preset colors to case names."""
    colors = {}
    for idx, name in enumerate(sorted(case_names)):
        colors[name] = CASE_COLOR_PALETTE[idx % len(CASE_COLOR_PALETTE)]
    return colors


def build_entity_color_map(relationships: list[dict], case_colors: dict[str, str]):
    """Map new entity nodes to a case color when the entity belongs to a single case."""
    cases_by_entity = defaultdict(set)
    for r in relationships:
        case = r.get("case", "")
        if not case:
            continue
        cases_by_entity[r["from"]].add(case)
        cases_by_entity[r["to"]].add(case)

    entity_colors = {}
    for entity, cases in cases_by_entity.items():
        if len(cases) == 1:
            entity_colors[entity] = case_colors.get(next(iter(cases)), DEFAULT_NODE_COLOR)
        elif len(cases) > 1:
            entity_colors[entity] = MULTI_CASE_NODE_COLOR

    return entity_colors


def build_nodes(existing_canvas: dict, entity_names: list[str], warnings: list[str], entity_colors: dict[str, str] | None = None):
    """Merge existing Canvas nodes with entities found in Relationship Notes."""
    entity_colors = entity_colors or {}
    used_ids = set()
    preserved_nodes = []
    existing_text_by_name = {}

    for raw_node in existing_canvas.get("nodes", []):
        if not isinstance(raw_node, dict):
            warnings.append("Skipped a malformed existing Canvas node because it was not a JSON object.")
            continue
        if is_auto_case_group(raw_node):
            continue

        node = normalize_existing_node(raw_node, used_ids)
        preserved_nodes.append(node)

        if node.get("type") == "text":
            name = str(node.get("text", "")).strip()
            if name and name not in existing_text_by_name:
                existing_text_by_name[name] = node

    output_nodes = []
    output_node_ids = set()
    id_by_name = {}
    new_node_count = 0
    preserved_entity_count = 0

    for name in entity_names:
        existing = existing_text_by_name.get(name)
        if existing:
            output_nodes.append(existing)
            output_node_ids.add(existing["id"])
            id_by_name[name] = existing["id"]
            preserved_entity_count += 1
            continue

        node_id = slug_id(f"entity::{name}", used_ids)
        id_by_name[name] = node_id
        output_node_ids.add(node_id)
        new_node_count += 1
        output_nodes.append(
            {
                "id": node_id,
                "type": "text",
                "text": name,
                "x": 0,
                "y": 0,
                "width": DEFAULT_NODE_WIDTH,
                "height": DEFAULT_NODE_HEIGHT,
                "color": entity_colors.get(name, DEFAULT_NODE_COLOR),
                "_new_entity_node": True,
            }
        )

    # Preserve manual or legacy nodes that are not part of the current relationship source set.
    for node in preserved_nodes:
        if node["id"] not in output_node_ids:
            output_nodes.append(node)
            output_node_ids.add(node["id"])

    assign_positions_to_new_nodes(output_nodes)

    # Remove internal marker before writing Obsidian Canvas JSON.
    for node in output_nodes:
        node.pop("_new_entity_node", None)

    stats = {
        "preserved_entity_nodes": preserved_entity_count,
        "new_entity_nodes": new_node_count,
        "total_preserved_canvas_nodes": len(preserved_nodes),
    }

    return output_nodes, id_by_name, used_ids, stats


def assign_positions_to_new_nodes(nodes: list[dict]):
    """Place only newly created entity nodes. Existing/manual coordinates are untouched."""
    new_nodes = [node for node in nodes if node.get("_new_entity_node")]
    if not new_nodes:
        return

    anchored_nodes = [node for node in nodes if not node.get("_new_entity_node") and "x" in node and "y" in node]

    if anchored_nodes:
        center_x = sum(float(node.get("x", 0)) for node in anchored_nodes) / len(anchored_nodes)
        center_y = sum(float(node.get("y", 0)) for node in anchored_nodes) / len(anchored_nodes)
        farthest = max(
            math.hypot(float(node.get("x", 0)) - center_x, float(node.get("y", 0)) - center_y)
            for node in anchored_nodes
        )
        radius = max(360, farthest + 260, 90 * len(new_nodes))
    else:
        center_x = 0
        center_y = 0
        radius = max(360, 90 * len(new_nodes))

    start_angle = 0 if len(new_nodes) == 1 else -math.pi / 2

    for idx, node in enumerate(new_nodes):
        angle = start_angle + (2 * math.pi * idx / max(1, len(new_nodes)))
        node["x"] = snap(center_x + math.cos(angle) * radius)
        node["y"] = snap(center_y + math.sin(angle) * radius)


def build_edges(
    relationships: list[dict],
    id_by_name: dict[str, str],
    used_ids: set[str],
    warnings: list[str],
    case_colors: dict[str, str] | None = None,
    include_case_in_label: bool = False,
):
    """Regenerate relationship edges from source relationship notes."""
    case_colors = case_colors or {}
    edges = []

    for idx, r in enumerate(relationships, start=1):
        from_id = id_by_name.get(r["from"])
        to_id = id_by_name.get(r["to"])

        if not from_id or not to_id:
            warnings.append(f"Could not create edge for {r['file'].name}; one or both entity nodes are missing.")
            continue

        label_parts = [r["relationship_type"]]
        if include_case_in_label and r.get("case"):
            label_parts.append(r["case"])
        label_parts.extend([r["confidence"], r["status"]])

        seed = f"edge::{r['file'].stem}::{r['from']}::{r['relationship_type']}::{r['to']}::{idx}"
        edges.append(
            {
                "id": slug_id(seed, used_ids),
                "fromNode": from_id,
                "fromSide": "right",
                "toNode": to_id,
                "toSide": "left",
                "toEnd": "arrow",
                "label": " | ".join(label_parts),
                "color": case_colors.get(r.get("case", ""), edge_confidence_color(r["confidence"], r["status"])),
            }
        )

    return edges


def case_entity_names(relationships: list[dict], case_name: str):
    """Return all entity names participating in one case."""
    names = []
    seen = set()
    for r in relationships:
        if r.get("case") != case_name:
            continue
        for name in (r["from"], r["to"]):
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def add_case_groups(nodes: list[dict], id_by_name: dict[str, str], relationships: list[dict], case_colors: dict[str, str], used_ids: set[str]):
    """Add refreshed visual group nodes for each case based on the current node positions."""
    groups = []
    node_by_id = {node.get("id"): node for node in nodes if isinstance(node, dict)}
    cases = sorted({r.get("case", "") for r in relationships if r.get("case", "")})

    for case_name in cases:
        case_nodes = []
        for entity_name in case_entity_names(relationships, case_name):
            node_id = id_by_name.get(entity_name)
            node = node_by_id.get(node_id)
            if node and node.get("type") == "text":
                case_nodes.append(node)

        if not case_nodes:
            continue

        min_x = min(float(node.get("x", 0)) for node in case_nodes)
        min_y = min(float(node.get("y", 0)) for node in case_nodes)
        max_x = max(float(node.get("x", 0)) + float(node.get("width", DEFAULT_NODE_WIDTH)) for node in case_nodes)
        max_y = max(float(node.get("y", 0)) + float(node.get("height", DEFAULT_NODE_HEIGHT)) for node in case_nodes)

        groups.append(
            {
                "id": slug_id(f"case-group::{case_name}", used_ids),
                "type": "group",
                "label": f"{AUTO_CASE_GROUP_PREFIX}{case_name}",
                "x": snap(min_x - GROUP_MARGIN),
                "y": snap(min_y - GROUP_MARGIN),
                "width": max(DEFAULT_NODE_WIDTH, snap(max_x - min_x + (GROUP_MARGIN * 2))),
                "height": max(DEFAULT_NODE_HEIGHT, snap(max_y - min_y + (GROUP_MARGIN * 2))),
                "color": case_colors.get(case_name, DEFAULT_NODE_COLOR),
            }
        )

    legend_y = snap(max((float(node.get("y", 0)) + float(node.get("height", DEFAULT_NODE_HEIGHT)) for node in nodes), default=0) + 260)
    legend_lines = [f"{name}: color {case_colors.get(name, DEFAULT_NODE_COLOR)}" for name in cases]
    if legend_lines:
        groups.append(
            {
                "id": slug_id("case-legend", used_ids),
                "type": "group",
                "label": AUTO_CASE_LEGEND_LABEL,
                "x": -420,
                "y": legend_y,
                "width": 360,
                "height": max(120, 42 * len(legend_lines) + 80),
                "color": "5",
            }
        )

    return groups + nodes


def markdown_cell(value):
    """Escape values so the generated Markdown edge list remains table-safe."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def write_edge_list(relationships: list[dict], edge_list_path: Path, warnings: list[str], title: str):
    rows = [
        "| From | Relationship | To | Status | Confidence | Case | Source note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for r in relationships:
        note = r["file"].stem
        rows.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(r["from"]),
                    markdown_cell(r["relationship_type"]),
                    markdown_cell(r["to"]),
                    markdown_cell(r["status"]),
                    markdown_cell(r["confidence"]),
                    markdown_cell(r["case"]),
                    f"[[{markdown_cell(note)}]]",
                ]
            )
            + " |"
        )

    if warnings:
        rows.append("")
        rows.append("## Warnings")
        for w in warnings:
            rows.append(f"- {w}")

    content = (
        "---\n"
        "type: relationship-edge-list\n"
        "status: generated\n"
        "tags:\n"
        "  - osint/relationships\n"
        "  - osint/canvas\n"
        "---\n\n"
        f"# {title}\n\n"
        "> [!info]\n"
        "> This file is regenerated by the automatic Canvas generator. Relationship Notes remain the source of truth.\n\n"
        + "\n".join(rows)
        + "\n"
    )

    edge_list_path.write_text(content, encoding="utf-8")


def generate_canvas_for_relationships(
    relationships: list[dict],
    output_canvas_path: Path,
    output_edge_list_path: Path,
    all_warnings: list[str],
    case_colors: dict[str, str],
    include_case_groups: bool,
    include_case_in_edge_label: bool,
    edge_list_title: str,
):
    warnings = []
    existing_canvas = load_existing_canvas(output_canvas_path, warnings)

    entity_names = []
    seen_entities = set()
    for r in relationships:
        for name in (r["from"], r["to"]):
            if name not in seen_entities:
                seen_entities.add(name)
                entity_names.append(name)

    entity_colors = build_entity_color_map(relationships, case_colors)
    nodes, id_by_name, used_ids, node_stats = build_nodes(existing_canvas, entity_names, warnings, entity_colors=entity_colors)
    edges = build_edges(relationships, id_by_name, used_ids, warnings, case_colors=case_colors, include_case_in_label=include_case_in_edge_label)

    if include_case_groups:
        nodes = add_case_groups(nodes, id_by_name, relationships, case_colors, used_ids)

    canvas = {"nodes": nodes, "edges": edges}
    output_canvas_path.write_text(json.dumps(canvas, ensure_ascii=False, indent=2), encoding="utf-8")
    write_edge_list(relationships, output_edge_list_path, warnings, edge_list_title)
    all_warnings.extend(warnings)

    return {
        "status": "ok",
        "nodes": len(nodes),
        "relationships": len(relationships),
        "relationship_entity_nodes": len(entity_names),
        "new_entity_nodes": node_stats["new_entity_nodes"],
        "preserved_entity_nodes": node_stats["preserved_entity_nodes"],
        "preserved_canvas_nodes_before_merge": node_stats["total_preserved_canvas_nodes"],
        "edges": len(edges),
        "warnings": warnings,
        "output": str(output_canvas_path),
        "edge_list": str(output_edge_list_path),
    }


def write_dashboard(global_result: dict, case_results: dict[str, dict], case_counts: dict[str, dict], case_colors: dict[str, str], warnings: list[str]):
    """Write a central Obsidian dashboard for choosing which relationship map to open."""
    updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = [
        "| Case | Canvas | Edge List | Relationships | Entities | Color |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]

    for case_name in sorted(case_results):
        result = case_results[case_name]
        counts = case_counts.get(case_name, {"relationships": 0, "entities": 0})
        canvas_path = Path(result["output"])
        edge_list_path = Path(result["edge_list"])
        rows.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(case_name),
                    canvas_wikilink(canvas_path),
                    canvas_wikilink(edge_list_path),
                    str(counts["relationships"]),
                    str(counts["entities"]),
                    f"color {case_colors.get(case_name, DEFAULT_NODE_COLOR)}",
                ]
            )
            + " |"
        )

    warning_block = ""
    if warnings:
        warning_lines = "\n".join(f"> - {markdown_cell(w)}" for w in warnings)
        warning_block = f"\n> [!warning] Generator Warnings\n{warning_lines}\n"

    content = (
        "---\n"
        "type: relationship-map-dashboard\n"
        "status: generated\n"
        "updated: \"" + updated + "\"\n"
        "tags:\n"
        "  - osint/relationships\n"
        "  - osint/canvas\n"
        "  - osint/dashboard\n"
        "---\n\n"
        "# Relationship Map Dashboard\n\n"
        "> [!info]\n"
        "> This dashboard is regenerated by the automatic Canvas generator. Use it as the central entry point for choosing which relationship map to view.\n\n"
        "## Open the Global Map\n\n"
        f"| View | File | Relationships | Entities | Nodes | Edges |\n"
        f"| --- | --- | ---: | ---: | ---: | ---: |\n"
        f"| Global relationship map | {canvas_wikilink(Path(global_result['output']))} | {global_result['relationships']} | {global_result['relationship_entity_nodes']} | {global_result['nodes']} | {global_result['edges']} |\n\n"
        "## Open a Case-Specific Map\n\n"
        + "\n".join(rows)
        + "\n\n"
        "## Practical Use\n\n"
        "Open `Auto Relationship Map.canvas` only when you need the full cross-case overview. For focused analysis, open the case-specific Canvas from the table above. Each case Canvas shows only the relationships whose `related_case` field matches that case.\n\n"
        "The global map also contains automatic case group boxes and case-colored edges. These are visual aids only; the authoritative filtering is performed by opening the dedicated case Canvas.\n"
        + warning_block
    )

    DASHBOARD.write_text(content, encoding="utf-8")


def count_case_entities(case_relationships: list[dict]):
    entities = set()
    for r in case_relationships:
        entities.add(r["from"])
        entities.add(r["to"])
    return len(entities)


def main():
    REL_DIR.mkdir(parents=True, exist_ok=True)
    all_warnings = []

    all_relationships = read_relationships(all_warnings)

    relationships_by_case = defaultdict(list)
    for r in all_relationships:
        if r["case"]:
            relationships_by_case[r["case"]].append(r)

    case_colors = build_case_color_map(list(relationships_by_case.keys()))

    # Generate global map.
    global_canvas_path = REL_DIR / "Auto Relationship Map.canvas"
    global_edge_list_path = REL_DIR / "Relationship Edge List.md"
    global_results = generate_canvas_for_relationships(
        all_relationships,
        global_canvas_path,
        global_edge_list_path,
        all_warnings,
        case_colors=case_colors,
        include_case_groups=True,
        include_case_in_edge_label=True,
        edge_list_title="Relationship Edge List",
    )

    # Generate one Canvas and one edge list per case.
    case_results = {}
    case_counts = {}
    for case_name, case_relationships in sorted(relationships_by_case.items()):
        slug = case_slug(case_name)
        case_canvas_path = REL_DIR / f"Case - {slug} Relationship Map.canvas"
        case_edge_list_path = REL_DIR / f"Case - {slug} Relationship Edge List.md"
        case_results[case_name] = generate_canvas_for_relationships(
            case_relationships,
            case_canvas_path,
            case_edge_list_path,
            all_warnings,
            case_colors=case_colors,
            include_case_groups=True,
            include_case_in_edge_label=False,
            edge_list_title=f"{case_name} Relationship Edge List",
        )
        case_counts[case_name] = {
            "relationships": len(case_relationships),
            "entities": count_case_entities(case_relationships),
        }

    write_dashboard(global_results, case_results, case_counts, case_colors, all_warnings)

    final_output = {
        "status": "ok",
        "dashboard": str(DASHBOARD),
        "global_map": global_results,
        "case_maps": case_results,
        "case_colors": case_colors,
        "total_warnings": all_warnings,
    }

    print(json.dumps(final_output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
