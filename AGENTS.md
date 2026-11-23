# Implementation instructions

This repository is reserved for the Claude Code integration owner. Implement native Claude Agent SDK behavior here; submit public contract changes to AgentTeams Core. Read `docs/handoff.md` first.

- Use runtime ID `claudecode` and image name `agentteams-harness-claudecode` consistently when registering the candidate in Core.
- Keep Task semantics and schemas in Core. Load the public `task_native.py` role schema and use its trusted-context bridge.
- Keep model arguments separate from framework identity, Matrix sources, role and execution generation.
- Reuse the public recovery, Matrix consumption and delivery layers. Do not translate another Harness's private session format or fork the Task state machine.
- Do not enable nested tools/subagents until their child operations have native admission and terminal receipts.
- Pin Core and SDK inputs. Test against the actual SDK, then run the guide's real-session acceptance before claiming support.
- Keep credentials, private conversations and local runtime artifacts out of git.
- Write runtime prompts and skills directly to the agent as "you".
