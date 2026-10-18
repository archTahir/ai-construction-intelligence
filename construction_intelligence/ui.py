import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from construction_intelligence.exports import export_issue_register_csv, export_state_json
from construction_intelligence.gemini_analysis import test_gemini_connection
from construction_intelligence.pipeline import (
    analyze_document,
    find_review_item,
    register_document,
    resolve_match_review,
)
from construction_intelligence.state_store import load_state, save_state


APPLICATION_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = APPLICATION_ROOT / "data" / "state.json"
DEFAULT_EXPORT_DIRECTORY = APPLICATION_ROOT / "exports"


def replace_text(text_widget: tk.Text, content: str) -> None:
    """Replace read-only text widget content."""
    text_widget.configure(state="normal")
    text_widget.delete("1.0", "end")
    text_widget.insert("1.0", content)
    text_widget.configure(state="disabled")


def clear_tree(tree_widget: ttk.Treeview) -> None:
    """Remove every row from a tree view."""
    tree_widget.delete(*tree_widget.get_children())


def get_all_meetings(state: dict) -> list[dict]:
    """Return all imported meeting records."""
    return [
        meeting_record
        for document_record in state["documents"].values()
        for meeting_record in document_record["meetings"]
    ]


def refresh_overview(application_context: dict) -> None:
    """Refresh overview indicators and major issues."""
    state = application_context["state"]
    meetings = get_all_meetings(state)
    issues = state["issues"]
    active_issues = [
        issue_record
        for issue_record in issues.values()
        if issue_record.get("status") not in {"closed_verified", "superseded"}
    ]
    commercial_issues = [
        issue_record
        for issue_record in issues.values()
        if "commercial" in issue_record.get("category", "").lower()
        or "contract" in issue_record.get("category", "").lower()
    ]
    approval_issues = [
        issue_record
        for issue_record in active_issues
        if any(
            approval_word in str(issue_record.get("current_assessment", {}).get("approval_status", "")).lower()
            for approval_word in ["pending", "under", "not", "rejected", "unknown"]
        )
    ]
    recurring_issues = [
        issue_record
        for issue_record in issues.values()
        if len(issue_record.get("meeting_ids", [])) > 1
    ]
    indicator_values = {
        "meetings": str(sum(meeting.get("analysis_status") == "complete" for meeting in meetings)),
        "active": str(len(active_issues)),
        "commercial": str(len(commercial_issues)),
        "approvals": str(len(approval_issues)),
        "recurring": str(len(recurring_issues)),
        "reviews": str(sum(item.get("status") == "pending" for item in state["review_queue"])),
    }
    for indicator_name, indicator_value in indicator_values.items():
        application_context["indicator_variables"][indicator_name].set(indicator_value)

    overview_tree = application_context["overview_tree"]
    clear_tree(overview_tree)
    significance_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ordered_issues = sorted(
        active_issues,
        key=lambda issue_record: (
            significance_order.get(issue_record.get("significance", "low"), 4),
            issue_record.get("issue_id", ""),
        ),
    )
    for issue_record in ordered_issues[:40]:
        overview_tree.insert(
            "",
            "end",
            iid=issue_record["issue_id"],
            values=(
                issue_record["issue_id"],
                issue_record.get("title"),
                issue_record.get("discipline"),
                issue_record.get("status"),
                issue_record.get("significance"),
                issue_record.get("last_discussed"),
            ),
        )


def refresh_issue_register(application_context: dict) -> None:
    """Refresh the complete issue register."""
    issue_tree = application_context["issue_tree"]
    clear_tree(issue_tree)
    for issue_id, issue_record in sorted(application_context["state"]["issues"].items()):
        issue_tree.insert(
            "",
            "end",
            iid=issue_id,
            values=(
                issue_id,
                issue_record.get("title"),
                issue_record.get("discipline"),
                issue_record.get("category"),
                issue_record.get("status"),
                issue_record.get("significance"),
                issue_record.get("last_discussed"),
            ),
        )


