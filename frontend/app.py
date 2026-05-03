"""
frontend/app.py — Streamlit UI for the Dify DSL Generator
Run with: streamlit run frontend/app.py
"""
import streamlit as st
import httpx
import json

BACKEND_URL = "http://127.0.0.1:8001"

# ─── Page config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Dify DSL Generator",
    page_icon="⚙️",
    layout="wide"
)

# ─── Diagnostic Function ─────────────────────────────────────────────────────
def test_connection():
    try:
        r = httpx.get(f"{BACKEND_URL}/health", timeout=5)
        return f"✅ Connection OK! Status: {r.status_code}, Response: {r.json()}"
    except Exception as e:
        return f"❌ Connection FAILED: {str(e)}"

# ─── Session state init ──────────────────────────────────────────────────────

if "conversation" not in st.session_state:
    st.session_state.conversation = []
if "phase" not in st.session_state:
    st.session_state.phase = "start"      # start → intake → generating → done
if "final_yaml" not in st.session_state:
    st.session_state.final_yaml = None
if "manifest" not in st.session_state:
    st.session_state.manifest = None
if "steps_log" not in st.session_state:
    st.session_state.steps_log = []
if "errors" not in st.session_state:
    st.session_state.errors = []
if "current_question" not in st.session_state:
    st.session_state.current_question = None


# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Dify DSL Generator")
    st.markdown("---")

    # Backend health check
    try:
        r = httpx.get(f"{BACKEND_URL}/health", timeout=3)
        if r.status_code == 200:
            data = r.json()
            st.success(f"Backend connected")
            st.caption(f"Node types: {len(data.get('node_types', []))}")
        else:
            st.error("Backend error")
    except Exception:
        st.error("Backend not running.\n\nStart with:\n```\nuvicorn backend.main:app --reload --port 8001\n```")

    st.markdown("---")
    st.markdown("**How it works:**")
    st.markdown("""
1. Describe your workflow
2. Answer clarifying questions
3. Get a valid DSL YAML
4. Import directly to Dify
    """)

    st.markdown("---")
    if st.button("🔄 Start Over", use_container_width=True):
        for key in ["conversation", "phase", "final_yaml", "manifest",
                    "steps_log", "errors", "current_question"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()


# ─── Main layout ─────────────────────────────────────────────────────────────

left_col, right_col = st.columns([1, 1], gap="large")

# ─── LEFT: Chat interface ─────────────────────────────────────────────────────

with left_col:
    st.subheader("💬 Build your workflow")

    # Show conversation history
    chat_container = st.container(height=420)
    with chat_container:
        for msg in st.session_state.conversation:
            role = msg["role"]
            content = msg["content"]
            # Don't show the raw JSON brief in the chat
            if role == "assistant" and content.strip().startswith("{"):
                try:
                    parsed = json.loads(content)
                    if parsed.get("ready") is True:
                        st.chat_message("assistant").markdown(
                            "✅ Got everything I need! Generating your DSL now..."
                        )
                        continue
                    elif parsed.get("ready") is False:
                        st.chat_message("assistant").markdown(parsed.get("question", content))
                        continue
                except Exception:
                    pass
            st.chat_message(role).markdown(content)

    # Input area
    if st.session_state.phase == "start":
        st.markdown("**Describe what you want to build:**")
        prompt = st.text_area(
            "Your workflow description",
            placeholder="e.g. Build a chatbot that answers customer support questions using our knowledge base. It should detect if the question is about billing or technical issues and route accordingly.",
            height=100,
            label_visibility="collapsed"
        )
        if st.button("🚀 Start", use_container_width=True, type="primary"):
            if prompt.strip():
                st.session_state.conversation.append({"role": "user", "content": prompt})
                st.session_state.phase = "intake"
                st.rerun()

    elif st.session_state.phase == "intake":
        # Run intake agent turn
        with st.spinner("Thinking..."):
            try:
                r = httpx.post(
                    f"{BACKEND_URL}/intake",
                    json={"conversation": st.session_state.conversation},
                    timeout=30
                )
                result = r.json()
            except Exception as e:
                st.error(f"Backend unreachable at {BACKEND_URL}")
                st.info("Check if the backend terminal shows any errors.")
                if st.button("🔍 Diagnose Connection", key="diag_intake"):
                    st.code(test_connection())
                result = {"ready": False, "question": "Connection error. Is the backend running?"}

        if result.get("ready"):
            # Brief is complete — add to conversation and start generating
            st.session_state.conversation.append(
                {"role": "assistant", "content": json.dumps(result)}
            )
            st.session_state.phase = "generating"
            st.rerun()
        else:
            question = result.get("question", "Please tell me more.")
            st.session_state.conversation.append({"role": "assistant", "content": question})
            st.session_state.current_question = question
            st.session_state.phase = "answering"
            st.rerun()

    elif st.session_state.phase == "answering":
        # User answers the clarifying question
        answer = st.chat_input("Your answer...")
        if answer:
            st.session_state.conversation.append({"role": "user", "content": answer})
            st.session_state.phase = "intake"
            st.rerun()

    elif st.session_state.phase == "generating":
        with st.spinner("Generating DSL..."):
            try:
                r = httpx.post(
                    f"{BACKEND_URL}/generate",
                    json={"conversation": st.session_state.conversation},
                    timeout=300
                )
                result = r.json()
                st.session_state.steps_log = result.get("steps", [])
            except Exception as e:
                st.error(f"Generation failed: {e}")
                result = {"done": False, "question": f"Error: {str(e)}"}

        if result.get("done"):
            st.session_state.final_yaml = result.get("yaml")
            st.session_state.manifest = result.get("manifest")
            st.session_state.errors = result.get("errors", [])
            st.session_state.phase = "done"
            st.rerun()
        else:
            # Still needs intake or failed
            question = result.get("question", "")
            if question:
                st.session_state.conversation.append({"role": "assistant", "content": question})
                st.session_state.phase = "answering"
                st.rerun()
            else:
                st.error("Generation stopped without completion and no clarifying question was provided.")
                if st.button("Try again"):
                    st.rerun()

    elif st.session_state.phase == "done":
        st.success("✅ DSL generated! See output on the right.")

        # Show pipeline steps
        if st.session_state.steps_log:
            with st.expander("Pipeline steps", expanded=False):
                for step in st.session_state.steps_log:
                    st.caption(step)

        # Show errors if any
        if st.session_state.errors:
            with st.expander(f"⚠️ {len(st.session_state.errors)} validation warnings", expanded=True):
                for err in st.session_state.errors:
                    st.warning(err)

        if st.button("🔁 Generate another", use_container_width=True):
            for key in ["conversation", "phase", "final_yaml", "manifest",
                        "steps_log", "errors", "current_question"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()


# ─── RIGHT: YAML Output ───────────────────────────────────────────────────────

with right_col:
    st.subheader("📄 Generated DSL YAML")

    if st.session_state.final_yaml:
        # Download button
        st.download_button(
            label="⬇️ Download .yml",
            data=st.session_state.final_yaml,
            file_name=f"{st.session_state.manifest.get('app_name', 'workflow').replace(' ', '_').lower()}.yml",
            mime="text/yaml",
            use_container_width=True,
            type="primary"
        )

        # Validation status
        if not st.session_state.errors:
            st.success("✅ Passed all validation checks — safe to import to Dify")
        else:
            st.warning(f"⚠️ Generated with {len(st.session_state.errors)} warnings")

        # YAML viewer
        st.code(st.session_state.final_yaml, language="yaml")

        # Manifest summary
        if st.session_state.manifest:
            with st.expander("Node graph summary", expanded=False):
                manifest = st.session_state.manifest
                nodes = manifest.get("nodes", [])
                edges = manifest.get("edges", [])

                st.markdown(f"**App:** {manifest.get('app_name')} ({manifest.get('app_mode')})")
                st.markdown(f"**Nodes:** {len(nodes)} | **Edges:** {len(edges)}")

                for node in nodes:
                    st.markdown(f"- `{node['type']}` — {node.get('title', '')} (`{node['id'][:8]}...`)")

    else:
        st.markdown("""
        <div style="
            border: 1.5px dashed var(--background-secondary);
            border-radius: 12px;
            padding: 60px 20px;
            text-align: center;
            color: var(--text-color);
            opacity: 0.5;
        ">
            <div style="font-size: 48px; margin-bottom: 12px;">📋</div>
            <div>Your generated DSL will appear here</div>
        </div>
        """, unsafe_allow_html=True)