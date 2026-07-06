# ruff: noqa
import datetime
import json
import logging
import os
import re
import sys
from pydantic import BaseModel, Field
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.adk.workflow import Workflow, node, START
from google.adk.agents.context import Context
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams, StdioServerParameters
from google.genai import types

from .config import config

# Setup security audit logging
logger = logging.getLogger("security_audit")
logger.setLevel(logging.INFO)
# Standard output logging
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(handler)

# Pydantic models for structured agent I/O
class OrchestratorOutput(BaseModel):
    route: str = Field(description="Must be 'ranger_threat' for urgent ranger dispatch threats, or 'ecological_sightings' for observations, species lookups, or migrations.")
    analysis: str = Field(description="A brief summary explanation of why this classification was chosen.")

class RangerThreatAnalysis(BaseModel):
    threat_summary: str = Field(description="Brief summary of the detected poaching/trespassing threat.")
    location: str = Field(description="The sector or location coordinates.")
    action_required: str = Field(description="Specific recommended action for the ranger team.")
    severity: str = Field(description="Classification: HIGH or CRITICAL.")

class EcologicalSightingAnalysis(BaseModel):
    species: str = Field(description="Name of the detected species.")
    conservation_status: str = Field(description="Status from wildlife database lookup.")
    migration_anomaly: str = Field(description="Is this sightings or migration pattern anomalous or normal?")
    habitat_notes: str = Field(description="General notes based on weather and light conditions.")

# Configure the local MCP server process using Stdio transport
python_exe = sys.executable
mcp_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "mcp_server.py"))

server_params = StdioServerParameters(
    command=python_exe,
    args=[mcp_script]
)

# Instantiate the McpToolset
mcp_toolset = McpToolset(connection_params=StdioConnectionParams(server_params=server_params))

# Orchestrator agent definitions
orchestrator_agent = LlmAgent(
    name="orchestrator_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the main WildlifeGuard orchestrator. Analyze the incoming wildlife camera reports. "
        "Classify whether it needs urgent ranger threat response (illegal human activity, weapons, vehicles, poaching) "
        "or ecological analysis (wildlife sightings, animal numbers, migration patterns). "
        "Return the classification and a short summary."
    ),
    output_schema=OrchestratorOutput,
    output_key="decision"
)

# Specialized sub-agents definitions with MCP toolset wired in
ranger_threat_agent = LlmAgent(
    name="ranger_threat_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You analyze urgent security and poaching threats in wildlife reserves. "
        "First, extract the coordinates (latitude and longitude) from the incoming report. "
        "You MUST call the get_weather_location tool with these coordinates to check the battery and weather status. "
        "If coordinates are missing, use Lat 0.0, Long 0.0 as a fallback. "
        "Do NOT write any natural language explanations, chat messages, or questions to the user. "
        "You must output ONLY a valid JSON object matching the RangerThreatAnalysis schema, with all fields populated."
    ),
    tools=[mcp_toolset],
    output_schema=RangerThreatAnalysis,
    output_key="threat_analysis"
)

ecological_sightings_agent = LlmAgent(
    name="ecological_sightings_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You analyze animal sightings and ecological reports in wildlife reserves. "
        "First, extract the species name and coordinates from the incoming report. "
        "You MUST call get_wildlife_db to retrieve details and conservation status of the species. "
        "You should also check coordinates using get_weather_location if available. "
        "If coordinates are missing, use Lat 0.0, Long 0.0 as a fallback. "
        "Do NOT write any natural language explanations, chat messages, or questions to the user. "
        "You must output ONLY a valid JSON object matching the EcologicalSightingAnalysis schema, with all fields populated."
    ),
    tools=[mcp_toolset],
    output_schema=EcologicalSightingAnalysis,
    output_key="ecology_analysis"
)