def refresh_documents(application_context: dict) -> None:
    """Refresh imported documents and meeting statuses."""
    document_tree = application_context["document_tree"]
    clear_tree(document_tree)
    for document_id, document_record in application_context["state"]["documents"].items():
        document_tree.insert(
            "",
            "end",
            iid=document_id,
            values=(
                document_record.get("file_name"),
                "Document",
                document_record.get("page_count"),
                document_record.get("analysis_status"),
            ),
            open=True,
        )
        for meeting_index, meeting_record in enumerate(document_record["meetings"]):
            meeting_tree_id = f"{document_id}|{meeting_index}"
            document_tree.insert(
                document_id,
                "end",
                iid=meeting_tree_id,
                values=(
                    meeting_record.get("meeting_id"),
                    meeting_record.get("meeting_date") or "Unknown date",
                    meeting_record.get("page_count"),
                    meeting_record.get("analysis_status"),
                ),
            )


def refresh_reviews(application_context: dict) -> None:
    """Refresh the human review queue."""
    review_tree = application_context["review_tree"]
    clear_tree(review_tree)
    for review_item in application_context["state"]["review_queue"]:
        review_tree.insert(
            "",
            "end",
            iid=review_item["review_id"],
            values=(
                review_item.get("review_type"),
                review_item.get("meeting_id"),
                review_item.get("status"),
                review_item.get("created_at", "")[:19],
            ),
        )


def refresh_activity(application_context: dict) -> None:
    """Refresh processing activity and usage details."""
    runs = application_context["state"]["runs"]
    activity_content = json.dumps(runs[-10:], indent=2, ensure_ascii=False)
    replace_text(application_context["activity_text"], activity_content or "No processing runs yet.")


def refresh_application(application_context: dict) -> None:
    """Refresh every dashboard view."""
    refresh_overview(application_context)
    refresh_issue_register(application_context)
    refresh_documents(application_context)
    refresh_reviews(application_context)
    refresh_activity(application_context)


def format_issue_details(issue_record: dict) -> str:
    """Format a persistent issue for human review."""
    current_assessment = issue_record.get("current_assessment", {})
    detail_lines = [
        f"{issue_record.get('issue_id')} | {issue_record.get('title')}",
        "",
        f"Discipline: {issue_record.get('discipline')}",
        f"Category: {issue_record.get('category')}",
        f"Status: {issue_record.get('status')}",
        f"Significance: {issue_record.get('significance')}",
        f"First reported: {issue_record.get('first_reported')}",
        f"Last discussed: {issue_record.get('last_discussed')}",
        "",
        "Current assessment",
        current_assessment.get("summary", ""),
        "",
        f"System: {current_assessment.get('system') or 'Unknown'}",
        f"Component: {current_assessment.get('component') or 'Unknown'}",
        f"Location: {current_assessment.get('location') or 'Unknown'}",
        f"Approval status: {current_assessment.get('approval_status') or 'Unknown'}",
        f"Evidence status: {current_assessment.get('evidence_status') or 'Unknown'}",
        "",
        "Recommended verification",
        current_assessment.get("recommended_verification", ""),
        "",
        "Full record",
        json.dumps(issue_record, indent=2, ensure_ascii=False),
    ]
    return "\n".join(detail_lines)


def show_selected_issue(application_context: dict, tree_widget: ttk.Treeview) -> None:
    """Display the selected issue details."""
    selected_items = tree_widget.selection()
    if not selected_items:
        return
    issue_id = selected_items[0]
    issue_record = application_context["state"]["issues"].get(issue_id)
    if issue_record:
        replace_text(
            application_context["issue_detail_text"],
            format_issue_details(issue_record),
        )


