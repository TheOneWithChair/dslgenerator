"""
parser.py — Run once to build knowledge_store.json from nodestemplateslayout.txt
Usage: python backend/parser.py
"""
import json
import re
from pathlib import Path

def parse_knowledge_file(input_path: str, output_path: str):
    raw = Path(input_path).read_text(encoding="utf-8")
    store = {
        "node_schemas": {},
        "edge_rules": "",
        "layout_rules": "",
        "app_header": {},
        "validation_rules": "",
        "examples": {},
        "node_types": []
    }

    # --- Parse node schemas ---
    node_blocks = re.findall(
        r'>>>NODE_START:(\w[\w-]*)\n(.*?)>>>NODE_END:\1',
        raw, re.DOTALL
    )
    for node_type, content in node_blocks:
        store["node_schemas"][node_type] = content.strip()

    store["node_types"] = list(store["node_schemas"].keys())

    # --- Parse edge rules ---
    edge_match = re.search(r'>>>EDGE_RULES_START\n(.*?)>>>EDGE_RULES_END', raw, re.DOTALL)
    if edge_match:
        store["edge_rules"] = edge_match.group(1).strip()

    # --- Parse layout rules ---
    layout_match = re.search(r'>>>LAYOUT_RULES_START\n(.*?)>>>LAYOUT_RULES_END', raw, re.DOTALL)
    if layout_match:
        store["layout_rules"] = layout_match.group(1).strip()

    # --- Parse app header ---
    header_match = re.search(r'>>>APP_HEADER_START\n(.*?)>>>APP_HEADER_END', raw, re.DOTALL)
    if header_match:
        header_content = header_match.group(1).strip()
        # Split workflow vs chat header
        wf_match = re.search(r'WORKFLOW_MODE_HEADER:\n(.*?)(?=CHATFLOW_MODE_HEADER:|MODE_SELECTION_RULES:)', header_content, re.DOTALL)
        chat_match = re.search(r'CHATFLOW_MODE_HEADER:\n(.*?)(?=MODE_SELECTION_RULES:|$)', header_content, re.DOTALL)
        rules_match = re.search(r'MODE_SELECTION_RULES:\n(.*?)$', header_content, re.DOTALL)

        store["app_header"]["workflow"] = wf_match.group(1).strip() if wf_match else ""
        store["app_header"]["chat"] = chat_match.group(1).strip() if chat_match else ""
        store["app_header"]["mode_rules"] = rules_match.group(1).strip() if rules_match else ""

    # --- Parse validation rules ---
    val_match = re.search(r'>>>VALIDATION_RULES_START\n(.*?)>>>VALIDATION_RULES_END', raw, re.DOTALL)
    if val_match:
        store["validation_rules"] = val_match.group(1).strip()

    # --- Parse examples ---
    example_blocks = re.findall(
        r'>>>EXAMPLE_START:(\w+)\n(.*?)>>>EXAMPLE_END:\1',
        raw, re.DOTALL
    )
    for name, content in example_blocks:
        store["examples"][name] = content.strip()

    # Write output
    Path(output_path).write_text(json.dumps(store, indent=2), encoding="utf-8")

    # Print summary
    print("✅ knowledge_store.json built successfully")
    print(f"   Node types: {store['node_types']}")
    print(f"   Examples: {list(store['examples'].keys())}")
    print(f"   Edge rules: {'✓' if store['edge_rules'] else '✗'}")
    print(f"   Layout rules: {'✓' if store['layout_rules'] else '✗'}")
    print(f"   App headers: {list(store['app_header'].keys())}")
    print(f"   Validation rules: {'✓' if store['validation_rules'] else '✗'}")
    return store


if __name__ == "__main__":
    base = Path(__file__).parent.parent
    input_file = base / "knowledge" / "nodestemplateslayout.txt"
    output_file = base / "knowledge" / "knowledge_store.json"
    parse_knowledge_file(str(input_file), str(output_file))