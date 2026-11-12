#!/usr/bin/env python3
"""Run the legacy null replay regression using the runner naming convention."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('llmq-null-replay.py')), run_name='__main__')