def show_selected_document(application_context: dict) -> None:
    """Display selected document or meeting metadata."""
    selected_items = application_context["document_tree"].selection()
    if not selected_items:
        return
    selected_identifier = selected_items[0]
    if "|" in selected_identifier:
        document_id, meeting_index_text = selected_identifier.split("|", 1)
        document_record = application_context["state"]["documents"][document_id]
        selected_record = document_record["meetings"][int(meeting_index_text)]
    else:
        selected_record = application_context["state"]["documents"][selected_identifier]
    replace_text(
        application_context["document_detail_text"],
        json.dumps(selected_record, indent=2, ensure_ascii=False),
    )


def show_selected_review(application_context: dict) -> None:
    """Display the selected review item."""
    selected_items = application_context["review_tree"].selection()
    if not selected_items:
        return
    selected_review_id = selected_items[0]
    selected_review = next(
        (
            review_item
            for review_item in application_context["state"]["review_queue"]
            if review_item["review_id"] == selected_review_id
        ),
        None,
    )
    if selected_review:
        replace_text(
            application_context["review_detail_text"],
            json.dumps(selected_review, indent=2, ensure_ascii=False),
        )


def selected_review_id(application_context: dict) -> str | None:
    """Return the selected review identifier."""
    selected_items = application_context["review_tree"].selection()
    return selected_items[0] if selected_items else None


def resolve_selected_review(application_context: dict, resolution: str) -> None:
    """Resolve the selected review item with an explicit decision."""
    review_id = selected_review_id(application_context)
    if not review_id:
        messagebox.showinfo("No review selected", "Select a review item first.")
        return
    try:
        review_item = find_review_item(application_context["state"], review_id)
        target_issue_id = None
        if resolution == "merged":
            review_candidates = review_item.get("candidates", [])
            if not review_candidates:
                raise ValueError("This review item has no merge candidate.")
            target_issue_id = review_candidates[0]["issue_id"]
        resolve_match_review(
            application_context["state"],
            review_id,
            resolution,
            target_issue_id,
        )
        save_state(application_context["state"], application_context["state_path"])
        refresh_application(application_context)
        application_context["status_variable"].set("Review decision saved.")
    except Exception as review_error:
        messagebox.showerror("Review could not be resolved", str(review_error))


def import_pdf(application_context: dict) -> None:
    """Import a PDF selected through the operating-system file picker."""
    selected_file = filedialog.askopenfilename(
        title="Import meeting minutes",
        filetypes=[("PDF documents", "*.pdf")],
    )
    if not selected_file:
        return
    application_context["status_variable"].set("Reading PDF...")
    application_context["root"].update_idletasks()
    try:
        document_id, document_added = register_document(
            application_context["state"],
            selected_file,
        )
        save_state(application_context["state"], application_context["state_path"])
        refresh_application(application_context)
        if document_added:
            document_record = application_context["state"]["documents"][document_id]
            application_context["status_variable"].set(
                f"Imported {document_record['file_name']} with {len(document_record['meetings'])} meeting(s)."
            )
        else:
            application_context["status_variable"].set("This document was already imported.")
    except Exception as import_error:
        application_context["status_variable"].set("Import failed.")
        messagebox.showerror("Import failed", str(import_error))


def selected_document_id(application_context: dict) -> str | None:
    """Return the selected document identifier or the first pending document."""
    selected_items = application_context["document_tree"].selection()
    if selected_items:
        return selected_items[0].split("|", 1)[0]
    for document_id, document_record in application_context["state"]["documents"].items():
        if document_record.get("analysis_status") != "complete":
            return document_id
    return next(iter(application_context["state"]["documents"]), None)


def save_settings(application_context: dict) -> None:
    """Save non-secret analysis settings."""
    model_name = application_context["model_variable"].get().strip()
    if not model_name:
        raise ValueError("A Gemini model name is required.")
    state_settings = application_context["state"]["settings"]
    state_settings["model"] = model_name
    state_settings["analysis_depth"] = application_context["depth_variable"].get()
    state_settings["enabled_specialists"] = [
        specialist_name
        for specialist_name, enabled_variable in application_context["specialist_variables"].items()
        if enabled_variable.get()
    ]
    state_settings["maximum_meetings_per_run"] = int(
        application_context["meeting_limit_variable"].get()
    )
    save_state(application_context["state"], application_context["state_path"])


