# Operating playbook

## Triage before dispatch

Start with a bounded triage pass over the authorized work queue and existing artifacts.
Identify dependencies, duplicates, obsolete tasks and missing acceptance criteria. Propose
reordering, merges and drops before launching a batch. Obtain approval when the batch or
tracker changes require it; existing authorization remains valid. A supervisor coordinates
and reviews; give expensive implementation and deep analysis to workers when delegation
is authorized. Do not modify a tracker merely because it is available.

Give every task an objective, scope, ownership, budget, concrete acceptance evidence and
human escalation path. Keep one persistent parent per project checkout. Native children
share that checkout: assign file ownership and serialize overlapping edits. Use isolated
worktrees when isolation is necessary, not as a substitute for coordination.

## Route by measured pool behavior

Maintain a private routing table of accounts, available rate windows, prompt-cache TTL,
observed token speed and cost. Query `orch-usage` before dispatch and compare it with the
remaining work and reset times. These properties vary by provider, plan, model and date;
measure them rather than publishing one account's entitlements as universal facts.

| Work pattern | Pool characteristics to prefer |
| --- | --- |
| Long unattended jobs and resumes after idle gaps | Long cache retention, generous long-duration windows |
| Short interactive bursts | High token speed and available short-window capacity |
| Bulk transforms, tests, routine refactors | Fast capable model, low/medium effort |
| Planning, subtle debugging, architecture and final review | Strong reasoning model with enough budget |
| Coordination | Separate modest budget, bounded terminal reads and small summaries |

A pool with both a short rolling window and a weekly limit can stall despite weekly
headroom. A longer-cache pool can tolerate idle gaps more economically. Separately metered
model buckets can be overflow routes only if the task and permissions fit. Spread work
across reset windows; do not retry-storm a blocked pool or unavailable network.

Treat effort as a separate dial from model size. Use a ladder of inexpensive helper → fast
implementation worker → general reasoning worker → strongest reviewer. Escalate after an
observable failure, and record which model/effort solved each task type. Low/medium suits
mechanical work; high suits substantive design and debugging; xhigh suits subtle multi-step
reasoning. Reserve max for demonstrated hard cases or a failed lower-effort attempt, and
avoid it for long autonomous loops. Require explicit authorization for ultra. Large thinking
budgets can turn one slow-token-model turn into many minutes; effort is not free even when
fast output hides the latency. Bind concrete model names to this ladder locally.

## Context, caching and durable handoff

Prefer one fresh session per task. Keep handoff state in authorized tracker entries or repo
notes, so sessions can be replaced without losing decisions. Every turn carries context;
a large cached session still has costs. Increase context windows only for tasks requiring
wide code awareness. Compact earlier for mechanical work. Verify version-specific context
and auto-compaction settings against the installed CLI before changing them.

Write progress before compaction: ownership, exact session ID, changes, test results,
blockers, pending decisions and the next executable step. Compaction can lose details;
re-read durable state afterward. Do not rely on a hidden conversation as the only record.
For Claude self-compaction, launch `orch-self-compact` detached after writing state. It waits
for the identified Orca terminal to become idle, then types `/compact` into that session.
A model merely deciding to summarize is not equivalent to the CLI's compaction command.

Budget cache misses explicitly. Short retention favors finishing a burst before a long idle
gap; longer retention suits intermittent unattended work. Do not spend hourly heartbeat
turns solely to keep a cache warm when a less frequent cache miss costs less overall.

## Endpoint security and simultaneous failures

Some endpoint detection and response agents match **command-line text**, not just executed
behavior. For example, Cortex XDR's `python_encoded_command` behavioral rule can kill the
whole causality tree: IDE, agents and their units. Never run a Python one-liner that decodes
and executes code, or executes code read from standard input. Never quote such a one-liner
inside a shell command, heredoc, commit message or terminal message either: its text alone
can trigger the rule. Describe the pattern only in words. Copy a plain `.py` file and run
it by path instead; parsing data from standard input is distinct from executing it.

