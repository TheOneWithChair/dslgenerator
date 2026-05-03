import json
import os
import logging
from typing import Dict, Any, List
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from state import AgentState

logger = logging.getLogger("agent.intake")

INTAKE_SYSTEM = """You are a Dify workflow intake specialist. Your job is to understand 
what the user wants to build and collect all information needed to plan a Dify DSL workflow.

Available Dify app modes:
- workflow: form-based inputs, one-shot execution, uses End node for output
- chat: conversational, sys.query available, uses Answer node for output  
- agent-chat: like chat but agent can autonomously call tools
- advanced-chat: full chatflow with branching, conditions, loops

Available node types: {node_types}

Your task:
1. Read the user's initial description
2. Ask ONE focused clarifying question at a time (not a list of all questions at once)
3. When you have enough info, output ONLY a JSON brief (no extra text)

Questions to cover (ask naturally, one at a time):
- App mode: workflow (one-shot) or chat (conversational)?
- What are the inputs? Names, types (text/select/number/file), required?
- What processing steps? (LLM calls, HTTP requests, code, knowledge retrieval, conditions?)
- What should the output look like?
- Any external tools, APIs, or knowledge bases?

When you have all needed info, respond with ONLY this JSON (no markdown, no explanation):
{{
  "ready": true,
  "app_name": "...",
  "app_mode": "workflow|chat|agent-chat|advanced-chat",
  "description": "...",
  "inputs": [
    {{"name": "variable_name", "label": "Display Label", "type": "text-input|paragraph|select|number|file|file-list", "required": true, "options": [], "max_length": null}}
  ],
  "processing_steps": [
    {{"step": 1, "node_type": "llm|code|http-request|knowledge-retrieval|if-else|template-transform|parameter-extractor", "purpose": "what this step does", "notes": "any special config needed"}}
  ],
  "output_description": "what the final output is",
  "tools_or_apis": [],
  "knowledge_bases": []
}}

If you still need more information, respond with ONLY:
{{"ready": false, "question": "your single clarifying question here"}}
"""

def intake_node(state: AgentState) -> Dict[str, Any]:
    """
    LangGraph Stage 1: Intake Agent node.
    """
    logger.info("--- STAGE 1: INTAKE AGENT ---")
    
    if state.get("brief"):
        logger.info("Brief already present in state, skipping intake.")
        return {
            "steps_log": ["Stage 1: Intake skipped (brief already present)."]
        }
    
    llm = ChatGoogleGenerativeAI(
        model=os.getenv("MODEL", "gemini-flash-latest"),
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0.7
    )
    
    system_prompt = INTAKE_SYSTEM.format(node_types=", ".join(state["node_types"]))
    messages = [SystemMessage(content=system_prompt)]
    
    for msg in state["conversation"]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
            
    response = llm.invoke(messages)
    raw = response.content.strip()
    
    try:
        # Strip markdown fences if present
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        
        if result.get("ready"):
            return {
                "brief": result,
                "steps_log": ["Stage 1: Intake complete. Brief extracted."]
            }
        else:
            return {
                "intake_question": result.get("question", "Could you provide more details?"),
                "steps_log": ["Stage 1: Intake needs more clarification."]
            }
    except json.JSONDecodeError:
        # LLM returned plain text (a question)
        return {
            "intake_question": raw,
            "steps_log": ["Stage 1: Intake returned clarifying question."]
        }