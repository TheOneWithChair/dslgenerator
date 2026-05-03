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

load_dotenv(override=True)

# Ensure backend/ is on sys.path so `agents` and `validator` can be imported
# regardless of where uvicorn is launched from.
_BACKEND_DIR = Path(__file__).parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from agents.intake import run_intake
from agents.planner import run_planner
from agents.assembler import run_assembler
from validator import validate_dsl

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
    One turn of the intake agent.
    Returns either a clarifying question or the complete brief.
    """
    result = run_intake(req.conversation, store["node_types"])
    return result


@app.post("/plan")
def plan(req: PlanRequest):
    """
    Runs the planner agent on a completed brief.
    Returns the node manifest JSON.
    """
    manifest = run_planner(req.brief, store["node_types"])
    return {"manifest": manifest}


@app.post("/assemble")
def assemble(req: AssembleRequest):
    """
    Assembles YAML from the manifest.
    Fetches only the schemas needed for the nodes in this manifest.
    """
    manifest = req.manifest

    # Fetch only needed schemas (not the full store)
    needed_types = list({node["type"] for node in manifest.get("nodes", [])})
    enriched_schemas = {}
    for ntype in needed_types:
        schema = store["node_schemas"].get(ntype)
        if schema:
            enriched_schemas[ntype] = schema

    # Pick the right app header template
    app_mode = manifest.get("app_mode", "workflow")
    header_key = "workflow" if app_mode == "workflow" else "chat"
    header_template = store["app_header"].get(header_key, "")

    yaml_str = run_assembler(
        manifest=manifest,
        enriched_schemas=enriched_schemas,
        edge_rules=store["edge_rules"],
        layout_rules=store["layout_rules"],
        app_header_template=header_template,
        previous_errors=req.previous_errors,
        previous_yaml=req.previous_yaml,
    )
    return {"yaml": yaml_str}


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
    Full pipeline: intake → plan → assemble → validate (with retry).
    The conversation must include the user's initial prompt + all Q&A.
    The last assistant message should be the complete brief JSON.
    """
    steps_log = []

    # Step 1: Get the brief from the conversation
    # The final intake call should have returned a brief — run it to confirm
    steps_log.append("Running intake to extract brief...")
    brief_result = run_intake(req.conversation, store["node_types"])

    if not brief_result.get("ready"):
        return {
            "done": False,
            "question": brief_result.get("question", "Please provide more details."),
            "steps": steps_log
        }

    brief = brief_result
    steps_log.append(f"Brief ready: {brief.get('app_name')}")

    # Step 2: Plan
    steps_log.append("Planning node graph...")
    manifest = run_planner(brief, store["node_types"])
    steps_log.append(f"Planned {len(manifest['nodes'])} nodes, {len(manifest['edges'])} edges")

    # Step 3: Fetch schemas for needed node types
    steps_log.append("Fetching node schemas...")
    needed_types = list({node["type"] for node in manifest.get("nodes", [])})
    enriched_schemas = {t: store["node_schemas"][t] for t in needed_types if t in store["node_schemas"]}
    steps_log.append(f"Schemas fetched: {needed_types}")

    # Step 4+5: Assemble → Validate → Retry loop (max 3 attempts)
    app_mode = manifest.get("app_mode", "workflow")
    header_key = "workflow" if app_mode == "workflow" else "chat"
    header_template = store["app_header"].get(header_key, "")

    yaml_str = None
    last_errors = None

    for attempt in range(3):
        steps_log.append(f"Assembling YAML (attempt {attempt + 1}/3)...")
        yaml_str = run_assembler(
            manifest=manifest,
            enriched_schemas=enriched_schemas,
            edge_rules=store["edge_rules"],
            layout_rules=store["layout_rules"],
            app_header_template=header_template,
            previous_errors=last_errors,
            previous_yaml=yaml_str,
        )

        steps_log.append("Validating...")
        result = validate_dsl(yaml_str, manifest)

        if result["valid"]:
            steps_log.append("✅ Valid DSL generated!")
            return {
                "done": True,
                "yaml": yaml_str,
                "manifest": manifest,
                "steps": steps_log
            }

        last_errors = result["errors"]
        steps_log.append(f"Validation failed ({len(last_errors)} errors), retrying...")

    # Failed after 3 attempts
    return {
        "done": True,
        "yaml": yaml_str,
        "manifest": manifest,
        "steps": steps_log,
        "warning": f"Generated with {len(last_errors)} unresolved validation errors",
        "errors": last_errors
    }