def post_progress(
    application_context: dict,
    message: str,
    completed_count: int,
    total_count: int,
) -> None:
    """Post a worker progress event to the interface queue."""
    application_context["message_queue"].put(
        {
            "type": "progress",
            "message": message,
            "completed": completed_count,
            "total": total_count,
        }
    )


def analysis_worker(
    application_context: dict,
    document_id: str,
    api_key: str,
) -> None:
    """Run document analysis outside the Tkinter event thread."""
    try:
        run_record = analyze_document(
            state=application_context["state"],
            document_id=document_id,
            state_path=application_context["state_path"],
            api_key=api_key,
            progress_callback=lambda message, completed, total: post_progress(
                application_context,
                message,
                completed,
                total,
            ),
        )
        application_context["message_queue"].put(
            {"type": "analysis_complete", "run": run_record}
        )
    except Exception as analysis_error:
        application_context["message_queue"].put(
            {"type": "error", "message": str(analysis_error)}
        )


def start_analysis(application_context: dict) -> None:
    """Start analysis for the selected document."""
    document_id = selected_document_id(application_context)
    if not document_id:
        messagebox.showinfo("No document", "Import a meeting PDF before starting analysis.")
        return
    try:
        save_settings(application_context)
    except Exception as settings_error:
        messagebox.showerror("Invalid settings", str(settings_error))
        return
    api_key = application_context["api_key_variable"].get().strip() or os.getenv(
        "GEMINI_API_KEY",
        "",
    )
    if not api_key:
        messagebox.showerror("API key required", "Enter a Gemini API key in Settings.")
        return
    application_context["analysis_button"].configure(state="disabled")
    application_context["progress_bar"].configure(value=0, maximum=1)
    application_context["status_variable"].set("Starting analysis...")
    threading.Thread(
        target=analysis_worker,
        args=(application_context, document_id, api_key),
        daemon=True,
    ).start()


def connection_worker(application_context: dict, api_key: str, model_name: str) -> None:
    """Test Gemini access outside the Tkinter event thread."""
    try:
        display_name = test_gemini_connection(api_key, model_name)
        application_context["message_queue"].put(
            {
                "type": "connection_complete",
                "message": f"Connected to {display_name}.",
            }
        )
    except Exception as connection_error:
        application_context["message_queue"].put(
            {"type": "error", "message": str(connection_error)}
        )


def start_connection_test(application_context: dict) -> None:
    """Start a Gemini connection test."""
    api_key = application_context["api_key_variable"].get().strip() or os.getenv(
        "GEMINI_API_KEY",
        "",
    )
    model_name = application_context["model_variable"].get().strip()
    if not api_key or not model_name:
        messagebox.showerror("Configuration required", "Enter an API key and model name.")
        return
    application_context["status_variable"].set("Testing Gemini connection...")
    threading.Thread(
        target=connection_worker,
        args=(application_context, api_key, model_name),
        daemon=True,
    ).start()


def process_interface_messages(application_context: dict) -> None:
    """Apply background worker events on the Tkinter event thread."""
    try:
        while True:
            interface_message = application_context["message_queue"].get_nowait()
            message_type = interface_message["type"]
            if message_type == "progress":
                total_count = max(interface_message["total"], 1)
                application_context["progress_bar"].configure(maximum=total_count)
                application_context["progress_bar"].configure(
                    value=interface_message["completed"]
                )
                application_context["status_variable"].set(interface_message["message"])
            elif message_type == "analysis_complete":
                application_context["analysis_button"].configure(state="normal")
                refresh_application(application_context)
                run_record = interface_message["run"]
                application_context["status_variable"].set(
                    f"Analysis finished: {run_record['status']}."
                )
            elif message_type == "connection_complete":
                application_context["status_variable"].set(interface_message["message"])
                messagebox.showinfo("Gemini connection", interface_message["message"])
            elif message_type == "error":
                application_context["analysis_button"].configure(state="normal")
                application_context["status_variable"].set("Operation failed.")
                messagebox.showerror("Operation failed", interface_message["message"])
    except queue.Empty:
        pass
    application_context["root"].after(
        200,
        process_interface_messages,
        application_context,
    )


