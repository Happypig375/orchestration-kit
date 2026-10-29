# Source from the interactive Bash startup file used by IDE-restored tabs.
# Export the same ORCH_* configuration as the user units before sourcing this file.
claude() {
  local kit=${ORCH_HOME:-$HOME/orchestration-kit}
  if [[ $(pwd -P) == "$(cd "$kit" && pwd -P)" ]]; then
    # Wrapper adds the bypass flag and the revive goal as the first message.
    "${ORCH_SUPERVISOR_WRAPPER:-$kit/examples/orch-account-wrapper}" "$@"
  else
    command "${ORCH_CLAUDE_BIN:-$HOME/.local/bin/claude}" "$@"
  fi
}
