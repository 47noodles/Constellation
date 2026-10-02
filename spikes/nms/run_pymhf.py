"""Run `pymhf run nmspy` without a Windows console, logging to a file.

pyMHF builds questionary prompts at import time, which needs a real console.
The prompts are never asked once pymhf.local.toml exists, so a dummy output
is enough.
"""

import builtins
import sys
import threading

import prompt_toolkit.output.defaults as _defaults

# pyMHF's interactive ">>>" prompt reads stdin; with no console that is an
# immediate EOF, which pyMHF treats as "quit" and kills the game. Block instead.
_never = threading.Event()
builtins.input = lambda *a, **k: _never.wait() or ""
from prompt_toolkit.output import DummyOutput

_defaults.create_output = lambda *a, **k: DummyOutput()
import prompt_toolkit.shortcuts.prompt as _prompt  # noqa: E402

_prompt.create_output = _defaults.create_output

import pymhf  # noqa: E402

sys.argv = ["pymhf", "run", "nmspy"]
pymhf.run()
