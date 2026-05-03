"""
validator.py — Pure Python DSL validator. No LLM. Fast, deterministic.
"""
import re
import yaml
import logging


from typing import Dict, Any
from state import AgentState

def validator_node(state: AgentState) -> Dict[str, Any]:
    """
    LangGraph Stage 5: Validator + Feedback loop node.
    """
    from validator import validate_dsl # Local import to avoid circular dependency if any
    
    logger = logging.getLogger("agent.validator")
    logger.info("--- STAGE 5: VALIDATOR ---")
    
    result = validate_dsl(state["yaml_str"], state["manifest"])
    
    if result["valid"]:
        return {
            "errors": [],
            "done": True,
            "steps_log": ["Stage 5: Validation PASSED."]
        }
    else:
        return {
            "errors": result["errors"],
            "done": False,
            "steps_log": [f"Stage 5: Validation FAILED with {len(result['errors'])} errors."]
        }

def validate_dsl(yaml_str: str, manifest: dict) -> dict:
    """
    Validate a Dify DSL YAML string.
    
    Returns:
        {"valid": True, "errors": []} on success
        {"valid": False, "errors": ["error1", "error2"]} on failure
    """
    errors = []

    # --- Check 1: YAML parses cleanly ---
    try:
        dsl = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        return {"valid": False, "errors": [f"YAML parse error: {e}"]}

    if not isinstance(dsl, dict):
        return {"valid": False, "errors": ["DSL root is not a dict"]}

    # --- Check 2: Top-level structure ---
    for required_key in ["version", "kind", "app", "workflow"]:
        if required_key not in dsl:
            errors.append(f"Missing top-level key: '{required_key}'")

    if errors:
        return {"valid": False, "errors": errors}

    # --- Extract graph ---
    workflow = dsl.get("workflow", {})
    graph = workflow.get("graph", {})
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if not nodes:
        return {"valid": False, "errors": ["No nodes found in graph"]}

    # --- Build lookup tables ---
    node_ids = set()
    node_by_id = {}
    node_types_by_id = {}

    for node in nodes:
        nid = node.get("id")
        if not nid:
            errors.append("A node is missing its 'id' field")
            continue
        if nid in node_ids:
            errors.append(f"Duplicate node ID: '{nid}'")
        node_ids.add(nid)
        node_by_id[nid] = node
        node_types_by_id[nid] = node.get("data", {}).get("type", "")

    # --- Check 3: App mode vs terminal node type ---
    app_mode = dsl.get("app", {}).get("mode", "")
    node_data_types = [node.get("data", {}).get("type", "") for node in nodes]

    if app_mode == "workflow":
        if "answer" in node_data_types:
            errors.append("workflow mode cannot have 'answer' nodes — use 'end' instead")
        if "end" not in node_data_types:
            errors.append("workflow mode must have at least one 'end' node")
    elif app_mode in ("chat", "agent-chat", "advanced-chat"):
        if "end" in node_data_types:
            errors.append(f"{app_mode} mode cannot have 'end' nodes — use 'answer' instead")
        if "answer" not in node_data_types:
            errors.append(f"{app_mode} mode must have at least one 'answer' node")

    # --- Check 4: Required node wrapper fields ---
    for node in nodes:
        nid = node.get("id", "UNKNOWN")
        if node.get("type") != "custom":
            errors.append(f"Node '{nid}': wrapper type must be 'custom', got '{node.get('type')}'")
        if "sourcePosition" not in node:
            errors.append(f"Node '{nid}': missing 'sourcePosition'")
        if "targetPosition" not in node:
            errors.append(f"Node '{nid}': missing 'targetPosition'")
        if "position" not in node:
            errors.append(f"Node '{nid}': missing 'position'")

        data = node.get("data", {})
        if not data.get("type"):
            errors.append(f"Node '{nid}': missing data.type")
        if "title" not in data:
            errors.append(f"Node '{nid}': missing data.title")
        if "desc" not in data:
            errors.append(f"Node '{nid}': missing data.desc")

    # --- Check 5: Edge references ---
    for edge in edges:
        eid = edge.get("id", "UNKNOWN")
        src = edge.get("source")
        tgt = edge.get("target")

        if src not in node_ids:
            errors.append(f"Edge '{eid}': source '{src}' not found in nodes")
        if tgt not in node_ids:
            errors.append(f"Edge '{eid}': target '{tgt}' not found in nodes")

        # Check if-else edges use correct sourceHandle
        src_type = node_types_by_id.get(src, "")
        src_handle = edge.get("sourceHandle", "")
        if src_type == "if-else" and src_handle not in ("true", "false"):
            errors.append(f"Edge '{eid}': if-else source must use sourceHandle 'true' or 'false', got '{src_handle}'")
        if src_type != "if-else" and src_handle not in ("source", ""):
            errors.append(f"Edge '{eid}': non-if-else node must use sourceHandle 'source'")

        # Check edge data fields
        edge_data = edge.get("data", {})
        if "sourceType" not in edge_data:
            errors.append(f"Edge '{eid}': missing data.sourceType")
        if "targetType" not in edge_data:
            errors.append(f"Edge '{eid}': missing data.targetType")

    # --- Check 6: Variable references in YAML text ---
    yaml_text = yaml_str
    var_refs = re.findall(r'\{\{#([^.#]+)\.[^#]+#\}\}', yaml_text)
    for ref_node_id in var_refs:
        if ref_node_id not in node_ids:
            errors.append(f"Variable reference {{{{#{ref_node_id}.*#}}}} — node '{ref_node_id}' not found")

    # --- Check 7: value_selector arrays ---
    for node in nodes:
        nid = node.get("id", "UNKNOWN")
        data = node.get("data", {})

        # Check outputs value_selectors
        for output in data.get("outputs", []):
            sel = output.get("value_selector", [])
            if sel and sel[0] not in node_ids:
                errors.append(f"Node '{nid}' output value_selector: '{sel[0]}' not found")

        # Check LLM context variable_selector
        ctx = data.get("context", {})
        ctx_sel = ctx.get("variable_selector", [])
        if ctx_sel and ctx_sel[0] not in node_ids:
            errors.append(f"Node '{nid}' context.variable_selector: '{ctx_sel[0]}' not found")

    # --- Check 8: Node-specific required fields ---
    for node in nodes:
        nid = node.get("id", "UNKNOWN")
        data = node.get("data", {})
        ntype = data.get("type", "")

        if ntype == "llm":
            if not data.get("prompt_template"):
                errors.append(f"LLM node '{nid}': prompt_template is empty")
            model = data.get("model", {})
            if not model.get("mode"):
                errors.append(f"LLM node '{nid}': model.mode is missing")

        elif ntype == "answer":
            if not data.get("answer"):
                errors.append(f"Answer node '{nid}': answer field is empty")

        elif ntype == "code":
            if not data.get("code"):
                errors.append(f"Code node '{nid}': code field is empty")
            if not data.get("code_language"):
                errors.append(f"Code node '{nid}': code_language is missing")

        elif ntype == "knowledge-retrieval":
            if not data.get("query_variable_selector"):
                errors.append(f"Knowledge retrieval node '{nid}': query_variable_selector is missing")

    # --- Check 9: Connectivity (no orphan nodes) ---
    nodes_with_outgoing = {e["source"] for e in edges if "source" in e}
    nodes_with_incoming = {e["target"] for e in edges if "target" in e}

    for node in nodes:
        nid = node.get("id", "UNKNOWN")
        ntype = node.get("data", {}).get("type", "")

        if ntype != "start" and nid not in nodes_with_incoming:
            errors.append(f"Node '{nid}' ({ntype}): no incoming edge (orphan)")
        if ntype not in ("end", "answer") and nid not in nodes_with_outgoing:
            errors.append(f"Node '{nid}' ({ntype}): no outgoing edge (dead end)")

    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "errors": []}