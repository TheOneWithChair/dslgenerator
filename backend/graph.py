import logging
from langgraph.graph import StateGraph, END
from state import AgentState

# Import nodes from their respective agent files
from agents.intake import intake_node
from agents.planner import planner_node
from mcp_layer import schema_fetcher_node
from agents.assembler import assembler_node
from validator import validator_node

logger = logging.getLogger("orchestrator.graph")

# --- Edges / Routing Logic ---

def route_after_intake(state: AgentState) -> str:
    """Route to planner if brief is ready, else stop for more info."""
    if state.get("brief") is not None:
        return "planner"
    return END

def route_after_validator(state: AgentState) -> str:
    """Route to END if valid or max retries hit, else loop back to assembler."""
    if state.get("done"):
        return END
    elif state.get("attempt", 0) >= 3:
        # We don't want to loop forever
        return END
    else:
        return "assembler"

# --- Graph Assembly ---

def build_dsl_workflow() -> StateGraph:
    """
    Builds the multi-agent Dify DSL generation workflow using LangGraph.
    Stages: Intake -> Planner -> Schema Fetcher (MCP) -> Assembler -> Validator (with loop)
    """
    workflow = StateGraph(AgentState)
    
    # Define Nodes
    workflow.add_node("intake", intake_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("schema_fetcher", schema_fetcher_node)
    workflow.add_node("assembler", assembler_node)
    workflow.add_node("validator", validator_node)
    
    # Define Connections (Edges)
    workflow.set_entry_point("intake")
    
    workflow.add_conditional_edges("intake", route_after_intake)
    workflow.add_edge("planner", "schema_fetcher")
    workflow.add_edge("schema_fetcher", "assembler")
    workflow.add_edge("assembler", "validator")
    workflow.add_conditional_edges("validator", route_after_validator)
    
    return workflow.compile()
