from typing import Annotated, TypedDict, List, Dict, Any, Optional
import operator

class AgentState(TypedDict):
    # Input from user
    conversation: List[Dict[str, str]]
    
    # Static data
    node_types: List[str]
    store: Dict[str, Any]
    
    # State tracking
    brief: Optional[Dict[str, Any]]
    manifest: Optional[Dict[str, Any]]
    enriched_schemas: Optional[Dict[str, str]]
    edge_rules: Optional[str]
    layout_rules: Optional[str]
    app_header_template: Optional[str]
    yaml_str: Optional[str]
    
    # Results and Errors
    errors: List[str]
    intake_question: Optional[str]
    
    # Orchestration state
    steps_log: Annotated[List[str], operator.add]
    attempt: int
    done: bool
