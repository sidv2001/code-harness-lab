# Design of the first starter

The loop is `FakeModel -> typed request -> workspace policy -> human gate (for
patches) -> bounded observation -> next model call`. A separate local trace
records every reserved call, tool request and observation, patch application,
and run outcome. The model receives only the objective, latest observation,
and a rolling ledger, never the trace file or an accumulated transcript.

## Current boundaries

| Boundary | Behavior in this starter |
| --- | --- |
| Model | Deterministic script; it does not reason about the file it reads. Exhaustion without `finish` raises an error. |
| Requests | `list`, `read`, `propose_patch`, `ask_human`, and `finish` are distinct dataclasses. There is no shell or network tool. |
| Files | Only direct, plain allowlisted basenames in the generated workspace; no symlinks or multiply linked files. Reads require UTF-8 and cap files at 4,096 bytes. Patch text rejects terminal control/formatting characters. A patch must match the whole current file, fit that cap, produce a displayable diff, and still match after approval. The replacement is staged in the same directory. |
| Human decision | Patch approval shows the diff and requires the exact word `approve`. Answering an `ask_human` question does not approve a patch. With no approval gate, requests are denied and recorded. |
| Model context | Objective: at most 240 characters. Latest observation: at most 640 characters. Ledger: at most three summaries of 96 characters each. File/diff and question/answer limits are enforced separately. |
| Budget | Up to five model turns and five **synthetic** cost units by default, with one unit reserved before each scripted call. These are not token or dollar estimates. |
| Test boundary | `TestSandbox` is a typed interface. The shipped `UnavailableSandbox` raises `SandboxUnavailable`, yielding `NOT RUN` and `unverified` after an edit. A caller-supplied trusted adapter could return a typed pass or failure; none is shipped. |
| Trace and restart | `trace.jsonl` is created exclusively outside the model-visible workspace, written append-only with owner-only permissions, and never reopened for a resumed run. It is a local record, not tamper-evident storage. A new run gets a new trace and new approval decision. An incomplete trace indicates an interrupted/erroring run, not a success. |

The logical file policy and local temp workspace are not OS-enforced isolation
against hostile code or concurrent adversarial filesystem writers. Candidate
code is never executed by this starter. Python and `pytest` do execute the
trusted harness and its tests on the host.

## Why these seams

Typed requests separate a model's suggestion from permission to act. The
whole-file precondition lets the person approve the diff they actually saw;
if the file changes while they decide, the edit is refused. The observation
and ledger are intentionally narrower than the append-only trace, which can
be inspected without automatically becoming the next prompt. The sandbox
interface makes test provenance visible: a model's `finish` note cannot turn
an untested patch into a verified one.

Tests cover traversal, symlinks/hardlinks, stale patches, denials, context and
budget bounds, the unavailable test boundary, malformed adapter results, and
fresh-run invariants. See [roadmap](roadmap.md) for the capabilities still to
be built.