def export_json(application_context: dict) -> None:
    """Export complete application state to a selected JSON file."""
    DEFAULT_EXPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_path = filedialog.asksaveasfilename(
        title="Export state",
        initialdir=DEFAULT_EXPORT_DIRECTORY,
        initialfile="construction-intelligence-state.json",
        defaultextension=".json",
        filetypes=[("JSON files", "*.json")],
    )
    if output_path:
        export_state_json(application_context["state"], output_path)
        application_context["status_variable"].set(f"Exported {Path(output_path).name}.")


def export_csv(application_context: dict) -> None:
    """Export the issue register to a selected CSV file."""
    DEFAULT_EXPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output_path = filedialog.asksaveasfilename(
        title="Export issue register",
        initialdir=DEFAULT_EXPORT_DIRECTORY,
        initialfile="construction-issue-register.csv",
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv")],
    )
    if output_path:
        export_issue_register_csv(application_context["state"], output_path)
        application_context["status_variable"].set(f"Exported {Path(output_path).name}.")


def create_indicator_card(
    parent: ttk.Frame,
    column_index: int,
    label: str,
    value_variable: tk.StringVar,
) -> None:
    """Create one overview indicator card."""
    indicator_frame = ttk.Frame(parent, padding=12, style="Card.TFrame")
    indicator_frame.grid(row=0, column=column_index, padx=5, pady=5, sticky="nsew")
    parent.columnconfigure(column_index, weight=1)
    ttk.Label(indicator_frame, textvariable=value_variable, style="Metric.TLabel").pack()
    ttk.Label(indicator_frame, text=label, style="Card.TLabel").pack()


def create_overview_tab(application_context: dict, notebook: ttk.Notebook) -> None:
    """Create the project intelligence overview tab."""
    overview_tab = ttk.Frame(notebook, padding=12)
    notebook.add(overview_tab, text="Overview")
    indicator_frame = ttk.Frame(overview_tab)
    indicator_frame.pack(fill="x")
    indicators = [
        ("meetings", "Meetings analysed"),
        ("active", "Active issues"),
        ("commercial", "Commercial matters"),
        ("approvals", "Approval concerns"),
        ("recurring", "Recurring issues"),
        ("reviews", "Human reviews"),
    ]
    for column_index, (indicator_name, indicator_label) in enumerate(indicators):
        create_indicator_card(
            indicator_frame,
            column_index,
            indicator_label,
            application_context["indicator_variables"][indicator_name],
        )
    ttk.Label(overview_tab, text="Priority issue register", style="Section.TLabel").pack(
        anchor="w",
        pady=(14, 6),
    )
    overview_tree = ttk.Treeview(
        overview_tab,
        columns=("id", "title", "discipline", "status", "significance", "meeting"),
        show="headings",
    )
    overview_tree.pack(fill="both", expand=True)
    column_configuration = [
        ("id", "ID", 90),
        ("title", "Issue", 360),
        ("discipline", "Discipline", 150),
        ("status", "Status", 150),
        ("significance", "Significance", 110),
        ("meeting", "Last meeting", 110),
    ]
    for column_name, column_label, column_width in column_configuration:
        overview_tree.heading(column_name, text=column_label)
        overview_tree.column(column_name, width=column_width, anchor="w")
    overview_tree.bind(
        "<Double-1>",
        lambda event: show_selected_issue(application_context, overview_tree),
    )
    application_context["overview_tree"] = overview_tree


