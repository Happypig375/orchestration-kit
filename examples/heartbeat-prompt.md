Read CLAUDE.md and STATE.md. Run bin/orch-heartbeat. Compare the evidence with the last
checkpoint: actual artifacts, commits, test/build output, blocker changes, and budget pace.
A live process or a rewritten STATUS.md is not evidence of progress. For apparent stalls,
read bounded terminal output and assess expected task duration before intervening.

Act within the approved task scope: resume dead pinned parents, relay new human requests,
resolve coordination conflicts, and pause new dispatch if the budget is ahead of pace.
Do not restart a worker whose liveness is uncertain. If capacity retries are exhausted,
inspect the terminal before changing the model or retrying again.

Update STATE.md with handles, evidence, decisions, next checks and remaining budget.
Select active (12m), healthy (30m), or idle (2h) with bin/orch-watch --mode MODE.
Relaunch bin/orch-watch as a background task whose completion wakes this supervisor;
a detached shell alone does not provide a wake notification. Recreate it after restart.
If context has grown substantially, write progress first, then launch
setsid bin/orch-self-compact >/dev/null 2>&1 &
so /compact is submitted only when this session becomes idle.

Recovery timers use two idle/no-watcher strikes before nudging this session. Keep the watcher
armed while waiting. If the IDE and all agents die together, check endpoint-security logs
for terminate/causality events before repeated recovery attempts; follow the playbook's
command-line-text precautions.
