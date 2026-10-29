"""Isolated recovery tests: no real IDE, agents, signals, services or firewall changes."""
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

KIT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('supervisor', KIT / 'bin/orch-supervisor.py')
SUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUP)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='kit-recovery-')
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.goal = self.root / 'goal.md'
        self.goal.write_text('Read state and rearm the watcher.')
        self.pin = self.state / 'supervisor-session'
        self.session = str(uuid.uuid4())
        self.pin.write_text(self.session + '\n')
        for key, value in {'ROOT': self.root, 'STATE': self.state, 'PIN': self.pin,
                           'PROFILE': self.root / 'profile', 'ORCA': str(self.root / 'ide')}.items():
            mock = patch.object(SUP, key, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.env = {'ORCH_REVIVE_GOAL_FILE': str(self.goal), 'ORCH_SUPERVISOR_WRAPPER': str(self.root / 'wrapper')}
        env_patch = patch.dict(os.environ, self.env)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.proc = {'pid': 999999, 'tick': '123', 'correct': True}

    def ide(self, *args, **kwargs):
        if args[:2] == ('terminal', 'list'):
            output = {'result': {'terminals': [{'handle': 'test-terminal', 'title': 'orchestrator', 'writable': True}]}}
            return subprocess.CompletedProcess(args, 0, json.dumps(output))
        return subprocess.CompletedProcess(args, 0, '{}')

    def test_process_inspection_scopes_profile_and_interactive_parent(self):
        proc_root = self.root / 'proc'
        proc = proc_root / '123456'
        proc.mkdir(parents=True)
        (proc / 'cwd').symlink_to(self.root, target_is_directory=True)
        (proc / 'comm').write_text('claude\n')
        (proc / 'cmdline').write_bytes(b'claude\0')
        (proc / 'environ').write_bytes(('CLAUDE_CONFIG_DIR=' + str(SUP.PROFILE)).encode() + b'\0')
        (proc / 'stat').write_text('123456 (claude) S ' + ' '.join(['0'] * 18 + ['123']))
        self.assertEqual(SUP.processes(proc_root), [{'pid': 123456, 'tick': '123', 'correct': True}])
        (proc / 'environ').write_bytes(b'OTHER_SETTING=value\0')
        self.assertFalse(SUP.processes(proc_root)[0]['correct'])
        (proc / 'cmdline').write_bytes(b'claude\0--print\0task\0')
        self.assertEqual(SUP.processes(proc_root), [])
        (proc / 'cmdline').write_bytes(b'claude\0')
        (proc / 'cwd').unlink()
        (proc / 'cwd').symlink_to(self.state, target_is_directory=True)
        self.assertEqual(SUP.processes(proc_root), [])

    def test_pinned_relaunch_uses_wrapper(self):
        with patch.object(SUP, 'processes', return_value=[]), patch.object(SUP, 'orca', side_effect=self.ide) as ide:
            SUP.revive()
        call = ide.call_args_list[-1].args
        command = shlex.split(call[call.index('--command') + 1])
        self.assertEqual(command, [self.env['ORCH_SUPERVISOR_WRAPPER'], '--resume', self.session])

    def test_invalid_pin_refuses_relaunch(self):
        self.pin.write_text('invalid')
        with patch.object(SUP, 'processes', return_value=[]), patch.object(SUP, 'orca') as ide:
            with self.assertRaises(ValueError):
                SUP.revive()
        ide.assert_not_called()

    def test_wrong_profile_stops_before_launch(self):
        wrong = self.proc | {'correct': False}
        with patch.object(SUP, 'processes', side_effect=[[wrong], []]), \
             patch.object(SUP, 'terminate_wrong') as terminate, patch.object(SUP, 'orca', side_effect=self.ide):
            SUP.revive()
        terminate.assert_called_once_with(wrong)

    def test_termination_revalidates_identity_and_waits(self):
        wrong = self.proc | {'correct': False}
        with patch.object(SUP, 'processes', side_effect=[[wrong], []]), patch.object(SUP.os, 'kill') as kill:
            SUP.terminate_wrong(wrong)
        kill.assert_called_once_with(wrong['pid'], SUP.signal.SIGTERM)
        with patch.object(SUP, 'processes', return_value=[]), patch.object(SUP.os, 'kill') as kill:
            with self.assertRaises(RuntimeError):
                SUP.terminate_wrong(wrong)
            kill.assert_not_called()

    def test_unstopped_wrong_profile_refuses_duplicate(self):
        wrong = self.proc | {'correct': False}
        with patch.object(SUP, 'processes', return_value=[wrong]), patch.object(SUP.os, 'kill'), \
             patch.object(SUP.time, 'sleep'), patch.object(SUP, 'orca') as ide:
            with self.assertRaises(RuntimeError):
                SUP.revive()
        ide.assert_not_called()

    def test_idle_nudge_requires_two_strikes(self):
        with patch.object(SUP, 'orca', side_effect=self.ide) as ide:
            SUP.check_idle(self.proc)
            self.assertFalse(any(call.args[:2] == ('terminal', 'send') for call in ide.call_args_list))
            SUP.check_idle(self.proc)
            sends = [call for call in ide.call_args_list if call.args[:2] == ('terminal', 'send')]
            self.assertEqual(len(sends), 1)
            self.assertIn(self.goal.read_text(), sends[0].args)
        self.assertFalse((self.state / 'idle-strikes.json').exists())

    def test_watcher_and_busy_state_reset_strikes(self):
        with patch.object(SUP, 'orca', side_effect=self.ide):
            SUP.check_idle(self.proc)
        with (self.state / 'watch.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch.object(SUP, 'orca') as ide:
                SUP.check_idle(self.proc)
                ide.assert_not_called()
        self.assertFalse((self.state / 'idle-strikes.json').exists())
        with patch.object(SUP, 'orca', side_effect=self.ide):
            SUP.check_idle(self.proc)
        def busy(*args):
            if args[:2] == ('terminal', 'wait'):
                raise subprocess.CalledProcessError(1, args)
            return self.ide(*args)
        with patch.object(SUP, 'orca', side_effect=busy):
            SUP.check_idle(self.proc)
        self.assertFalse((self.state / 'idle-strikes.json').exists())

    def test_recovery_lock_blocks_duplicate_run(self):
        with (self.state / 'supervisor.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch.object(SUP, 'processes') as processes:
                SUP.revive()
                processes.assert_not_called()

    def test_hook_keeps_actual_session_current(self):
        new_session = str(uuid.uuid4())
        data = {'hook_event_name': 'SessionStart', 'cwd': str(self.root), 'session_id': new_session}
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(SUP.PROFILE)}), \
             patch('sys.stdin', io.StringIO(json.dumps(data))):
            SUP.pin_session()
        self.assertEqual(self.pin.read_text().strip(), new_session)
        data['agent_id'] = 'child'
        data['session_id'] = str(uuid.uuid4())
        with patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(SUP.PROFILE)}), \
             patch('sys.stdin', io.StringIO(json.dumps(data))):
            SUP.pin_session()
        self.assertEqual(self.pin.read_text().strip(), new_session)

    def test_launch_profile_flag_hook_and_first_message(self):
        with patch.object(SUP.os, 'chdir'), patch.object(SUP.os, 'execvpe') as launch:
            SUP.launch(['--resume', self.session, '--', 'Extra task'])
        binary, args, env = launch.call_args.args
        self.assertTrue(Path(binary).is_absolute())
        self.assertIn('--dangerously-skip-permissions', args)
        self.assertEqual(args[-1], 'Extra task\n\n' + self.goal.read_text())
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(SUP.PROFILE))
        hooks = json.loads((self.state / 'supervisor-hooks.json').read_text())
        self.assertEqual(set(hooks), {'hooks'})
        hook = hooks['hooks']['SessionStart'][0]['hooks'][0]['command']
        self.assertEqual(shlex.split(hook)[-1], 'pin')

    def test_workers_hold_flock_and_reject_relative_ide(self):
        env = os.environ | {'ORCH_HOME': str(KIT), 'ORCH_STATE_DIR': str(self.state),
                           'ORCH_WORKERS': str(self.root / 'workers.tsv'), 'ORCH_ORCA': str(self.root / 'ide')}
        # A missing runtime would fail if the shared lock did not stop the invocation.
        (self.root / 'workers.tsv').write_text('')
        with (self.state / 'resume.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = subprocess.run([str(KIT / 'bin/orch-resume-workers')], env=env, capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 0)
        result = subprocess.run([str(KIT / 'bin/orch-resume-workers')], env=env | {'ORCH_ORCA': 'orca'},
                                capture_output=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'absolute', result.stderr)

    def test_implicit_resume_is_rejected(self):
        for options in (['--continue'], ['--resume'], ['--resume', 'invalid']):
            with self.subTest(options=options), patch.object(SUP.os, 'execvpe') as launch:
                with self.assertRaises(ValueError):
                    SUP.launch(options)
                launch.assert_not_called()

    def test_ambiguous_terminal_and_failed_read_reset_strikes(self):
        with patch.object(SUP, 'orca', side_effect=self.ide):
            SUP.check_idle(self.proc)
        with patch.object(SUP, 'orca', side_effect=subprocess.CalledProcessError(1, ['fake'])):
            with self.assertRaises(subprocess.CalledProcessError):
                SUP.check_idle(self.proc)
        self.assertFalse((self.state / 'idle-strikes.json').exists())
        def ambiguous(*args):
            return subprocess.CompletedProcess(args, 0, json.dumps({'result': {'terminals': []}}))
        with patch.object(SUP, 'orca', side_effect=self.ide):
            SUP.check_idle(self.proc)
        with patch.object(SUP, 'orca', side_effect=ambiguous):
            SUP.check_idle(self.proc)
        self.assertFalse((self.state / 'idle-strikes.json').exists())

    def test_shell_function_only_routes_supervisor_checkout(self):
        shell = 'source "$1"; cd "$2"; claude --resume "$4"; cd "$3"; claude --help'
        wrapper = self.root / 'wrapper-recorder'
        wrapper.write_text((KIT / 'tests/fake-ide.py').read_text().replace('FAKE_IDE_LOG', 'FAKE_WRAPPER_LOG'))
        wrapper.chmod(0o755)
        env = os.environ | {'ORCH_HOME': str(self.root),
                            'ORCH_SUPERVISOR_WRAPPER': str(wrapper),
                            'FAKE_WRAPPER_LOG': str(self.root / 'wrapper.log'),
                            'ORCH_CLAUDE_BIN': str(KIT / 'tests/fake-ide.py'),
                            'FAKE_IDE_LOG': str(self.root / 'shell.log')}
        result = subprocess.run(['bash', '-c', shell, 'shell-test',
                                 str(KIT / 'examples/orchestrator-shell.bash'), str(self.root),
                                 str(KIT), self.session], env=env, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in (self.root / 'shell.log').read_text().splitlines()]
        self.assertEqual(calls, [['--help']])
        wrapper_calls = [json.loads(line) for line in (self.root / 'wrapper.log').read_text().splitlines()]
        self.assertEqual(wrapper_calls, [['--resume', self.session]])

    def test_original_helpers_with_fake_runtime(self):
        worker = self.root / 'worker with spaces'
        worker.mkdir()
        registry = self.root / 'workers.tsv'
        registry.write_text(f'codex\t{worker}\tworker title\n')
        (worker / '.codex-parent-session').write_text(self.session)
        env = os.environ | {'ORCH_HOME': str(KIT), 'ORCH_STATE_DIR': str(self.state),
                            'ORCH_ORCA': str(KIT / 'tests/fake-ide.py'),
                            'ORCH_WORKERS': str(registry), 'ORCH_CAPACITY_MAX': '2',
                            'ORCH_COMPACT_DELAY': '0', 'ORCH_POLL_SECONDS': '0.05',
                            'FAKE_IDE_LOG': str(self.root / 'calls.jsonl')}
        def run(name, *args, extra=None):
            result = subprocess.run([str(KIT / 'bin' / name), *args], env=env | (extra or {}),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        self.assertIn('weekly=', run('orch-usage'))
        run('orch-capacity-retry', extra={'FAKE_FAIL_SEND': '1'})
        counter = self.state / 'capacity/test-terminal'
        self.assertFalse(counter.exists())
        run('orch-capacity-retry')
        run('orch-capacity-retry')
        self.assertIn('EXHAUSTED', run('orch-capacity-retry'))
        self.assertIn('WAKE capacity', run('orch-watch'))
        run('orch-capacity-retry', extra={'FAKE_SCREEN': 'ready'})
        self.assertFalse(counter.exists())
        (worker / 'NEEDS-HUMAN.md').write_text('request one\n')
        self.assertIn('newest work file: none', run('orch-heartbeat'))
        self.assertNotIn('request one', run('orch-heartbeat'))
        run('orch-resume-workers')
        transcript = self.root / 'transcripts'
        transcript.mkdir()
        (transcript / 'test.jsonl').write_text('test\n')
        self.assertIn('compact sent', run('orch-self-compact', '--force',
                      extra={'ORCH_TRANSCRIPT_DIR': str(transcript)}))
        self.assertEqual((self.state / 'compact-size').read_text().strip(), '5')
        calls = [json.loads(line) for line in (self.root / 'calls.jsonl').read_text().splitlines()]
        create = next(call for call in calls if call[:2] == ['terminal', 'create'])
        self.assertIn(self.session, shlex.split(create[create.index('--command') + 1]))
        self.assertNotIn('--last', create[create.index('--command') + 1])

    def test_timers_have_five_minute_cadence(self):
        for name in ('orchestrator', 'orch-resume-workers'):
            data = (KIT / 'examples/systemd' / (name + '.timer')).read_text()
            self.assertIn('OnUnitActiveSec=5min', data)
            self.assertIn('Unit=' + name + '.service', data)


if __name__ == '__main__':
    unittest.main()
