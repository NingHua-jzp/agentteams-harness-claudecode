# Claude Code implementation handoff

Prepared on 2026-11-24. This is an implementation checklist, not an acceptance report.

## Starting point

- Repository: `agentteams-group/agentteams-harness-claudecode`
- Proposed runtime ID: `claudecode`
- Proposed image: `agentteams-harness-claudecode`
- Core inspected at `6ad1a9799` (main, Harness integration guide #1695). Resolve and pin the full commit when building; refresh main before starting implementation.
- The SDK language and supported role/deployment scope are for the implementation owner to declare. A shared image can select roles at startup.

## Native integration

1. Pin an official Claude Agent SDK release and its CLI. Validate actual tool registration, session persistence, interrupt and approval behavior. Use API-key authentication for hosted integration; confirm the selected gateway implements the SDK's model protocol.
2. Consume `agents/{workerIdentity}/runtime/runtime.yaml` and projected role assets. Resolve credentials from bindings; preserve the stable Worker identity. Reject unsupported configuration explicitly.
3. Register the role-specific schema from `plugins/teamharness/mcp/common/task_native.py`. Pass model arguments and framework context separately. Obtain the full SDK tool name from the real registration; do not implement Task mutations through arbitrary Bash commands.
4. Verify Controller coordination notifications before preparing planning, execution, review or completion scope. Use the actual Matrix event ID and authoritative role, Task, Team and process generation.
5. Journal tool admission before effects and save actual terminal receipts with original call IDs. Check prepared output/scratch paths before native writes. A tool error or interruption is not proof of no effect.
6. Persist native inputs and receipts before acknowledging them. Use the shared Matrix ledger and Task checkpoints for recovery; native sessions are optional caches. Discover recoverable Tasks at startup without requiring a new message.
7. Expose cancellation/steering and approval controls with requester, room and run binding. Keep the current permission policy for Bash, file and external MCP tools.
8. Package `agt`, shared libraries, TeamHarness, role assets and the official SDK in the candidate image. Add bounded runtime logs, readiness and real model/tool tracing without credential or content leakage.

## Core follow-up

Use a separate Core branch/PR for runtime validation, member-config projection, backend image selection, coordination/telemetry recognition and build references. Do not publish an invented release tag or enable an unbuilt default image. Keep Manager support disabled until implemented and verified.

## Acceptance

Follow the live guide's frozen-candidate rules. Cover role schema and native hooks with real SDK tests; then run simple/complex tasks (10 each), artifact checks, exact submission review, concurrency/duplicate delivery, cancellation and unknown outcomes. Worker support additionally requires restart recovery, both switch directions and a round trip with retained old sessions/cursors. Record Core/Harness SHAs, SDK/CLI versions, image digests and trace/Task/event links. Distinguish local tests, image smoke, real inference and admission certification in the report.

## Suggested layout

Choose a language before adding build tooling. Keep the native adapter under `src/`, launcher under `scripts/`, native/contract tests under `tests/`, and measured acceptance evidence summaries under `docs/`. Add a Dockerfile and CI once those entrypoints exist. The initial scaffold intentionally has no executable placeholder that could be mistaken for a supported runtime.
