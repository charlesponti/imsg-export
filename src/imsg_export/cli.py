"""Command line entry point: `imsg-export <command>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .exporter import ExportError, default_db_path, export_history
from .readme import write_readme
from .verify import verify_export

DEFAULT_TARGET = "~/imessage-export"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imsg-export",
        description="Export macOS Messages.app history — iMessage, SMS and RCS — "
        "to JSONL, CSV and readable transcripts.",
    )
    parser.add_argument("--version", action="version", version=f"imsg-export {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "target",
            nargs="?",
            default=DEFAULT_TARGET,
            help=f"export folder (default: {DEFAULT_TARGET})",
        )
        sub.add_argument(
            "--db",
            default=None,
            help=f"path to chat.db (default: {default_db_path()})",
        )

    export_cmd = subparsers.add_parser("export", help="read chat.db and write the export")
    add_common(export_cmd)
    export_cmd.add_argument(
        "--no-contacts",
        action="store_true",
        help="skip the optional `imsg` lookup that maps handles to contact names",
    )
    export_cmd.add_argument(
        "--readme", action="store_true", help="also write README.md into the export folder"
    )

    verify_cmd = subparsers.add_parser("verify", help="audit an export against chat.db")
    add_common(verify_cmd)

    readme_cmd = subparsers.add_parser("readme", help="regenerate README.md for an export")
    readme_cmd.add_argument("target", nargs="?", default=DEFAULT_TARGET)

    all_cmd = subparsers.add_parser("all", help="export, write the README, then audit")
    add_common(all_cmd)
    all_cmd.add_argument("--no-contacts", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "export":
            summary = export_history(args.target, args.db, use_contacts=not args.no_contacts)
            destination = Path(args.target).expanduser()
            print(f"exported {summary['messages_total']:,} messages to {destination}")
            print(
                f"  {summary['messages_in_chats']:,} in live chats, "
                f"{summary['messages_orphaned']:,} from deleted conversations"
            )
            print(
                f"  attachments: {summary['attachments_copied']:,} copied, "
                f"{summary['attachments_purged']:,} already gone"
            )
            if args.readme:
                write_readme(args.target)
                print("  README.md written")
            return 0

        if args.command == "verify":
            result = verify_export(args.target, args.db)
            print(result.report())
            return 0 if result.ok else 1

        if args.command == "readme":
            path = write_readme(args.target)
            print(f"wrote {path}")
            return 0

        if args.command == "all":
            summary = export_history(args.target, args.db, use_contacts=not args.no_contacts)
            print(f"exported {summary['messages_total']:,} messages")
            target = Path(args.target).expanduser()
            result = verify_export(target, args.db)
            report = result.report()
            print(report)
            (target / "audit.txt").write_text(report + "\n", encoding="utf-8")
            write_readme(target)
            return 0 if result.ok else 1

    except ExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Unreachable: argparse rejects unknown subcommands and the no-command case
    # returns above. Kept as a defensive fallback.
    parser.print_help()  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
