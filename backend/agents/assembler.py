"""
agents/assembler.py
Takes the manifest + fetched schemas and writes the final YAML.
This is the ONLY agent that outputs YAML.
"""
import json
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(override=True)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = os.getenv("MODEL", "gemini-flash-latest")


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


def run_assembler(
    manifest: dict,
    enriched_schemas: dict,
    edge_rules: str,
    layout_rules: str,
    app_header_template: str,
    previous_errors: list = None,
    previous_yaml: str = None
) -> str:
    """
    Assembles the final YAML from the manifest and schemas.
    
    Args:
        manifest: Node manifest from planner
        enriched_schemas: {node_type: schema_text} for each node used
        edge_rules: Edge format rules from knowledge store
        layout_rules: Layout rules from knowledge store
        app_header_template: App header template for the mode
        previous_errors: Errors from previous validation attempt (for retry)
        previous_yaml: Previous YAML output (for retry)
    
    Returns:
        Raw YAML string
    """
    # Build the user message
    sections = []

    sections.append("=== NODE MANIFEST ===")
    sections.append(json.dumps(manifest, indent=2))

    sections.append("\n=== NODE SCHEMAS (use ONLY these fields) ===")
    for node_type, schema in enriched_schemas.items():
        sections.append(f"\n--- {node_type} schema ---")
        sections.append(schema)

    sections.append("\n=== EDGE RULES ===")
    sections.append(edge_rules)

    sections.append("\n=== LAYOUT RULES ===")
    sections.append(layout_rules)

    sections.append("\n=== APP HEADER TEMPLATE ===")
    sections.append(app_header_template)

    # If this is a retry, include the errors
    if previous_errors:
        sections.append("\n=== PREVIOUS ATTEMPT ERRORS — FIX THESE ===")
        for err in previous_errors:
            sections.append(f"  - {err}")
        sections.append("\n=== PREVIOUS YAML (fix the errors above) ===")
        sections.append(previous_yaml or "")
        sections.append("\nNow output the CORRECTED full YAML:")
    else:
        sections.append("\nNow output the complete Dify DSL YAML:")

    user_message = "\n".join(sections)

    model = genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=ASSEMBLER_SYSTEM,
    )

    response = model.generate_content(
        user_message,
        generation_config=genai.types.GenerationConfig(max_output_tokens=4000),
    )

    raw = response.text.strip()

    # Strip markdown fences if LLM added them
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.replace("```yaml", "").replace("```", "").strip()

    return raw