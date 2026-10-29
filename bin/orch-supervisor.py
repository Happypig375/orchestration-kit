#!/usr/bin/env python3
"""Profile-aware recovery, account launch, and session pinning for one supervisor."""
import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid


def setting(name, default):
    return os.environ.get(name, str(default))


ROOT = Path(setting('ORCH_HOME', Path(__file__).resolve().parent.parent)).resolve()
STATE = Path(setting('ORCH_STATE_DIR', Path(setting('XDG_CACHE_HOME', Path.home() / '.cache')) / 'orch-heartbeat'))
PROFILE = Path(setting('ORCH_CLAUDE_CONFIG_DIR', Path.home() / '.config/orchestrator-claude')).resolve()
ORCA = setting('ORCH_ORCA', Path.home() / '.local/bin/orca')
TITLE = setting('ORCH_TERMINAL_TITLE', 'orchestrator')
PIN = STATE / 'supervisor-session'


def absolute(value):
    if not Path(value).is_absolute():
        raise ValueError('executable must be an absolute path')
    return value


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def session_id(value):
    return str(uuid.UUID(value.strip()))


def goal():
    return Path(setting('ORCH_REVIVE_GOAL_FILE', ROOT / 'examples/revive-goal.md')).read_text().strip()


def pin_session():
    """SessionStart reports the actual ID, including after in-session resume or clear."""
    data = json.load(sys.stdin)
    if (data.get('hook_event_name') != 'SessionStart' or data.get('agent_id')
            or Path(data['cwd']).resolve() != ROOT
            or Path(os.environ['CLAUDE_CONFIG_DIR']).resolve() != PROFILE):
        return
    atomic_write(PIN, session_id(data['session_id']) + '\n')


def launch(args):
    """Called only through the account wrapper; settings add a hook, not a permission mode."""
    binary = absolute(setting('ORCH_CLAUDE_BIN', Path.home() / '.local/bin/claude'))
    command = shlex.join([sys.executable, str(Path(__file__).resolve()), 'pin'])
    hooks = {'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': command}]}]}}
    hooks_file = STATE / 'supervisor-hooks.json'
    atomic_write(hooks_file, json.dumps(hooks))
    # Restore callers pass options; an optional positional prompt must follow --.
    if '--' in args:
        boundary = args.index('--')
        options, prompt = args[:boundary], '\n'.join(args[boundary + 1:])
    else:
        options, prompt = args, ''
    for index, option in enumerate(options):
        if option in ('--continue', '-c'):
            raise ValueError('implicit latest-session resume is disabled; use a pinned ID')
        if option in ('--resume', '-r', '--session-id'):
            if index + 1 >= len(options):
                raise ValueError('resume requires an explicit session ID')
            session_id(options[index + 1])
        elif option.startswith(('--resume=', '--session-id=')):
            session_id(option.split('=', 1)[1])
    if not any(a in ('--resume', '-r', '--session-id')
               or a.startswith(('--resume=', '--session-id=')) for a in options):
        options += ['--resume', session_id(PIN.read_text())] if PIN.exists() else ['--session-id', str(uuid.uuid4())]
    bypass = setting('ORCH_SKIP_PERMISSIONS_FLAG', '--dangerously-skip-permissions')
    if bypass and bypass not in options:
        options += [bypass]
    message = '\n\n'.join(part for part in (prompt, goal()) if part)
    env = os.environ | {'CLAUDE_CONFIG_DIR': str(PROFILE), 'ORCH_HOME': str(ROOT),
                        'ORCH_STATE_DIR': str(STATE), 'ORCH_CLAUDE_CONFIG_DIR': str(PROFILE)}
    os.chdir(ROOT)
    os.execvpe(binary, [binary, *options, '--settings', str(hooks_file), message], env)


def processes(proc_root=Path('/proc')):
    """Only inspect this user's interactive Claude processes in the supervisor checkout."""
    found = []
    name = setting('ORCH_CLAUDE_PROCESS_NAME', 'claude')
    for proc in proc_root.glob('[0-9]*'):
        try:
            if proc.stat().st_uid != os.getuid() or (proc / 'comm').read_text().strip() != name:
                continue
            if (proc / 'cwd').resolve(strict=True) != ROOT:
                continue
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if any(a in (b'-p', b'--print', b'--agent-id', b'--parent-session-id') for a in args):
                continue
            environ = dict(item.split(b'=', 1) for item in (proc / 'environ').read_bytes().split(b'\0') if b'=' in item)
            profile = environ.get(b'CLAUDE_CONFIG_DIR')
            # Keep the kernel start tick to detect PID reuse before signalling.
            tick = (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]
            found.append({'pid': int(proc.name), 'tick': tick,
                          'correct': profile is not None and Path(os.fsdecode(profile)).resolve() == PROFILE})
        except (FileNotFoundError, ProcessLookupError):
            continue
    return found


