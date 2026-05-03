import json
from typing import Dict, Any, List
import logging

logger = logging.getLogger("mcp_layer")

from state import AgentState

def schema_fetcher_node(state: AgentState) -> Dict[str, Any]:
    """
    LangGraph Stage 3: Schema Fetcher (MCP Tool Calls) node.
    """
    logger.info("--- STAGE 3: MCP SCHEMA FETCHER ---")
    
    mcp_client = MCPRegistryClient(state["store"])
    needed_types = list({n["type"] for n in state["manifest"].get("nodes", [])})
    
    enriched_schemas = mcp_client.fetch_dify_node_schemas(needed_types)
    edge_rules = mcp_client.fetch_edge_rules()
    layout_rules = mcp_client.fetch_layout_rules()
    
    app_mode = state["manifest"].get("app_mode", "workflow")
    header_key = "workflow" if app_mode == "workflow" else "chat"
    app_header_template = mcp_client.fetch_app_header(header_key)
    
    return {
        "enriched_schemas": enriched_schemas,
        "edge_rules": edge_rules,
        "layout_rules": layout_rules,
        "app_header_template": app_header_template,
        "steps_log": ["Stage 3: MCP schema fetch complete."]
    }

class MCPRegistryClient:
    """
    Mock Model Context Protocol (MCP) Client for fetching Dify Schemas.
    In a real-world scenario, this would communicate over stdio or SSE
    with an external MCP server to fetch schemas dynamically.
    """
    def __init__(self, store: Dict[str, Any]):
        self.store = store

    def fetch_dify_node_schemas(self, node_types: List[str]) -> Dict[str, str]:
        """
        Stage 3: MCP Tool Call to fetch exact node schemas.
        """
        logger.info(f"[MCP Layer] Fetching schemas for: {node_types}")
        schemas = {}
        for ntype in node_types:
            schema = self.store.get("node_schemas", {}).get(ntype)
            if schema:
                schemas[ntype] = schema
            else:
                logger.warning(f"[MCP Layer] Schema NOT FOUND for node type: {ntype}")
        logger.info(f"[MCP Layer] Successfully fetched {len(schemas)} schemas.")
        return schemas

    def fetch_edge_rules(self) -> str:
        """Fetch edge mapping rules."""
        logger.info("[MCP Layer] Fetching edge rules via MCP...")
        return self.store.get("edge_rules", "")

    def fetch_layout_rules(self) -> str:
        """Fetch layout mapping rules."""
        logger.info("[MCP Layer] Fetching layout rules via MCP...")
        return self.store.get("layout_rules", "")

    def fetch_app_header(self, mode: str) -> str:
        """Fetch app header template based on mode."""
        logger.info(f"[MCP Layer] Fetching app header for mode: {mode} via MCP...")
        return self.store.get("app_header", {}).get(mode, "")
