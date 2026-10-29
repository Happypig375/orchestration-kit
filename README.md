# Orchestration kit

A small, adaptable kit for a Claude Code supervisor coordinating Codex and Claude Code
workers through Orca terminals. It combines reboot recovery, bounded capacity retries,
usage summaries, context maintenance, and adaptive supervision. Read [PLAYBOOK.md](PLAYBOOK.md)
for the operating policy and [examples/TASK.md](examples/TASK.md) for a worker assignment.
There is no hosted service, account configuration, or live worker state in this repository.

## Prerequisites

Use Linux with Bash, Python 3, Git, GNU coreutils/findutils, procps, util-linux (`flock`,
`setsid`), curl, and systemd user units. Install and authenticate the Orca CLI, Claude Code,
and Codex CLI separately. Orca needs a running runtime (`orca open` or your existing
`orca-serve.service`). The CLI must support terminal list/read/send/wait/create, account
list, and project setup-delete. Check your installed versions' `--help` before deployment;
these scripts use the source environment's Orca JSON shape and Codex `--no-daemon` flag.
ShellCheck is optional for development. The port-guard example additionally needs
iptables and ip6tables and administrator installation.

## Quick start

1. Put the checkout at `$HOME/orchestration-kit`, or adapt all unit paths to its location.
   Set `export ORCH_HOME="$HOME/orchestration-kit"` and add `"$ORCH_HOME/bin"` to PATH.
   Register it and each worker checkout with `orca repo add --path "$ORCH_HOME"` (repeat
   with each worker path).
2. Copy `examples/workers.tsv` to `workers.tsv`. Replace commented examples with literal
   tab-separated `agent`, absolute checkout path, terminal title rows. Supported agents
   are `codex` and `claude`; spaces in paths/titles are allowed, tabs/newlines are not.
   Values are literal: `$HOME` and `~` in a registry are not expanded. Resolve checkout
   symlinks to canonical paths so process working-directory checks agree.
3. Start each worker interactively in its registered checkout. Record the actual parent
   session ID in `.codex-parent-session` or `.claude-parent-session` in that checkout.
   Keep those files out of that project's Git history. Do not invent IDs, record child
   sessions, or register two parents in the same checkout.
4. Copy the relevant playbook rules into a private `CLAUDE.md` and initialize a private
   `STATE.md` with task ownership, handles, evidence checkpoints and pending decisions.
   Start the supervisor in the kit checkout through Orca, with the terminal title
   `orchestrator` and a separate `CLAUDE_CONFIG_DIR`. Authenticate that configuration
   first. Record its pinned session ID in `$ORCH_STATE_DIR/supervisor-session`; create
   that directory first (default `$HOME/.cache/orch-heartbeat`).
5. Run `bin/orch-heartbeat` for an initial evidence snapshot. Instruct the supervisor to
   follow `examples/heartbeat-prompt.md` and run `bin/orch-watch` as a background task
   whose completion wakes its session. A watcher exits after one wake; rearm it after
   each review. `bin/orch-watch --mode active` selects the initial 12-minute interval.
6. For reboot recovery, copy `examples/systemd/*.service` to
   `$HOME/.config/systemd/user/`. Create `$HOME/.config/orchestration-kit/environment`
   with absolute values such as `ORCH_ORCA=/opt/orca/bin/orca` and your actual
   `ORCH_TRANSCRIPT_DIR`. systemd environment files do not expand shell variables.
   Run `systemctl --user daemon-reload`, then
   `systemctl --user enable orchestrator.service orch-resume-workers.service`.
   Test each with `systemctl --user start UNIT` after configuring pinned sessions.
   Arrange user lingering with your administrator if startup must work before login.

The units run launch checks at startup; their oneshot success does not mean the terminal
process remains alive. Orca owns those processes. The supervisor must recreate its watcher
and monitor recovery. Startup retries readiness for up to approximately ten minutes;
readiness failure is reported and must be retried after connectivity/runtime recovery.
The units expect an existing `orca-serve.service`; adapt ordering to your runtime setup.
They never install services, change networking, or change account credentials themselves.

## Configuration