def terminate_wrong(proc):
    # Revalidate cwd/profile/start time immediately before a narrowly targeted SIGTERM.
    if proc not in processes():
        raise RuntimeError('supervisor identity changed; refusing to signal')
    os.kill(proc['pid'], signal.SIGTERM)
    for _ in range(100):
        if proc not in processes():
            print('wrong-profile supervisor stopped')
            return
        time.sleep(0.1)
    raise RuntimeError('wrong-profile supervisor did not stop; refusing duplicate launch')


def orca(*args, timeout=30):
    return subprocess.run([absolute(ORCA), *args], check=True, capture_output=True, text=True, timeout=timeout)


def watcher_running():
    with (STATE / 'watch.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def check_idle(proc):
    strikes = STATE / 'idle-strikes.json'
    if watcher_running():
        strikes.unlink(missing_ok=True)
        return
    try:
        terminals = json.loads(orca('terminal', 'list', '--worktree', 'path:' + str(ROOT), '--json').stdout)['result']['terminals']
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        strikes.unlink(missing_ok=True)
        raise
    matching = [t for t in terminals if t.get('title') == TITLE and t.get('writable')]
    if len(matching) != 1:
        strikes.unlink(missing_ok=True)
        print('supervisor terminal identity uncertain; no nudge')
        return
    handle = matching[0]['handle']
    try:
        orca('terminal', 'wait', '--terminal', handle, '--for', 'tui-idle', '--timeout-ms', '1000')
    except (subprocess.SubprocessError, OSError):
        strikes.unlink(missing_ok=True)
        return
    identity = f'{proc["pid"]}:{proc["tick"]}:{handle}'
    try:
        previous = json.loads(strikes.read_text())
    except (FileNotFoundError, ValueError):
        previous = {}
    n = previous.get('count', 0) + 1 if previous.get('identity') == identity else 1
    if n >= int(setting('ORCH_IDLE_STRIKES', 2)):
        # Recheck immediately before input: the watcher may have just been rearmed.
        if not watcher_running():
            orca('terminal', 'send', '--terminal', handle, '--text', goal(), '--enter')
            print('nudged idle supervisor without watcher')
        strikes.unlink(missing_ok=True)
    else:
        atomic_write(strikes, json.dumps({'identity': identity, 'count': n}))
        print('idle without watcher: first strike')


def revive():
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'supervisor.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        current = processes()
        for proc in current:
            if not proc['correct']:
                terminate_wrong(proc)
        current = processes()
        if any(not proc['correct'] for proc in current):
            raise RuntimeError('supervisor identity changed during recovery; retry later')
        if len(current) > 1:
            raise RuntimeError('multiple supervisor processes; refusing automatic action')
        if current:
            check_idle(current[0])
            return
        (STATE / 'idle-strikes.json').unlink(missing_ok=True)
        session = session_id(PIN.read_text())  # Never choose an implicit latest session.
        wrapper = absolute(setting('ORCH_SUPERVISOR_WRAPPER', ROOT / 'examples/orch-account-wrapper'))
        deadline = time.monotonic() + 600
        while True:
            try:
                endpoint = os.environ.get('ORCH_NETWORK_URL')
                if endpoint:
                    subprocess.run(['curl', '-s', '--max-time', '5', '-o', '/dev/null', endpoint], check=True, timeout=6)
                orca('status', timeout=5)
                break
            except (OSError, subprocess.SubprocessError):
                if time.monotonic() >= deadline:
                    raise RuntimeError('network or Orca not ready') from None
                time.sleep(5)
        orca('terminal', 'create', '--worktree', 'path:' + str(ROOT), '--title', TITLE,
             '--command', shlex.join([wrapper, '--resume', session]), '--json')
        print('relaunched pinned supervisor through account wrapper')


if __name__ == '__main__':
    try:
        action = sys.argv[1]
        if action == 'pin':
            pin_session()
        elif action == 'launch':
            launch(sys.argv[2:])
        elif action == 'revive':
            revive()
        else:
            raise ValueError('unknown action')
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'supervisor recovery: {exc}', file=sys.stderr)
        sys.exit(1)
