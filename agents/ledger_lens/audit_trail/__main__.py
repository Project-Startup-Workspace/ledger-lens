"""Command line: `python -m ledger_lens.audit_trail verify <pack.zip>`."""

import argparse
import sys
from pathlib import Path

from ledger_lens.audit_trail.pack import verify_pack


def main() -> int:
    parser = argparse.ArgumentParser(prog="ledger_lens.audit_trail")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="verify an audit pack zip")
    verify.add_argument("pack", type=Path)
    args = parser.parse_args()

    result = verify_pack(args.pack.read_bytes())
    status = "VALID" if result.valid else "INVALID"
    print(f"{status}: case {result.case_id}, {result.events} events")
    for problem in result.problems:
        print(f"  - {problem}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