def create_issue_tab(application_context: dict, notebook: ttk.Notebook) -> None:
    """Create the complete issue register and detail tab."""
    issue_tab = ttk.Frame(notebook, padding=12)
    notebook.add(issue_tab, text="Issues")
    issue_pane = ttk.Panedwindow(issue_tab, orient="horizontal")
    issue_pane.pack(fill="both", expand=True)
    issue_tree = ttk.Treeview(
        issue_pane,
        columns=("id", "title", "discipline", "category", "status", "significance", "meeting"),
        show="headings",
    )
    issue_detail_text = tk.Text(issue_pane, wrap="word", state="disabled", padx=10, pady=10)
    issue_pane.add(issue_tree, weight=3)
    issue_pane.add(issue_detail_text, weight=2)
    column_configuration = [
        ("id", "ID", 85),
        ("title", "Issue", 280),
        ("discipline", "Discipline", 120),
        ("category", "Category", 150),
        ("status", "Status", 130),
        ("significance", "Priority", 90),
        ("meeting", "Last", 80),
    ]
    for column_name, column_label, column_width in column_configuration:
        issue_tree.heading(column_name, text=column_label)
        issue_tree.column(column_name, width=column_width, anchor="w")
    issue_tree.bind(
        "<<TreeviewSelect>>",
        lambda event: show_selected_issue(application_context, issue_tree),
    )
    application_context["issue_tree"] = issue_tree
    application_context["issue_detail_text"] = issue_detail_text


def create_document_tab(application_context: dict, notebook: ttk.Notebook) -> None:
    """Create the document and meeting status tab."""
    document_tab = ttk.Frame(notebook, padding=12)
    notebook.add(document_tab, text="Documents")
    document_pane = ttk.Panedwindow(document_tab, orient="horizontal")
    document_pane.pack(fill="both", expand=True)
    document_tree = ttk.Treeview(
        document_pane,
        columns=("name", "type", "pages", "status"),
        show="tree headings",
    )
    document_tree.heading("#0", text="")
    document_tree.column("#0", width=30)
    for column_name, column_label, column_width in [
        ("name", "Document or meeting", 320),
        ("type", "Date or type", 160),
        ("pages", "Pages", 70),
        ("status", "Status", 150),
    ]:
        document_tree.heading(column_name, text=column_label)
        document_tree.column(column_name, width=column_width, anchor="w")
    document_detail_text = tk.Text(
        document_pane,
        wrap="word",
        state="disabled",
        padx=10,
        pady=10,
    )
    document_pane.add(document_tree, weight=2)
    document_pane.add(document_detail_text, weight=3)
    document_tree.bind(
        "<<TreeviewSelect>>",
        lambda event: show_selected_document(application_context),
    )
    application_context["document_tree"] = document_tree
    application_context["document_detail_text"] = document_detail_text


def create_review_tab(application_context: dict, notebook: ttk.Notebook) -> None:
    """Create the human review queue tab."""
    review_tab = ttk.Frame(notebook, padding=12)
    notebook.add(review_tab, text="Review queue")
    review_pane = ttk.Panedwindow(review_tab, orient="horizontal")
    review_pane.pack(fill="both", expand=True)
    review_tree = ttk.Treeview(
        review_pane,
        columns=("type", "meeting", "status", "created"),
        show="headings",
    )
    for column_name, column_label, column_width in [
        ("type", "Review type", 220),
        ("meeting", "Meeting", 100),
        ("status", "Status", 100),
        ("created", "Created", 160),
    ]:
        review_tree.heading(column_name, text=column_label)
        review_tree.column(column_name, width=column_width, anchor="w")
    review_detail_text = tk.Text(
        review_pane,
        wrap="word",
        state="disabled",
        padx=10,
        pady=10,
    )
    review_pane.add(review_tree, weight=2)
    review_pane.add(review_detail_text, weight=3)
    review_button_frame = ttk.Frame(review_tab)
    review_button_frame.pack(fill="x", pady=(8, 0))
    ttk.Button(
        review_button_frame,
        text="Create new issue",
        command=lambda: resolve_selected_review(application_context, "new_issue"),
    ).pack(side="left", padx=(0, 6))
    ttk.Button(
        review_button_frame,
        text="Merge strongest candidate",
        command=lambda: resolve_selected_review(application_context, "merged"),
    ).pack(side="left", padx=6)
    ttk.Button(
        review_button_frame,
        text="Dismiss",
        command=lambda: resolve_selected_review(application_context, "dismissed"),
    ).pack(side="left", padx=6)
    review_tree.bind(
        "<<TreeviewSelect>>",
        lambda event: show_selected_review(application_context),
    )
    application_context["review_tree"] = review_tree
    application_context["review_detail_text"] = review_detail_text


