# Research notes: sources, choices, and open questions

These primary sources informed the design; they are not dependencies or
evidence that this lab achieves the results described in the papers.

| Reading | Design question it raises here |
| --- | --- |
| Anthropic, [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) and [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Start with a legible, simple loop. Limit and choose what enters the model's context; do not treat a long transcript as free memory. This starter uses a scripted model and a short ledger. |
| [SWE-agent](https://arxiv.org/abs/2405.15793) | The agent-computer interface matters. Here the interface is five typed requests, not an open shell. No SWE-agent performance is claimed. |
| [Agentless](https://arxiv.org/abs/2407.01489) and [SWE-bench](https://arxiv.org/abs/2310.06770) | A simpler baseline and a defined task/evaluation method matter before adding orchestration. There is no benchmark score or candidate-code test result yet. |
| OpenAI, [Codex approvals and security](https://developers.openai.com/codex/agent-approvals-security), and [AgentDojo](https://arxiv.org/abs/2406.13352) | Treat approval, isolation, and untrusted text as different concerns. This starter has an approval gate and file allowlist, but no OS sandbox or adversarial evaluation. |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [MemGPT](https://arxiv.org/abs/2310.08560), [LongMemEval](https://arxiv.org/abs/2410.10813), and [Reflexion](https://arxiv.org/abs/2303.11366) | Durable state, selective recall, long-horizon evaluation, and reflection are separate design questions. The local trace is an audit artifact, not implemented long-term agent memory. |
| Docker [rootless mode](https://docs.docker.com/engine/security/rootless/), [none network driver](https://docs.docker.com/engine/network/drivers/none/), and [seccomp profiles](https://docs.docker.com/engine/security/seccomp/) | Possible ingredients for a future Linux test runner, with explicit permissions and resource limits. Docker is not invoked by this project; platform-specific isolation needs its own review and tests. |

The immediate experiment is inspectability: can we see a typed request,
policy decision, human choice, bounded feedback, and persistent trace without
confusing any of them with a verified fix? The [roadmap](roadmap.md) turns the
unanswered questions into concrete gates before adding a real model.
