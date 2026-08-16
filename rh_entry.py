"""PyInstaller entry point for the standalone `rh` binary."""

import sys

from rh_mcp_cli.cli import main

if __name__ == "__main__":
    sys.exit(main())