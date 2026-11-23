# AgentTeams Claude Code Harness

Integration repository for running Claude Code through the official Claude Agent SDK as an AgentTeams Harness.

**Status: handoff scaffold. No runtime, image or role has been implemented or certified yet.** The assigned Claude Code integration owner will implement the adapter here. This repository does not claim that installing Claude Code alone provides AgentTeams integration.

## Integration boundary

AgentTeams Core owns the public `task/v1` protocol, task state, permissions, artifact delivery and recovery decisions. This repository owns the native SDK integration, trusted Matrix input, session persistence, tool hooks, launch entrypoint, image and native tests.

Start with the [implementation handoff](docs/handoff.md). Read the current [Harness integration guide](https://github.com/agentscope-ai/AgentTeams/blob/main/docs/design/harness-integration-guide.md) before implementing or declaring supported roles.

## References

- [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview)
- [AgentTeams Core](https://github.com/agentscope-ai/AgentTeams)
- [Member runtime configuration](https://github.com/agentscope-ai/AgentTeams/blob/main/docs/design/member-runtime-config-contract.md)
- [Qoder sibling integration](https://github.com/agentteams-group/agentteams-harness-qoder)

Licensed under Apache-2.0; see [LICENSE](LICENSE).