def create_settings_tab(application_context: dict, notebook: ttk.Notebook) -> None:
    """Create Gemini and analysis settings."""
    settings_tab = ttk.Frame(notebook, padding=20)
    notebook.add(settings_tab, text="Settings")
    settings_tab.columnconfigure(1, weight=1)
    ttk.Label(settings_tab, text="Gemini API key").grid(row=0, column=0, sticky="w", pady=8)
    ttk.Entry(
        settings_tab,
        textvariable=application_context["api_key_variable"],
        show="•",
        width=70,
    ).grid(row=0, column=1, sticky="ew", padx=12, pady=8)
    ttk.Label(settings_tab, text="Model").grid(row=1, column=0, sticky="w", pady=8)
    ttk.Entry(
        settings_tab,
        textvariable=application_context["model_variable"],
    ).grid(row=1, column=1, sticky="ew", padx=12, pady=8)
    ttk.Label(settings_tab, text="Analysis depth").grid(row=2, column=0, sticky="w", pady=8)
    ttk.Combobox(
        settings_tab,
        textvariable=application_context["depth_variable"],
        values=["standard", "detailed"],
        state="readonly",
    ).grid(row=2, column=1, sticky="w", padx=12, pady=8)
    ttk.Label(settings_tab, text="Maximum meetings per run").grid(
        row=3,
        column=0,
        sticky="w",
        pady=8,
    )
    ttk.Spinbox(
        settings_tab,
        from_=1,
        to=100,
        textvariable=application_context["meeting_limit_variable"],
        width=8,
    ).grid(row=3, column=1, sticky="w", padx=12, pady=8)
    ttk.Label(settings_tab, text="Specialist analysis").grid(
        row=4,
        column=0,
        sticky="nw",
        pady=8,
    )
    specialist_frame = ttk.Frame(settings_tab)
    specialist_frame.grid(row=4, column=1, sticky="w", padx=12, pady=8)
    specialist_labels = {
        "engineering": "Engineering",
        "contract_commercial": "Contract and commercial",
        "programme_procurement": "Programme and procurement",
        "quality_compliance": "Quality and compliance",
    }
    for specialist_name, specialist_label in specialist_labels.items():
        ttk.Checkbutton(
            specialist_frame,
            text=specialist_label,
            variable=application_context["specialist_variables"][specialist_name],
        ).pack(anchor="w", pady=2)
    button_frame = ttk.Frame(settings_tab)
    button_frame.grid(row=5, column=1, sticky="w", padx=12, pady=18)
    ttk.Button(
        button_frame,
        text="Test connection",
        command=lambda: start_connection_test(application_context),
    ).pack(side="left", padx=(0, 8))
    ttk.Button(
        button_frame,
        text="Save settings",
        command=lambda: save_settings(application_context),
    ).pack(side="left")
    ttk.Label(
        settings_tab,
        text="The API key is used in memory only and is never saved to state.json.",
    ).grid(row=6, column=1, sticky="w", padx=12)


def create_activity_tab(application_context: dict, notebook: ttk.Notebook) -> None:
    """Create the processing activity tab."""
    activity_tab = ttk.Frame(notebook, padding=12)
    notebook.add(activity_tab, text="Activity")
    activity_text = tk.Text(activity_tab, wrap="word", state="disabled", padx=10, pady=10)
    activity_text.pack(fill="both", expand=True)
    application_context["activity_text"] = activity_text


