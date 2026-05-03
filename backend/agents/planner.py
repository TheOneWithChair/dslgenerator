import json
import os
import logging
from typing import Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from state import AgentState

logger = logging.getLogger("agent.planner")

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

def planner_node(state: AgentState) -> Dict[str, Any]:
    """
    LangGraph Stage 2: Planner Agent node.
    """
    logger.info("--- STAGE 2: PLANNER AGENT ---")
    
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("MODEL", "gemini-flash-latest"),
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0.0 # High precision needed
    )
    
    system_prompt = PLANNER_SYSTEM.format(node_types=", ".join(state["node_types"]))
    user_content = f"Plan a Dify DSL for this brief:\n\n{json.dumps(state['brief'], indent=2)}"
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content)
    ]
    
    response = llm.invoke(messages)
    raw = response.content.strip()
    clean = raw.replace("```json", "").replace("```", "").strip()
    
    try:
        manifest = json.loads(clean)
        # Validate basic structure
        assert "nodes" in manifest, "Missing nodes"
        assert "edges" in manifest, "Missing edges"
        
        return {
            "manifest": manifest,
            "steps_log": [f"Stage 2: Planned {len(manifest.get('nodes', []))} nodes."]
        }
    except (json.JSONDecodeError, AssertionError) as e:
        logger.error(f"Planner failed: {e}")
        raise ValueError(f"Planner returned invalid JSON: {e}")