If everything dies at once, inspect the endpoint-security logs for terminate/causality
events before blaming the model or repeatedly restarting. Use your administrator's normal
log-access procedure; do not disable or evade endpoint security.

## Reboots and pinned parents

Orca may restore tabs without restarting agents. Keep a private workers.tsv with one parent
per checkout and pinned `.codex-parent-session` or `.claude-parent-session` files. Use exact
session IDs on resume; never use `--last`, which can select a native child or unrelated
session. The kit deliberately strengthens the source's Claude latest-session fallback by
requiring a pinned Claude parent too.

Order user units after the Orca runtime, wait for readiness with bounded retries, and keep
supervisor authentication separate from worker authentication. Invoke the IDE CLI by
absolute path so an unrelated system command cannot shadow it. Use an account wrapper for
supervisor launch and tab restore; supply the bypass CLI flag and a revive goal as the first
message. A directory-scoped shell function fixes IDE tab restoration that otherwise selects
a default profile with no prompt. Do not set a bypass default mode in settings: its startup
dialog can block unattended recovery. Maintain the current pin from SessionStart events.

Run supervisor and worker recovery services from five-minute timers. Hold a flock throughout
each recovery run so manual and timer invocations cannot double-launch. In the dedicated
supervisor checkout, stop a confirmed wrong-profile process and wait before resuming the
pinned parent through its wrapper. Two consecutive checks finding a correctly profiled
supervisor idle with no watcher justify a goal nudge; busy/unknown state resets the count.
Check process identity and checkout before resuming. If an existing process cannot be identified confidently, inspect
it before creating another. Preserve task state in repos or an authorized tracker; an
Orca workspace and a local session are not backups. Recreate session-only watches after
reboot or supervisor restart.

## Adaptive, evidence-based supervision

Run a background watcher that wakes the supervisor on worker disappearance, registry or
human-request changes, status updates, exhausted retries, or the mode deadline. Use active
12m during startup, migration or trouble; healthy 30m for productive long jobs; idle 2h
when work is waiting. These intervals are defaults to calibrate, not service guarantees.
The watcher polls and exits once; the supervisor must review and rearm it. A platform
background-task completion notification supplies the wake. An optional coarse scheduled
heartbeat can recover from a lost watcher, but do not run two competing supervisors.

At each wake, read only bounded output and compare durable evidence against the previous
checkpoint: changed implementation/artifacts, meaningful commits and diffs, actual build
or test logs and results. A running process, recent STATUS rewrite or touching a file is
not proof of progress. A new log's timestamp alone does not prove the build passed. The
heartbeat's 45-minute work-file gap is a hint; long computation may be healthy with no file
writes. Check terminal output, expected runtime, CPU/log evolution and known blockers
before intervening. Revive a confirmed dead worker; correct drift with a concrete message.

Record evidence checkpoints and actions in STATE.md. Calculate budget pace from consumption
since the last checkpoint versus time until reset and work remaining. Pause new dispatch
when ahead of budget, reduce effort where appropriate, and route to another authorized
pool only when evidence supports it. Keep coordination checks short.

For the specific idle `model at capacity` stop, submit `continue` at the polling interval,
with a cap of ten consecutive successful submissions per terminal. Reset only when the
capacity message clears. Once exhausted, wake the supervisor for inspection, a pause, or
an authorized model change. A failed send does not consume a retry; transport ambiguity
still requires inspection. Do not treat arbitrary errors or a busy agent as permission to
send input repeatedly.

## Two-supervisor migration

Use one shared durable state file as a coordination ledger, with an explicit current
owner and migration phase. Agree on a single writer or a lock; two simultaneous appenders
are not an ownership protocol.

1. The outgoing supervisor records tasks, parent IDs, live handles, file ownership,
   pending decisions, watcher jobs and last verified evidence. It freezes dispatch and
   writes: `MIGRATION IN PROGRESS — don't touch until MIGRATION DONE`.
