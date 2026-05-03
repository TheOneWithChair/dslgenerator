"""
backend/main.py — FastAPI orchestrator
Run with: uvicorn backend.main:app --reload --port 8001
"""
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("orchestrator")

load_dotenv(override=True)
print("\n--- Dify DSL Generator Backend Starting ---")
logger.info("Initializing Dify DSL Generator Backend...")

# Ensure backend/ is on sys.path so `agents` and `validator` can be imported
# regardless of where uvicorn is launched from.
_BACKEND_DIR = Path(__file__).parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from validator import validate_dsl
from graph import build_dsl_workflow

# Compile LangGraph workflow once at startup
dsl_workflow = build_dsl_workflow()

app = FastAPI(title="Dify DSL Generator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Load knowledge store ---
STORE_PATH = Path(__file__).parent.parent / "knowledge" / "knowledge_store.json"

def load_store() -> dict:
    if not STORE_PATH.exists():
        raise RuntimeError(
            "knowledge_store.json not found. "
            "Run: python backend/parser.py"
        )
    return json.loads(STORE_PATH.read_text())

store = load_store()
print(f"✅ Knowledge store loaded. {len(store['node_types'])} node types available.")
logger.info("Knowledge store loaded successfully.")


# ─── Request/Response Models ────────────────────────────────────────────────

class IntakeRequest(BaseModel):
    conversation: List[dict]      # [{"role": "user"|"assistant", "content": str}]

class PlanRequest(BaseModel):
    brief: dict

class AssembleRequest(BaseModel):
    manifest: dict
    previous_errors: Optional[List[str]] = None
    previous_yaml: Optional[str] = None

class ValidateRequest(BaseModel):
    yaml_str: str
    manifest: dict

class GenerateRequest(BaseModel):
    conversation: List[dict]      # full conversation including final brief answers


# ─── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "node_types": store["node_types"]}


@app.get("/node-types")
def get_node_types():
    """Returns all available node types."""
    return {"node_types": store["node_types"]}


@app.get("/schema/{node_type}")
def get_schema(node_type: str):
    """Returns schema for a single node type."""
    schema = store["node_schemas"].get(node_type)
    if not schema:
        raise HTTPException(404, f"Unknown node type: {node_type}")
    return {"node_type": node_type, "schema": schema}


@app.post("/intake")
def intake(req: IntakeRequest):
    """
    One turn of the intake agent using the LangGraph node logic.
    """
    logger.info(f"==> /intake endpoint called with {len(req.conversation)} conversation turns.")
    
    # Run the intake node logic
    state = {
        "conversation": req.conversation,
        "node_types": store["node_types"],
        "brief": None,
        "intake_question": None,
        "steps_log": []
    }
    
    from agents.intake import intake_node
    result_state = intake_node(state)
    
    if result_state.get("brief"):
        return result_state["brief"]
    else:
        return {"ready": False, "question": result_state.get("intake_question")}


@app.post("/plan")
def plan(req: PlanRequest):
    """
    Runs the planner agent node on a completed brief.
    """
    logger.info("==> /plan endpoint called. Starting Planner Agent node...")
    
    state = {
        "brief": req.brief,
        "node_types": store["node_types"],
        "steps_log": []
    }
    
    from agents.planner import planner_node
    result_state = planner_node(state)
    
    return {"manifest": result_state["manifest"]}


@app.post("/assemble")
def assemble(req: AssembleRequest):
    """
    Assembles YAML using the Assembler node logic.
    """
    logger.info("==> /assemble endpoint called. Starting Assembler Agent node...")
    
    # 1. Run Stage 3 logic (Schema fetching)
    from mcp_layer import schema_fetcher_node
    schema_state = schema_fetcher_node({
        "manifest": req.manifest,
        "store": store,
        "steps_log": []
    })
    
    # 2. Run Stage 4 logic (Assembling)
    from agents.assembler import assembler_node
    assembler_state = assembler_node({
        "manifest": req.manifest,
        "enriched_schemas": schema_state["enriched_schemas"],
        "edge_rules": schema_state["edge_rules"],
        "layout_rules": schema_state["layout_rules"],
        "app_header_template": schema_state["app_header_template"],
        "errors": req.previous_errors,
        "yaml_str": req.previous_yaml,
        "attempt": 0,
        "steps_log": []
    })
    
    return {"yaml": assembler_state["yaml_str"]}


@app.post("/validate")
def validate(req: ValidateRequest):
    """
    Validates the YAML deterministically (no LLM).
    Returns errors list or ok.
    """
    result = validate_dsl(req.yaml_str, req.manifest)
    return result


@app.post("/generate")
def generate(req: GenerateRequest):
    """
    Full pipeline executed via LangGraph: intake → plan → schema (MCP) → assemble → validate (with retry).
    """
    logger.info("==> /generate endpoint called. Invoking LangGraph workflow...")
    
    # 1. Try to extract an existing brief from the conversation history
    # (If the user already went through /intake and it was ready)
    brief = None
    for msg in reversed(req.conversation):
        if msg["role"] == "assistant" and "ready" in msg["content"] and "app_mode" in msg["content"]:
            try:
                content = msg["content"].strip()
                # Strip markdown if needed
                if content.startswith("```"):
                    content = content.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(content)
                if parsed.get("ready") is True:
                    brief = parsed
                    logger.info("Found existing brief in conversation. Will attempt to skip intake.")
                    break
            except:
                continue

    # Initial state
    initial_state = {
        "conversation": req.conversation,
        "node_types": store["node_types"],
        "store": store,
        "brief": brief,
        "intake_question": None,
        "manifest": None,
        "enriched_schemas": None,
        "edge_rules": None,
        "layout_rules": None,
        "app_header_template": None,
        "yaml_str": None,
        "errors": [],
        "steps_log": [],
        "attempt": 0,
        "done": False
    }

    # Execute graph synchronously
    final_state = dsl_workflow.invoke(initial_state)
    
    logger.info(f"Workflow finished. Done: {final_state.get('done')}, Brief: {final_state.get('brief') is not None}")
    
    if final_state.get("done"):
        # Passed validation or failed max attempts
        result = {
            "done": True,
            "yaml": final_state.get("yaml_str"),
            "manifest": final_state.get("manifest"),
            "steps": final_state.get("steps_log", [])
        }
        if final_state.get("errors"):
            result["errors"] = final_state.get("errors")
            result["warning"] = f"Generated with {len(final_state.get('errors'))} unresolved validation errors"
        return result

    if final_state.get("brief") is None:
        # Stopped at Intake needing more info
        return {
            "done": False,
            "question": final_state.get("intake_question", "Please provide more details."),
            "steps": final_state.get("steps_log", [])
        }
    
    # Fallback (e.g. if brief is present but not 'done' for some other reason)
    return {
        "done": False, 
        "steps": final_state.get("steps_log", []),
        "question": final_state.get("intake_question", "Generation failed or timed out.")
    }