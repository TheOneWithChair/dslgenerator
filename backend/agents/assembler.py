import json
import os
import logging
from typing import Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from state import AgentState

logger = logging.getLogger("agent.assembler")

ASSEMBLER_SYSTEM = """You are a Dify DSL YAML assembler. You write EXACTLY valid Dify DSL YAML.

You receive:
- A node manifest (IDs, types, config hints, variable flow)
- Exact schema for each node type used
- Edge rules and layout rules
- App header template

CRITICAL RULES — violating any of these will cause Dify import to fail:

=== APP HEADER ===
Use the header template exactly. Do not add or remove fields.

=== NODE WRAPPER — every node must have ALL of these ===
  id: "{node_id_from_manifest}"
  type: custom                    ← always "custom", not the node type
  sourcePosition: right
  targetPosition: left
  position:
    x: {column_index * 300 + 80}
    y: 282
  data:
    type: {block_type}            ← "start","llm","end","answer" etc
    title: "{title}"
    desc: "{desc}"
    ... node-specific fields ...

=== EDGE FORMAT — exact format, no deviations ===
Standard edge:
  id: "{source_id}-source-{target_id}-target"
  source: "{source_id}"
  sourceHandle: source
  target: "{target_id}"
  targetHandle: target
  type: custom
  data:
    sourceType: {source_block_type}
    targetType: {target_block_type}
    isInIteration: false
    isInLoop: false
  zIndex: 0

If-else TRUE branch edge:
  id: "{ifelse_id}-true-{target_id}-target"
  source: "{ifelse_id}"
  sourceHandle: "true"            ← NOT "source"
  target: "{target_id}"
  targetHandle: target
  type: custom
  data:
    sourceType: if-else
    targetType: {target_block_type}
    isInIteration: false
    isInLoop: false
  zIndex: 0

=== VARIABLE REFERENCES ===
CRITICAL: You MUST use exact Dify syntax for references. Plain variables like {{content}} will FAIL.
In prompt_template text: {{#node_id.output_key#}}
In value_selector arrays: ["node_id", "output_key"]
In answer field: {{#node_id.output_key#}}
CRITICAL: All Start node variables MUST have `required: true`.

=== LAYOUT ===
x = 80 + (column_index * 300)
y = 282 for linear flow
y = 100 for if-else true branch, y = 460 for false branch

=== VIEWPORT ===
Always end graph with:
    viewport:
      x: 0
      y: 0
      zoom: 0.7

Output ONLY the YAML. No markdown fences. No explanation. No comments except # CUSTOMIZE markers.
"""

def assembler_node(state: AgentState) -> Dict[str, Any]:
    """
    LangGraph Stage 4: Assembler Agent node.
    """
    logger.info("--- STAGE 4: ASSEMBLER AGENT ---")
    state["attempt"] += 1
    
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("MODEL", "gemini-flash-latest"),
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0.0
    )
    
    sections = []
    sections.append("=== NODE MANIFEST ===")
    sections.append(json.dumps(state["manifest"], indent=2))

    sections.append("\n=== NODE SCHEMAS (use ONLY these fields) ===")
    for node_type, schema in state["enriched_schemas"].items():
        sections.append(f"\n--- {node_type} schema ---")
        sections.append(schema)

    sections.append("\n=== EDGE RULES ===")
    sections.append(state["edge_rules"])

    sections.append("\n=== LAYOUT RULES ===")
    sections.append(state["layout_rules"])

    sections.append("\n=== APP HEADER TEMPLATE ===")
    sections.append(state["app_header_template"])

    # If this is a retry, include the errors
    if state["errors"]:
        sections.append("\n=== PREVIOUS ATTEMPT ERRORS — FIX THESE ===")
        for err in state["errors"]:
            sections.append(f"  - {err}")
        sections.append("\n=== PREVIOUS YAML (fix the errors above) ===")
        sections.append(state["yaml_str"] or "")
        sections.append("\nNow output the CORRECTED full YAML:")
    else:
        sections.append("\nNow output the complete Dify DSL YAML:")

    user_message = "\n".join(sections)
    
    logger.info(f"Assembler: Prompt constructed ({len(user_message)} chars). Invoking LLM...")
    import time
    start_time = time.time()
    
    messages = [
        SystemMessage(content=ASSEMBLER_SYSTEM),
        HumanMessage(content=user_message)
    ]
    
    try:
        response = llm.invoke(messages)
        elapsed = time.time() - start_time
        raw = response.content.strip()
        logger.info(f"Assembler: LLM response received in {elapsed:.2f}s ({len(raw)} chars).")
    except Exception as e:
        logger.error(f"Assembler: LLM call failed: {e}")
        raise
    
    # Strip markdown fences
    raw = raw.replace("```yaml", "").replace("```", "").strip()
    
    return {
        "yaml_str": raw,
        "steps_log": [f"Stage 4: Assembled YAML (Attempt {state['attempt']})."]
    }
    return raw