2. The incoming supervisor reads the snapshot but does not send worker input, resume
   parents, change registries or touch shared work until the completion marker appears.
3. The outgoing supervisor stops its watchers and relinquishes ownership, then writes
   `MIGRATION DONE` with the designated new owner and checkpoint. Keep workers running
   unless a separate task requires stopping them.
4. The incoming supervisor claims ownership, checks live identities and artifacts against
   the snapshot, records the new handles, and rearms exactly one watcher. It acknowledges
   completion in the ledger. If interrupted before the marker, ask the owner/human to
   resolve ownership; a timeout is not permission to take over.

Archive the ledger after a completed handoff. Never launch a second parent from an inactive
archive merely because its directory still exists.

## Worker etiquette and shared notes

Maintain one private machine-notes file with network routes, permitted resources, data
locations, recovery steps and shared-server etiquette. Symlink it to
`~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md`; merge or preserve existing files before
replacing them. Review it when the environment changes, and ensure alternate Claude
configuration directories load the relevant notes too. Bound CPU parallelism, use `nice`
for large jobs, avoid filling shared disks, and clean up owned scratch. Keep local
metadata databases closed to concurrent writes; use supported read-only exports/APIs and
separate attachment backups with verified restores. Do not expose private backup endpoints
or provider details in a public kit.

## Archive before removing Orca projects

Before cleanup, save uncommitted work, required artifacts, logs and parent IDs to an approved
private archive. Confirm the intended checkout has no live terminals with
`"$ORCH_ORCA" terminal list --worktree "path:$CHECKOUT" --json`. Stop or transfer owned workers first.
Inspect `"$ORCH_ORCA" project setups --json`, select the intended setup and run
`"$ORCH_ORCA" project setup-delete --setup "$SETUP_ID"`. Use `--force` only after reviewing saved
workspace details. This unregisters the setup; it is distinct from deleting a directory.
There is no `orca repo rm` command in the CLI this kit targets; verify future CLI changes
before adapting. Delete an archived checkout only when deletion itself is authorized.

## Human browser checks

For sites requiring interactive verification, use a headed browser on Xvfb, with a window
manager and a restricted noVNC view for the human. Automation works in background tabs;
only a challenge needing a human comes to the foreground. Report a precise human-action
request and keep the browser process running. Never solve, bypass or evade CAPTCHAs or bot
checks. Close only automation-owned tabs when finished, keeping unrelated human tabs intact.
Treat browser automation ports as privileged: isolate the profile and do not expose CDP
to a public interface. Prefer authentication even on a private overlay network.

## Network patterns to adapt with an administrator

An allowlisted egress proxy can run as a separate system user so policy routing selects an
authorized egress path. Bind it to loopback, enforce destination and CONNECT-port
allowlists, reject unapproved redirects/destinations, and account for DNS resolution and
requester isolation. Use it per command (`curl -x http://127.0.0.1:3129 URL`) or per browser
profile, never as a global HTTPS_PROXY. Domain lists, entitlement configuration and system
service details belong in private deployment configuration. This kit does not supply a
proxy implementation or change any routing.

A tailnet-only listener can still be reached by other local users. The localguard example
rejects loopback TCP connections to chosen ports unless the originating UID owns the
service, for both IPv4 and IPv6. It leaves tailnet ingress untouched; use overlay ACLs,
bind restrictions and authentication for remote access. It does not protect other
interfaces, UDP, Unix sockets or privileged users. Review rule ordering, firewall backend
and service restart/boot persistence with an administrator. Never apply firewall changes
as part of routine agent setup without authorization.

For kill-switch exit-node routing, send ordinary external traffic through the chosen
private-overlay exit node and fail closed when it disappears. Explicitly route only
approved local/private destinations directly. Validate IPv4, IPv6 and DNS behavior;
otherwise fallback routes can bypass the intended policy. Workers should wait with bounded
backoff while the exit node is unavailable. Document recovery privately; do not bake a
machine name, address, user identity or institutional network range into reusable scripts.
