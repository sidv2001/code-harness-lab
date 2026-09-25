# Proposal: a small lab for patient human-AI collaboration

How can a coding assistant remain useful when the work stretches beyond a
single chat? I'm interested in the handoffs: what the model can see, what it
can ask to do, what the person must approve, and what evidence survives when
the context window moves on. I want this project to make those boundaries
visible before adding a clever model. A transcript that looks productive is
not enough; I want to be able to point to a request, a decision, and the
observation that followed it.

The first public starter is deliberately small. A scripted `FakeModel` walks
through a synthetic function whose `add` method subtracts. It asks to list
and read one file, proposes a one-line change, and then finishes. The runner
exposes only typed operations, checks an exact file allowlist, and shows the
diff before requiring the person to type `approve`. It never offers the model
a shell command. An offline run produces a bounded observation, a short
in-run ledger, and a separate append-only JSONL trace. A fresh run cannot
quietly inherit approval or reuse an old trace.

One distinction matters more to me than an impressive demo: applying a patch
is not verifying a fix. This starter has a test-sandbox interface, but no
implementation that executes candidate code. An approved patch is labeled
`unverified`; a refusal leaves the file unchanged. The fixture is copied into
a new local workspace, so the proposal is something to inspect rather than
an edit to a tracked source file. The counters limit model turns and
synthetic cost units, not dollars or model quality.

From here I want to test each layer rather than declaring the system capable.
An isolated, resource-limited test runner should come before real
model-generated edits. A real model would need enforceable call budgets and
careful treatment of untrusted repository text. Longer-horizon memory should
start with a question about what is worth carrying forward, not an automatic
dump of every trace line back into the prompt. Small evaluation tasks and a
simple baseline can show whether added machinery actually helps.

If this becomes a useful collaboration tool, the value should be easy to
explain: the assistant can make a proposal, the person can see and refuse it,
and both can revisit the reasoning without pretending the trace is proof.
For now, I hope the lab makes the interface honest enough to learn from. The
[diagram](diagram.svg) beside this proposal shows the narrow model view, the
decision gates, and the record that stays outside it; a
[text version](diagram.txt) describes the same path.
