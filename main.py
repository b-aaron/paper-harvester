"""
main.py - Entry point for Paper Harvester.

Run this script directly to launch the interactive CLI::

    python main.py

Or install the package and run::

    paper-harvester
"""

import sys
import os

# Ensure the project root is on the Python path so the harvester package
# can be imported when running `python main.py` from the project directory.
sys.path.insert(0, os.path.dirname(__file__))

from harvester.cli import CLI


def main() -> None:
    """Launch the Paper Harvester interactive CLI."""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
