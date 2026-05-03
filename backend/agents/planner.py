"""
agents/planner.py
Takes the intake brief and produces a node manifest JSON with UUIDs.
No YAML written here — only the plan.
"""
import json
import os
import uuid
import google.generativeai as genai
from dotenv import load_dotenv
import logging

logger = logging.getLogger("agent.planner")

load_dotenv(override=True)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = os.getenv("MODEL", "gemini-flash-latest")


PLANNER_SYSTEM = """You are a Dify DSL planner. Given a workflow brief, you produce 
a precise node manifest JSON. You NEVER write YAML — only a planning JSON.

Critical rules:
1. Generate real UUID v4 format for every node ID (e.g. "a1b2c3d4-1a2b-4c3d-8e5f-1a2b3c4d5e6f")
2. First node is ALWAYS type "start"
3. Mode rules:
   - workflow mode → last node must be type "end", NEVER "answer"
   - chat/agent-chat/advanced-chat → last node must be type "answer", NEVER "end"
4. Every edge must reference node IDs you defined in this manifest
5. Variable references format: ["source_node_id", "output_key"]
6. Only use node types from the available list
7. if-else nodes have TWO outgoing edges: one with branch "true", one with "false"
8. CRITICAL: Start node variables MUST have "required": true.
9. CRITICAL: LLM prompt templates MUST map variables using the exact Dify syntax: {{#source_node_id.output_key#}} (e.g. {{#start_id.content#}}). Do NOT use plain {{content}}.

Available node types: {node_types}

Output ONLY valid JSON, no markdown, no explanation:
{{
  "app_mode": "workflow|chat|agent-chat|advanced-chat",
  "app_name": "...",
  "description": "...",
  "nodes": [
    {{
      "id": "uuid-here",
      "type": "start",
      "title": "Start",
      "desc": "",
      "config_hints": {{
        "variables": [
          {{"variable": "key", "label": "Label", "type": "text-input", "required": true}}
        ]
      }}
    }},
    {{
      "id": "uuid-here",
      "type": "llm",
      "title": "Node Title",
      "desc": "what this node does",
      "config_hints": {{
        "system_prompt": "...",
        "user_prompt_template": "uses {{#prev_node_id.output_key#}} (MUST USE THIS EXACT SYNTAX)",
        "temperature": 0.7
      }}
    }}
  ],
  "edges": [
    {{
      "id": "source_id-source-target_id-target",
      "from_id": "source_node_id",
      "to_id": "target_node_id",
      "from_type": "start",
      "to_type": "llm",
      "branch": null
    }}
  ],
  "variable_flow": [
    {{
      "from_node_id": "uuid",
      "from_output_key": "text",
      "to_node_id": "uuid",
      "to_field": "prompt_template"
    }}
  ]
}}

For if-else edges, set branch to "true" or "false".
Edge id format: "{{from_id}}-source-{{to_id}}-target"
For if-else: "{{ifelse_id}}-true-{{target_id}}-target" or "{{ifelse_id}}-false-{{target_id}}-target"
"""


def run_planner(brief: dict, node_types: list) -> dict:
    """
    Takes the intake brief, returns a node manifest JSON.
    
    Args:
        brief: The structured brief from the intake agent
        node_types: Available node types from knowledge store
    
    Returns:
        Manifest dict with nodes, edges, variable_flow
    """
    logger.info("Initializing Planner Agent...")
    system = PLANNER_SYSTEM.format(node_types=", ".join(node_types))

    user_message = f"""Plan a Dify DSL for this brief:

{json.dumps(brief, indent=2)}

Generate the complete node manifest JSON now."""

    logger.info("Sending brief to Planner Agent model...")
    model = genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=system,
    )

    response = model.generate_content(user_message)
    logger.info("Received response from Planner Agent model.")

    raw = response.text.strip()
    clean = raw.replace("```json", "").replace("```", "").strip()

    try:
        manifest = json.loads(clean)
        # Validate basic structure
        assert "nodes" in manifest, "Missing nodes"
        assert "edges" in manifest, "Missing edges"
        assert len(manifest["nodes"]) >= 2, "Need at least 2 nodes"
        return manifest
    except (json.JSONDecodeError, AssertionError) as e:
        raise ValueError(f"Planner returned invalid manifest: {e}\nRaw: {raw}")