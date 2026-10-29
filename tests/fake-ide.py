#!/usr/bin/env python3
"""Test-only IDE executable; records argv and never contacts a runtime."""
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with Path(os.environ['FAKE_IDE_LOG']).open('a') as stream:
    stream.write(json.dumps(args) + '\n')
if args[:2] == ['account', 'list']:
    print(json.dumps({'result': {'rateLimits': {'codex': {'weekly': {'usedPercent': 0}}}}}))
elif args[:2] == ['terminal', 'list']:
    print(json.dumps({'result': {'terminals': [{'handle': 'test-terminal', 'title': 'orchestrator', 'writable': True}]}}))
elif args[:2] == ['terminal', 'read']:
    print(os.environ.get('FAKE_SCREEN', 'Selected model is at capacity'))
elif args[:2] == ['terminal', 'send'] and os.environ.get('FAKE_FAIL_SEND'):
    sys.exit(1)
else:
    print('{}')
