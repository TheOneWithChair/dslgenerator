"""
agents/intake.py
Multi-turn intake agent that collects a structured brief from the user.
"""
import json
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = os.getenv("MODEL", "gemini-2.0-flash-latest")


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


def run_intake(conversation_history: list, node_types: list) -> dict:
    """
    Run one turn of the intake agent.
    
    Args:
        conversation_history: List of {"role": "user"|"assistant", "content": str}
        node_types: List of available node type strings
    
    Returns:
        {"ready": False, "question": "..."} — needs more info
        {"ready": True, ...brief fields...} — brief complete
    """
    system = INTAKE_SYSTEM.format(node_types=", ".join(node_types))

    # Build Gemini chat history (exclude last user message — passed separately)
    model = genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=system,
    )

    # Convert conversation history to Gemini format
    gemini_history = []
    for msg in conversation_history[:-1]:
        role = "model" if msg["role"] == "assistant" else "user"
        gemini_history.append({"role": role, "parts": [msg["content"]]})

    chat = model.start_chat(history=gemini_history)

    last_message = conversation_history[-1]["content"]
    response = chat.send_message(last_message)

    raw = response.text.strip()

    # Try to parse as JSON
    try:
        # Strip markdown fences if present
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        return result
    except json.JSONDecodeError:
        # LLM returned plain text (a question) — wrap it
        return {"ready": False, "question": raw}