"""Project one AT member turn onto the public Claude Code Agent SDK."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

import anyio
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, ResultMessage, SystemMessage, AssistantMessage
import yaml
from opentelemetry import propagate, trace
from telemetry import model_requests, turn_span
from task_recovery import Recovery
from worker_files import persist_terminal, publish
from agentteams_skill_warnings import check_skill, report_warnings


def role_of(record):
    role = record["member"]["role"]
    role = {"standalone": "worker", "team_leader": "leader", "remote": "remote-member"}.get(role, role)
    if role not in {"manager", "leader", "worker", "remote-member"}:
        raise ValueError("Unsupported member role")
    return role


def prepare_assets(record, bundle, plugin):
    manifest = yaml.safe_load((bundle / "plugin.yaml").read_text())
    role = role_of(record)
    paths = manifest["prompts"]
    prompts = list(paths["manager"].values()) if role == "manager" else [
        paths["team"], paths["agent"]["remoteMember" if role == "remote-member" else role]]
    context = [(bundle / path).read_text() for path in prompts]
    if role == "manager":
        context.append((bundle / "skills/team/task-management/SKILL.md").read_text().partition("## Plan as Leader")[0])
    context.append(json.dumps({key: record.get(key) for key in ("member", "team")}, ensure_ascii=False))
    context.extend((record["desired"].get("inlineConfig") or {}).values())
    skills = plugin / "skills"
    skills.mkdir()
    for section in manifest["skills"].values():
        for entry in section:
            if role in entry["roles"]:
                (skills / entry["id"]).symlink_to((bundle / entry["path"]).resolve())
    warnings = []
    # The skill plugin is rebuilt for this turn, so removing an assignment
    # cannot leave a discoverable stale copy in a long-lived session.
    builtin = {entry["id"] for section in manifest["skills"].values() for entry in section}
    for name in sorted(set(record["desired"].get("skills") or []) - builtin):
        try:
            if not name or name in {".", ".."} or Path(name).name != name or "\\" in name:
                raise ValueError("Invalid skill ID")
            destination = skills / name
            prefix = os.getenv("AGENTTEAMS_STORAGE_PREFIX")
            if prefix:
                remote = f"{prefix.rstrip('/')}/{record['storage']['memberPrefix']}/skills/{name}/"
                subprocess.run(["mc", "mirror", "--overwrite", remote, str(destination)], check=True,
                               timeout=30, capture_output=True)
            else:
                root = Path(os.environ["TEAMHARNESS_RUNTIME_CONFIG"]).parent.parent / "skills"
                source = root / name
                if not source.resolve().is_relative_to(root.resolve()):
                    raise ValueError("Invalid skill path")
                check_skill(source)
                shutil.copytree(source, destination)
            check_skill(destination)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            if name and Path(name).name == name and name not in {".", ".."}:
                shutil.rmtree(skills / name, ignore_errors=True)
            warnings.append(f"Skill {name}: load failed ({type(error).__name__})")
    report_warnings(warnings)
    return "\n\n".join(filter(None, context))


def mcp_servers(record, bundle, provider, task):
    # stdio MCP children receive a filtered environment from Claude Code.
    env = {k: v for k, v in os.environ.items() if k.startswith(("AGENTTEAMS_", "TEAMHARNESS_", "MC_"))}
    env.update(AGENTTEAMS_PLUGIN_DIR=str(bundle), AGENTTEAMS_AGENT_ROLE=role_of(record),
               AT_CLAUDE_TASK_CONTEXT=json.dumps(task, default=str))
    carrier = {}
    propagate.inject(carrier)
    if carrier.get("traceparent"):
        env["AT_OTEL_TRACEPARENT"] = carrier["traceparent"]
    servers = {"teamharness": {"command": sys.executable,
                               "args": [str(Path(__file__).with_name("team_tools.py"))], "env": env}}
    if any(task.get(key) for key in ("review", "planning", "completion", "execution")):
        return servers
    for item in record["desired"].get("mcpServers") or []:
        name, url = item["name"], item["url"]
        if not name or name in servers or item.get("transport", "http") not in {"http", "streamable-http"}:
            raise ValueError("Invalid or duplicate HTTP MCP server")
        address = urlsplit(url)
        if address.scheme not in {"https", "http"} or not address.netloc or address.username is not None:
            raise ValueError("Expected HTTP(S) MCP URL")
        headers = {}
        gateway = urlsplit(provider["baseUrl"])
        if (address.scheme, address.netloc) == (gateway.scheme, gateway.netloc):
            headers["Authorization"] = "Bearer " + provider["apiKey"]
        servers[name] = {"type": "http", "url": url, "headers": headers}
    return servers


def input_directories(context):
    if not context.get("taskDirectory"):
        return []
    root = (Path(context["taskDirectory"]) / "inputs").resolve()
    return [path for item in context.get("inputs", []) if item.get("readOnly") and item.get("directory")
            for path in [Path(item["directory"]).resolve()] if path != root and path.is_relative_to(root)]


def file_allowed(tool, fields, workspace, skills, context):
    path = (workspace / (fields.get("file_path") or fields.get("path") or ".")).resolve()
    pattern = Path(fields.get("pattern") or "") if tool == "Glob" else Path()
    if pattern.is_absolute() or ".." in pattern.parts:
        return False
    if path.is_relative_to(workspace.resolve()):
        return True
    if tool not in {"Read", "Grep", "Glob"}:
        return False
    return any(path.is_relative_to(root) for root in [*input_directories(context), *(s.resolve() for s in skills)])


async def run_turn(record, provider, workspace, prompt, session, task, bundle, *, on_effect=None, on_checkpoint=None):
    model = provider["models"][0]["id"]
    if (record["desired"].get("agentPackage") or {}).get("ref"):
        raise ValueError("Claude Code does not support AgentSpec packages")
    with (turn_span(role_of(record), task, model) as span,
          model_requests(span, workspace, session) as new_session_id,
          tempfile.TemporaryDirectory(prefix="at-claude-skills-") as directory):
        plugin = Path(directory)
        instructions = prepare_assets(record, bundle, plugin)
        servers = mcp_servers(record, bundle, provider, task)
        refreshed = plugin / "refreshed.json"
        servers["teamharness"]["env"]["AT_CLAUDE_REFRESH_FILE"] = str(refreshed)
        decision = any(task.get(key) for key in ("review", "planning", "completion"))
        tools = [] if decision else ["Read", "Glob", "Grep", "Skill"]
        if not decision and role_of(record) != "manager":
            tools.extend(["Write", "Edit"])
        if not decision and not task.get("execution") and os.getenv("AGENTTEAMS_YOLO") == "1":
            tools.append("Bash")
        context = task.get("context") or {}
        identity = task.get("identity")
        recovery = Recovery(device_delivery=True) if identity else None
        operations = {}
        tool_spans = {}
        confirmed = None

        async def before_tool(data, call_id, _context):
            nonlocal confirmed
            name = data["tool_name"]
            fields = data.get("tool_input") or {}
            try:
                if confirmed and on_checkpoint and on_checkpoint(*confirmed):
                    confirmed = None
                if on_effect and name not in {"Read", "Glob", "Grep", "Skill"}:
                    on_effect()
                if name in {"Read", "Write", "Edit", "Glob", "Grep"} and not file_allowed(
                        name, fields, workspace, (plugin / "skills").iterdir(), context):
                    raise ValueError("Outside the prepared input and output directories")
                if recovery:
                    recovery.tools_current(identity)
                    if name in {"Read", "Glob", "Grep", "Write", "Edit"}:
                        key = data.get("tool_use_id") or call_id
                        operation = recovery.begin_tools(identity, [{"id": key, "name": name, "arguments": fields,
                                                                   "read_only": name in {"Read", "Glob", "Grep"}}])
                        operations[key] = operation
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                               "permissionDecisionReason": str(error)}}
            key = data.get("tool_use_id") or call_id
            if key:
                tool_spans[key] = trace.get_tracer("agentteams.claude-code").start_span("claude-code.tool",
                    attributes={"gen_ai.tool.name": name, "gen_ai.tool.call.id": key,
                                "agentteams.session.id": data.get("session_id") or ""})
            return {}

        async def after_tool(data, call_id, _context):
            nonlocal confirmed
            key = data.get("tool_use_id") or call_id
            tool_span = tool_spans.pop(key, None)
            if tool_span:
                tool_span.end()
            if key in operations:
                name = data["tool_name"]
                success = data.get("hook_event_name") == "PostToolUse"
                if not success and name not in {"Read", "Glob", "Grep"}:
                    return {}  # Keep the registered mutation unresolved until authoritative verification.
                artifacts = []
                if success and name in {"Write", "Edit"}:
                    artifacts.append(publish(identity, workspace, data["tool_input"]["file_path"], operations[key]))
                result = {"id": key, "content": artifacts or {"response_sha256": Recovery.digest(data.get("tool_response") if success else data.get("error"))}}
                if not success:
                    result.update(status="error", effect="none")
                persist_terminal(identity, operations[key], result, artifacts)
                saved = recovery.finish_tools(identity, operations[key], [result], artifacts=artifacts)
                if data.get("session_id"):
                    confirmed = (data["session_id"], key, saved["execution"])
                del operations[key]
            return {}

        allowed_mcp = ["mcp__teamharness__task"] if decision or task.get("execution") else [
            "mcp__" + name + "__*" for name in servers]
        options = ClaudeAgentOptions(
            model=model, cwd=str(workspace), resume=session, session_id=new_session_id, tools=tools,
            allowed_tools=tools + allowed_mcp, permission_mode="dontAsk",
            system_prompt={"type": "preset", "preset": "claude_code", "append": instructions, "snapshot": False},
            setting_sources=[], plugins=[{"type": "local", "path": directory}],
            mcp_servers=servers, strict_mcp_config=True,
            add_dirs=[str(path) for path in input_directories(context)],
            hooks={"PreToolUse": [HookMatcher(hooks=[before_tool])],
                   "PostToolUse": [HookMatcher(hooks=[after_tool])],
                   "PostToolUseFailure": [HookMatcher(hooks=[after_tool])]},
            env={"ANTHROPIC_BASE_URL": provider["baseUrl"].rstrip("/").removesuffix("/v1"),
                 "ANTHROPIC_AUTH_TOKEN": provider["apiKey"], "ANTHROPIC_API_KEY": "",
                 "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        )
        async with ClaudeSDKClient(options=options) as client:
            if decision or task.get("execution") or (task.get("sources") and os.getenv("AGENTTEAMS_CONTROLLER_URL")):
                with anyio.fail_after(30):
                    while True:
                        status = await client.get_mcp_status()
                        server = next((item for item in status["mcpServers"] if item["name"] == "teamharness"), {})
                        tool = next((t for t in server.get("tools", []) if t["name"] == "task"), None)
                        if server.get("status") == "connected" and tool:
                            task_name = f"mcp__{server['name']}__{tool['name']}"
                            break
                        if server.get("status") in {"failed", "disabled", "needs-auth"}:
                            raise RuntimeError("The registered TeamHarness Task tool is unavailable")
                        await asyncio.sleep(0.1)
                prompt = f"Use the registered Task tool {task_name} for Task operations.\n" + prompt
            await client.query(prompt)
            stream = client.receive_response()
            while True:
                # Bound each idle interval, including waiting for the final result.
                with anyio.fail_after(float(os.getenv("AGENTTEAMS_LLM_STREAM_TIMEOUT_S", "300"))):
                    try:
                        message = await anext(stream)
                    except StopAsyncIteration:
                        break
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    span.set_attribute("agentteams.session.id", message.data.get("session_id") or "")
                    span.set_attribute("agentteams.turn.id", message.data.get("uuid") or "")
                if isinstance(message, AssistantMessage):
                    with trace.get_tracer("agentteams.claude-code").start_as_current_span("claude-code.model.response") as result_span:
                        result_span.set_attribute("gen_ai.response.model", message.model)
                        result_span.set_attribute("gen_ai.response.id", getattr(message, "message_id", None) or "")
                if isinstance(message, ResultMessage):
                    if message.is_error or message.subtype != "success" or not message.result:
                        reason = message.terminal_reason or message.subtype
                        if message.api_error_status is not None:
                            reason = f"gateway HTTP {message.api_error_status}"
                        raise RuntimeError(f"Claude Code returned no usable result ({reason})")
                    if refreshed.is_file():
                        task["refresh"] = json.loads(refreshed.read_text())
                    return message.session_id, message.result
    raise RuntimeError("Claude Code exited without a result")
