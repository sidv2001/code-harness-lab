# Roadmap: earn each added capability

**Now — implemented:** a deterministic offline model script, one synthetic
fixture, typed tools, an exact file allowlist, patch approval, bounded in-run
context, synthetic turn/cost limits, a separate append-only trace, and
fail-closed `NOT RUN` test reporting. There is no measured fixing ability.

**Next — isolated verification:** implement a trusted test adapter that runs
candidate code away from the host with no credentials or network, a read-only
test harness, limited CPU/memory/time, and explicit teardown. Review the
platform-specific isolation design rather than assuming a container flag is
enough. Acceptance gate: prove a denied escape attempt cannot access a host
sentinel; test timeouts, failures, and missing isolation without falling back
to host execution. Only then should `verified` mean a real test result.

**Then — model and evaluation:** add an optional real-model adapter that
accepts only the typed schema, treats repository text as untrusted data, and
reserves enforceable request/token/cost budgets before calls. Keep the offline
script as a reproducible baseline. Define small tasks with known expected
behavior and compare against a simpler non-agent approach; publish the task
set, test provenance, failure cases, and limits before reporting any rate.

**Later — selective continuity:** experiment with summaries or retrieval from
local traces only after specifying privacy, provenance, and invalidation rules.
Fresh-run approval must still be required. Evaluate whether recalled context
improves longer tasks without exposing secrets or carrying stale claims into
the next decision.