# Node functions
@node
def security_checkpoint(ctx: Context, node_input: types.Content) -> Event:
    """Filters user input for security checks (PII, Prompt Injection) and logs audit reports."""
    # 1. Parse text from the Content input
    text = ""
    if node_input and hasattr(node_input, 'parts'):
        for part in node_input.parts:
            if hasattr(part, 'text') and part.text:
                text += part.text
            elif isinstance(part, str):
                text += part
    else:
        text = str(node_input)

    # 2. PII Scrubbing (License plates, phone numbers, emails)
    plate_pattern = r"\b[A-Z]{3}-\d{4}\b"
    phone_pattern = r"\b\d{3}-\d{3}-\d{4}\b"
    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    
    scrubbed_text = re.sub(plate_pattern, "[REDACTED_PLATE]", text)
    scrubbed_text = re.sub(phone_pattern, "[REDACTED_PHONE]", text)
    scrubbed_text = re.sub(email_pattern, "[REDACTED_EMAIL]", scrubbed_text)

    # 3. Prompt Injection Detection
    injection_keywords = ["ignore previous instructions", "bypass security", "system override", "you are now a simulator"]
    is_injection = any(kw in text.lower() for kw in injection_keywords)

    # 4. Structured Audit Log
    audit_entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session_id": ctx.session.id,
        "pii_redacted": scrubbed_text != text,
        "injection_detected": is_injection,
        "severity": "WARNING" if (scrubbed_text != text) else ("CRITICAL" if is_injection else "INFO")
    }
    logger.info(json.dumps(audit_entry))

    if is_injection:
        return Event(
            output="SECURITY BLOCK: A prompt injection attempt was detected and blocked.",
            route="security_event"
        )

    return Event(output=scrubbed_text, route="ok", state={"user_query": scrubbed_text})


@node
def route_decision(ctx: Context, node_input: dict) -> Event:
    """Routes based on the orchestrator classification decision."""
    decision = ctx.state.get("decision", {})
    if hasattr(decision, "get"):
        route = decision.get("route", "")
        analysis = decision.get("analysis", "")
    else:
        route = getattr(decision, "route", "")
        analysis = getattr(decision, "analysis", "")
    
    route = str(route).lower().strip()
    user_query = ctx.state.get("user_query", "")
    combined_input = f"Orchestrator Analysis: {analysis}\nOriginal User Report: {user_query}"
    
    if "threat" in route or "ranger" in route:
        return Event(output=combined_input, route="ranger_threat")
    else:
        return Event(output=combined_input, route="ecological_sightings")


@node(rerun_on_resume=True)
async def ranger_approval_node(ctx: Context, node_input: dict):
    """Pauses for human approval before sending alert updates to the dispatch tool."""
    analysis = ctx.state.get("threat_analysis", {})
    
    if not ctx.resume_inputs:
        yield RequestInput(
            interrupt_id="approve_alert",
            message="✋ PAUSE FOR OPERATOR APPROVAL: Do you approve sending this ranger dispatch alert? (yes/no)"
        )
        return

    approval = ctx.resume_inputs.get("approve_alert", "").lower().strip()
    if approval == "yes":
        yield Event(output=f"Ranger dispatch approved. Threat analysis logged: {analysis}", state={"dispatch_status": "APPROVED"})
    else:
        yield Event(output="Ranger dispatch rejected by human operator.", state={"dispatch_status": "REJECTED"})


@node
def ecological_report_node(ctx: Context, node_input: dict) -> str:
    """Logs the ecological sighting report."""
    analysis = ctx.state.get("ecology_analysis", {})
    return f"ECOLOGICAL REPORT RECORDED: Species analysis complete. Logged sighting: {analysis}"


@node
def security_event_handler(ctx: Context, node_input: str) -> str:
    """Handles and formats security alert responses."""
    return f"ALERT: System action blocked due to security validation failure: {node_input}"


@node
def final_response(ctx: Context, node_input: Any):
    """Outputs the final result formatted as standard markdown for the UI."""
    msg = f"**System Response:**\n\n{node_input}"
    yield Event(content=types.Content(role='model', parts=[types.Part.from_text(text=msg)]))
    yield Event(output=node_input)


# Construct the Workflow Graph (ADK 2.0 Graph API)
root_agent = Workflow(
    name="wildlife_guard_workflow",
    edges=[
        # Entry path
        (START, security_checkpoint),
        
        # Security paths (conditional mapping)
        (security_checkpoint, {"ok": orchestrator_agent, "security_event": security_event_handler}),
        
        # Routing path
        (orchestrator_agent, route_decision),
        
        # Routing decision paths (conditional mapping)
        (route_decision, {"ranger_threat": ranger_threat_agent, "ecological_sightings": ecological_sightings_agent}),
        
        # Action paths
        (ranger_threat_agent, ranger_approval_node),
        (ecological_sightings_agent, ecological_report_node),
        
        # Convergence
        (ranger_approval_node, final_response),
        (ecological_report_node, final_response),
        (security_event_handler, final_response),
    ],
    description="WildlifeGuard surveillance and reporting workflow agent."
)

# Instantiate App with Resumability Config
app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)
