"""Explicit synthetic-tracking entry point; copy publication stays restricted."""
from pathlib import Path
import sys
from .github_release import run

if __name__ == '__main__':
    run(sys.argv[1], Path('candidate-bundle'), Path('index.html'), tracking=True)
