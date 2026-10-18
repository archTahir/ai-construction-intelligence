import argparse
import json
import os
from pathlib import Path

from construction_intelligence.exports import export_issue_register_csv, export_state_json
from construction_intelligence.pipeline import analyze_document, register_document
from construction_intelligence.state_store import load_state, save_state


DEFAULT_STATE_PATH = Path("data/state.json")


def print_progress(message: str, completed_count: int, total_count: int) -> None:
    """Print analysis progress for command-line use."""
    print(f"[{completed_count}/{total_count}] {message}")


def import_command(arguments: argparse.Namespace) -> None:
    """Import one PDF into local state."""
    state = load_state(arguments.state)
    document_id, document_added = register_document(state, arguments.pdf)
    save_state(state, arguments.state)
    document_record = state["documents"][document_id]
    result = {
        "document_id": document_id,
        "added": document_added,
        "file_name": document_record["file_name"],
        "meetings": len(document_record["meetings"]),
    }
    print(json.dumps(result, indent=2))


def analyze_command(arguments: argparse.Namespace) -> None:
    """Analyse one imported document."""
    state = load_state(arguments.state)
    document_id = arguments.document_id or next(iter(state["documents"]), None)
    if not document_id:
        raise SystemExit("No imported document is available.")
    if arguments.model:
        state["settings"]["model"] = arguments.model
    api_key = os.getenv("GEMINI_API_KEY", "")
    run_record = analyze_document(
        state=state,
        document_id=document_id,
        state_path=arguments.state,
        api_key=api_key,
        progress_callback=print_progress,
    )
    print(json.dumps(run_record, indent=2))


def status_command(arguments: argparse.Namespace) -> None:
    """Print a concise local project status."""
    state = load_state(arguments.state)
    meeting_count = sum(
        len(document_record["meetings"])
        for document_record in state["documents"].values()
    )
    status = {
        "documents": len(state["documents"]),
        "meetings": meeting_count,
        "issues": len(state["issues"]),
        "pending_reviews": sum(
            review_item.get("status") == "pending"
            for review_item in state["review_queue"]
        ),
        "runs": len(state["runs"]),
    }
    print(json.dumps(status, indent=2))


def export_command(arguments: argparse.Namespace) -> None:
    """Export JSON state and a CSV issue register."""
    state = load_state(arguments.state)
    output_directory = Path(arguments.output)
    json_path = export_state_json(state, output_directory / "construction-intelligence-state.json")
    csv_path = export_issue_register_csv(state, output_directory / "construction-issue-register.csv")
    print(json.dumps({"json": str(json_path), "csv": str(csv_path)}, indent=2))


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    command_parser = argparse.ArgumentParser(prog="construction-intelligence")
    command_parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    subparsers = command_parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("pdf")
    import_parser.set_defaults(handler=import_command)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--document-id")
    analyze_parser.add_argument("--model")
    analyze_parser.set_defaults(handler=analyze_command)

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(handler=status_command)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--output", default="exports")
    export_parser.set_defaults(handler=export_command)
    return command_parser


def main() -> None:
    """Run the command-line interface."""
    command_parser = build_parser()
    command_arguments = command_parser.parse_args()
    command_arguments.handler(command_arguments)


if __name__ == "__main__":
    main()

