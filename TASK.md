# Public orchestration kit brief

Extract reusable operating guidance and configurable supervision tools for a Claude Code
supervisor coordinating Claude Code and Codex workers through Orca.

Deliver README.md, PLAYBOOK.md, six bin/orch-* tools with shared configuration, example
workers and heartbeat prompt, user service templates, an administrative local-port guard,
a worker task skeleton, and an MIT license.

Keep identities, credentials, private network details, live state and session identifiers
out of repository files and history. Validate shell syntax, run ShellCheck if installed,
exercise tools with an isolated fake Orca runtime, and scan content and commit history for
leaks. Commit locally only. Report files, scan results and generalization limits in the
terminal; do not create a summary file. Finish with KIT DONE.
