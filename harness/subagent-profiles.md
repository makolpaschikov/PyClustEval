# Specialist model profiles

Use this policy when the analyst or harness maintainer assigns one of the four
specialists below. It records the human-approved choices in
[DEC-010](signals/DECISIONS.md#dec-010); it is not a model performance ranking.
Other roles retain their existing model/inheritance rules.

## Allowed choices

Every combination of a model and reasoning effort within a row is authorized.

| Role | Models | Reasoning effort | Who selects |
| --- | --- | --- | --- |
| Code scout | `gpt-6.1-terra`, `gpt-6.1-sol` | `high`, `xhigh` | Authorized caller |
| Internet scout | `gpt-6.1-sol`, `gpt-6-astra` | `medium`, `high`, `xhigh` | Authorized caller |
| Specification validator | `gpt-6.1-sol`, `gpt-6-astra` | `high`, `xhigh` | Analyst |
| Specification auditor | `gpt-6.1-sol`, `gpt-6-astra` | `high`, `xhigh` | Analyst |

The analyst may invoke all four roles. The maintainer may invoke scouts for
authorized harness investigation and simulate analyst assignments for isolated
harness verification. Developer/reviewer requests for assistance still go through
the analyst; profile availability does not grant delegation authority.

Choose by the assignment's ambiguity, breadth, interacting constraints and
consequences of an incorrect conclusion. Do not impose fixed model/effort pairings
or automatically choose the highest effort. Record the selected pair and a brief
task-specific reason in the existing assignment or evidence, not a separate tracker.
An agent assigned both specification skills must satisfy both rows.

Use the host's exposed model identifiers and supported effort values. If the
selected pair is unavailable, the caller may select another permitted pair and
report the change. If no permitted pair can be selected, return the limitation
for a decision; do not silently inherit, use a different family/version, or claim
that an unsupported override took effect. Changing these authorized sets is a
harness change requiring human agreement.

## Explicit invocation and context

The collaboration interface checked on 2026-11-13 accepts `model` and
`reasoning_effort` on `spawn_agent` with `fork_turns: "none"`. Full-history forks
inherit the parent's settings and do not accept overrides. Use a fresh subagent
with both explicit values for these roles; inspect the exposed interface again
if the host changes. This is a tool-call contract, not a `config.toml` schema.

Pass the absolute skill path and require it to be read before work. Supply a
self-contained assignment: repository/checkout, concrete question and task/spec
version when applicable, original request evidence needed by the role, input
paths, actual authority and scope, scientific invariants, allowed commands and
side effects, resource limits, output destination and expected evidence. A fresh
worker has no parent conversation; a reference to "our agreement" is insufficient.
Relevant files outside its checkout need explicit authorized paths.

These roles are skills read by ordinary subagents, not registered host agent
types. Instruction boundaries do not create an independent filesystem sandbox.
For independent checks, provide necessary raw evidence without preferred answers,
suspected defects or the caller's conclusions. Retain actual worker identity.

Record requested settings and whether launch succeeded. Report effective settings
only when the host exposes authoritative runtime metadata; an agent's assertion
about its own model is not such evidence. Do not infer quality from model identity
or a successful launch. Do not reuse an agent's identity as a fresh independent
reviewer, or assume follow-up calls changed its model/effort.

The workers read this policy to check the assignment and report missing or
incompatible settings to the caller; they do not change settings or launch agents.
The caller owns selection and any necessary replacement, preserving independence
and avoiding duplicate work. Full behavior and handoff requirements live in the
role skills and [delegation contract](../.agents/skills/analyst-orchestrator/references/delegation.md).

## Documentation and limits

[Official subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents)
describes explicit model/reasoning selection and inheritance.
[Model selection](https://developers.openai.com/api/docs/guides/model-selection)
and [reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning)
describe general tradeoffs; they do not establish performance on PyClustEval.
The exact fork restriction above comes from this session's tool interface.
No global settings, dependencies or application permissions are changed by this policy.