Export shell variables for interactive use; set matching values in the user units'
environment file for reboot recovery. `ORCH_HOME` defaults to the checkout containing
`bin/`. All tools share these settings unless marked otherwise:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ORCH_HOME` | kit checkout | Supervisor checkout and companion tools |
| `ORCH_WORKERS` | `$ORCH_HOME/workers.tsv` | Private tab-separated parent registry |
| `ORCH_STATE_DIR` | `${XDG_CACHE_HOME:-$HOME/.cache}/orch-heartbeat` | Counters, locks and snapshots |
| `ORCH_ORCA` | `orca` | Orca executable path; one executable, no arguments |
| `ORCH_TERMINAL_TITLE` | `orchestrator` | Exact supervisor terminal title for compaction |
| `ORCH_TRANSCRIPT_DIR` | `$ORCH_HOME/transcripts` | Actual Claude project directory containing JSONL transcripts |
| `ORCH_HUMAN_QUEUE` | empty (disabled) | Optional append-only human request queue |
| `ORCH_BACKUP_UNIT` | empty (disabled) | Optional user backup service whose Result is reported |
| `ORCH_BACKUP_TIMER` | empty (disabled) | Optional backup timer whose last trigger is reported |
| `ORCH_INBOX_DIR` | empty (disabled) | Optional inbox directory whose files are counted |
| `ORCH_CAPACITY_MAX` | `10` | Consecutive successful continue submissions per terminal |
| `ORCH_POLL_SECONDS` | `60` | Watch polling and retry interval in seconds |
| `ORCH_COMPACT_BYTES` | `1500000` | Transcript growth required for compaction |
| `ORCH_COMPACT_DELAY` | `20` | Seconds before waiting for supervisor idle |
| `ORCH_NETWORK_URL` | empty (disabled) | Optional HTTPS readiness endpoint for resume scripts |
| `ORCH_CODEX_BIN` | `codex` | Codex executable for workers |
| `ORCH_CLAUDE_BIN` | `claude` | Claude Code executable for workers and supervisor |
| `ORCH_CLAUDE_CONFIG_DIR` | unset | Dedicated supervisor profile; required by startup example |

Find the actual transcript directory under the chosen Claude configuration rather than
assuming a profile layout. The compactor selects its newest JSONL file, tracks submitted
compactions by byte count, waits for `tui-idle`, and types `/compact` through Orca. Use
`setsid bin/orch-self-compact >/dev/null 2>&1 &`; `--force` bypasses the size threshold.
A submitted compaction is not proof it completed; verify from the session. If transcripts
rotate or shrink, remove the private `compact-size` checkpoint after checking the session.

## Tool behavior and limits

- `orch-watch`: event fingerprints for registry, worker liveness, STATUS/NEEDS-HUMAN and
  optional queue; mode intervals active 12m, healthy 30m, idle 2h. Events are polled, so
  detection can lag a minute. Any disappearance/change wakes review; rearm afterward.
- `orch-heartbeat`: usage, process hints, status excerpts, appended human requests,
  newest work-file age, latest commit, dirty-file count and latest build/test artifact.
  A 45-minute gap is a stall *hint*, not a stop rule. Inspect diffs and test results.
  Metadata scans may be costly on large trees; adapt exclusions to the repository.
  Human queues should be append-only: rotation/truncation resets the line checkpoint,
  while same-length edits do not count as appended requests.
- `orch-capacity-retry`: inspects only the last bounded terminal output, sends `continue`
  for an idle-looking capacity message, counts successful submissions, and wakes review
  at the cap. Counts reset once the error disappears. The UI heuristic is not a formal
  agent state API; use one registered parent terminal per checkout and inspect false hits.
- `orch-resume-workers`: checks current-user process names and working directories,
  then resumes pinned parent IDs. Claude workers clear the supervisor's profile variable
  and use their default authenticated configuration. Profiles beyond this arrangement
  require adapting the registry/launcher. Native children have no registry row.
- `orch-usage`: prints rate-window usage and resets without account identities. Available
  windows depend on Orca's account JSON. Unexpected schemas require adapting the parser.
- `orch-common.sh`: shared settings, not a standalone command. Watchers and helpers use
  the same exported overrides; run only one watcher per supervisor.

Current-user process checks, advisory launch locks and terminal UI heuristics cannot prove
worker identity or eliminate all startup races. If identity is uncertain, inspect Orca and
session evidence before relaunching. No helper runs automatically until you wire it into
your own runtime and supervisor workflow.

See `examples/localguard` for a reviewed administrative pattern, not an installer. Set
`ORCH_SERVICE_USER` and `ORCH_GUARD_PORTS` to your own account and private TCP ports. Keep
runtime registries, transcripts, credentials, and state private; the supplied `.gitignore`
is only a starting point. License: [MIT](LICENSE).