def configure_styles(root: tk.Tk) -> None:
    """Configure restrained desktop dashboard styles."""
    styles = ttk.Style(root)
    if "clam" in styles.theme_names():
        styles.theme_use("clam")
    styles.configure("Title.TLabel", font=("TkDefaultFont", 18, "bold"))
    styles.configure("Section.TLabel", font=("TkDefaultFont", 12, "bold"))
    styles.configure("Metric.TLabel", font=("TkDefaultFont", 20, "bold"))
    styles.configure("Card.TFrame", relief="solid", borderwidth=1)
    styles.configure("Card.TLabel", font=("TkDefaultFont", 9))
    styles.configure("Treeview", rowheight=26)


def run_application(state_path: str | Path = DEFAULT_STATE_PATH) -> None:
    """Launch the Construction Intelligence desktop application."""
    root = tk.Tk()
    root.title("AI Construction Intelligence")
    root.geometry("1320x820")
    root.minsize(1080, 680)
    configure_styles(root)
    state = load_state(state_path)
    indicator_variables = {
        indicator_name: tk.StringVar(value="0")
        for indicator_name in [
            "meetings",
            "active",
            "commercial",
            "approvals",
            "recurring",
            "reviews",
        ]
    }
    enabled_specialists = set(state["settings"].get("enabled_specialists", []))
    application_context = {
        "root": root,
        "state": state,
        "state_path": Path(state_path),
        "message_queue": queue.Queue(),
        "indicator_variables": indicator_variables,
        "status_variable": tk.StringVar(value="Ready"),
        "api_key_variable": tk.StringVar(value=""),
        "model_variable": tk.StringVar(value=state["settings"]["model"]),
        "depth_variable": tk.StringVar(value=state["settings"]["analysis_depth"]),
        "meeting_limit_variable": tk.IntVar(
            value=state["settings"].get("maximum_meetings_per_run", 20)
        ),
        "specialist_variables": {
            specialist_name: tk.BooleanVar(value=specialist_name in enabled_specialists)
            for specialist_name in [
                "engineering",
                "contract_commercial",
                "programme_procurement",
                "quality_compliance",
            ]
        },
    }

    header_frame = ttk.Frame(root, padding=(16, 12))
    header_frame.pack(fill="x")
    ttk.Label(header_frame, text="AI Construction Intelligence", style="Title.TLabel").pack(
        side="left"
    )
    ttk.Button(
        header_frame,
        text="Import PDF",
        command=lambda: import_pdf(application_context),
    ).pack(side="right", padx=4)
    analysis_button = ttk.Button(
        header_frame,
        text="Analyse selected",
        command=lambda: start_analysis(application_context),
    )
    analysis_button.pack(side="right", padx=4)
    ttk.Button(
        header_frame,
        text="Export CSV",
        command=lambda: export_csv(application_context),
    ).pack(side="right", padx=4)
    ttk.Button(
        header_frame,
        text="Export JSON",
        command=lambda: export_json(application_context),
    ).pack(side="right", padx=4)
    application_context["analysis_button"] = analysis_button

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=(0, 8))
    create_overview_tab(application_context, notebook)
    create_issue_tab(application_context, notebook)
    create_document_tab(application_context, notebook)
    create_review_tab(application_context, notebook)
    create_settings_tab(application_context, notebook)
    create_activity_tab(application_context, notebook)

    status_frame = ttk.Frame(root, padding=(12, 6))
    status_frame.pack(fill="x")
    ttk.Label(status_frame, textvariable=application_context["status_variable"]).pack(
        side="left"
    )
    progress_bar = ttk.Progressbar(status_frame, length=280, mode="determinate")
    progress_bar.pack(side="right")
    application_context["progress_bar"] = progress_bar

    refresh_application(application_context)
    process_interface_messages(application_context)
    root.mainloop()
