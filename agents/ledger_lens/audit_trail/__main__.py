"""Command line: `python -m ledger_lens.audit_trail verify <pack.zip> [--public-key key.pem]`."""

import argparse
import sys
from pathlib import Path

from ledger_lens.audit_trail.pack import verify_pack


def main() -> int:
    parser = argparse.ArgumentParser(prog="ledger_lens.audit_trail")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="verify an audit pack zip")
    verify.add_argument("pack", type=Path)
    verify.add_argument("--public-key", type=Path, help="the lender's published signing key")
    args = parser.parse_args()

    key = args.public_key.read_bytes() if args.public_key else None
    result = verify_pack(args.pack.read_bytes(), trusted_public_key=key)
    status = "VALID" if result.valid else "INVALID"
    print(f"{status}: case {result.case_id}, {result.events} events, signed by {result.signed_by}")
    if result.valid and not result.key_trusted:
        print("  note: checked against the key inside the pack; pass --public-key to prove origin")
    for problem in result.problems:
        print(f"  - {problem}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
