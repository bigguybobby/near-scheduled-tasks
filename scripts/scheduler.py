#!/usr/bin/env python3
"""
NEAR Scheduled Tasks — OpenClaw Skill.

Manage, persist, and execute recurring NEAR blockchain operations via cron.
Supports transfers, contract calls, staking, price checks, webhooks, and
custom shell actions. Uses a JSON file for persistence with file-locking.
"""

import argparse
import fcntl
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("near-scheduled-tasks")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATES_PATH = Path(__file__).parent.parent / "templates" / "cron-templates.json"
DEFAULT_TASKS_FILE = "scheduled_tasks.json"

SUPPORTED_ACTION_TYPES = [
    "transfer",
    "contract_call",
    "price_check",
    "stake",
    "unstake",
    "stake_reward_claim",
    "ft_transfer",
    "account_create",
    "webhook",
    "custom",
]

# Cron field validation: (min, max, allow_names)
CRON_FIELD_RANGES = [
    (0, 59, False),   # minute
    (0, 23, False),   # hour
    (1, 31, False),   # day of month
    (1, 12, True),    # month (Jan–Dec)
    (0, 7, True),     # day of week (0/7 = Sunday)
]

MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"]
DOW_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


# ---------------------------------------------------------------------------
# Cron parsing & validation
# ---------------------------------------------------------------------------

def validate_cron_field(field: str, min_val: int, max_val: int, allow_names: bool) -> bool:
    """
    Validate a single cron field.

    Supports: ``*``, ``*/step``, ``value``, ``value-range``, ``list``.

    Args:
        field:       The cron field string (e.g. ``"*/5"``, ``"1-5"``, ``"0"``)
        min_val:     Minimum allowed numeric value.
        max_val:     Maximum allowed numeric value.
        allow_names: Whether named shortcuts (month/DOW names) are accepted.

    Returns:
        True if valid, False otherwise.
    """
    if field == "*":
        return True

    def _check_val(v: str) -> bool:
        if allow_names:
            if v.lower() in MONTH_NAMES + DOW_NAMES:
                return True
        try:
            n = int(v)
            return min_val <= n <= max_val
        except ValueError:
            return False

    # */step
    if field.startswith("*/"):
        step = field[2:]
        try:
            s = int(step)
            return s > 0
        except ValueError:
            return False

    # list: e.g. 1,3,5
    if "," in field:
        return all(_check_val(f) for f in field.split(","))

    # range: e.g. 1-5
    if "-" in field:
        parts = field.split("-", 1)
        return len(parts) == 2 and _check_val(parts[0]) and _check_val(parts[1])

    return _check_val(field)


def parse_cron(expr: str) -> tuple[bool, str]:
    """
    Parse and validate a 5-field cron expression.

    Args:
        expr: Cron string with exactly 5 whitespace-separated fields.

    Returns:
        ``(valid: bool, message: str)`` where message describes any error.
    """
    fields = expr.strip().split()
    if len(fields) != 5:
        return False, f"Expected 5 fields, got {len(fields)}"

    for i, (field, (mn, mx, an)) in enumerate(zip(fields, CRON_FIELD_RANGES)):
        if not validate_cron_field(field, mn, mx, an):
            field_names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
            return False, f"Invalid {field_names[i]} field: '{field}' (allowed {mn}–{mx})"

    return True, "OK"


def describe_cron(expr: str) -> str:
    """Return a human-readable description of a cron expression."""
    fields = expr.strip().split()
    if len(fields) != 5:
        return expr

    minute, hour, dom, month, dow = fields
    parts = []

    if dow != "*":
        names = {str(i): n for i, n in enumerate(DOW_NAMES)}
        day_name = names.get(dow, dow).capitalize()
        parts.append(f"Every {day_name}")
    elif dom != "*":
        parts.append(f"Day {dom} of every month")
    else:
        parts.append("Every day")

    if hour != "*" and minute != "*":
        parts.append(f"at {hour}:{minute.zfill(2)}")
    elif minute.startswith("*/"):
        parts.append(f"every {minute[2:]} minutes")
    elif hour.startswith("*/"):
        parts.append(f"every {hour[2:]} hours")

    return " ".join(parts) if parts else expr


# ---------------------------------------------------------------------------
# Persistence (file-locked JSON)
# ---------------------------------------------------------------------------

def _load_tasks(tasks_file: str) -> dict:
    """Load tasks from JSON file, returning empty structure if missing."""
    path = Path(tasks_file)
    if not path.exists():
        return {"version": 2, "tasks": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load tasks file %s: %s", tasks_file, exc)
        return {"version": 2, "tasks": []}


def _save_tasks(data: dict, tasks_file: str) -> None:
    """Save tasks to JSON file with an advisory file lock."""
    path = Path(tasks_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")

    with open(lock_path, "w", encoding="utf-8") as lock_f:
        try:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------

def create_task(
    name: str,
    cron: str,
    action_type: str,
    params: dict[str, Any],
    tasks_file: str = DEFAULT_TASKS_FILE,
    description: str = "",
    tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Create and persist a new scheduled task.

    Args:
        name:        Human-readable task name.
        cron:        5-field cron expression.
        action_type: One of the supported NEAR action types.
        params:      Action-specific parameter dict.
        tasks_file:  Path to persistent tasks JSON file.
        description: Optional description shown in listings.
        tags:        Optional list of tags for filtering.

    Returns:
        The newly created task dict.

    Raises:
        ValueError: If cron expression or action type is invalid.
    """
    valid, msg = parse_cron(cron)
    if not valid:
        raise ValueError(f"Invalid cron expression '{cron}': {msg}")

    if action_type not in SUPPORTED_ACTION_TYPES:
        raise ValueError(
            f"Unsupported action type '{action_type}'. "
            f"Supported: {', '.join(SUPPORTED_ACTION_TYPES)}"
        )

    data = _load_tasks(tasks_file)
    existing_ids = {t["id"] for t in data["tasks"]}
    task_idx = max((int(i.split("_")[1]) for i in existing_ids if "_" in i), default=0) + 1

    task: dict[str, Any] = {
        "id": f"task_{task_idx:04d}",
        "name": name,
        "description": description,
        "tags": tags or [],
        "cron": cron,
        "cron_description": describe_cron(cron),
        "action_type": action_type,
        "params": params,
        "enabled": True,
        "run_count": 0,
        "last_run": None,
        "last_status": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    data["tasks"].append(task)
    _save_tasks(data, tasks_file)
    logger.info("Created task %s: %s", task["id"], name)
    return task


def update_task(
    task_id: str,
    tasks_file: str = DEFAULT_TASKS_FILE,
    **kwargs: Any,
) -> Optional[dict]:
    """
    Update fields on an existing task.

    Args:
        task_id:    Task ID string.
        tasks_file: Path to tasks JSON file.
        **kwargs:   Fields to update (e.g. enabled=False, cron="0 10 * * *").

    Returns:
        Updated task dict, or None if not found.
    """
    data = _load_tasks(tasks_file)
    for task in data["tasks"]:
        if task["id"] == task_id:
            if "cron" in kwargs:
                valid, msg = parse_cron(kwargs["cron"])
                if not valid:
                    raise ValueError(f"Invalid cron: {msg}")
                kwargs["cron_description"] = describe_cron(kwargs["cron"])
            task.update(kwargs)
            _save_tasks(data, tasks_file)
            return task
    return None


def delete_task(task_id: str, tasks_file: str = DEFAULT_TASKS_FILE) -> bool:
    """
    Remove a task by ID.

    Args:
        task_id:    Task ID to remove.
        tasks_file: Path to tasks JSON file.

    Returns:
        True if task was found and deleted, False otherwise.
    """
    data = _load_tasks(tasks_file)
    before = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
    if len(data["tasks"]) == before:
        return False
    _save_tasks(data, tasks_file)
    return True


def get_task(task_id: str, tasks_file: str = DEFAULT_TASKS_FILE) -> Optional[dict]:
    """Retrieve a single task by ID."""
    data = _load_tasks(tasks_file)
    return next((t for t in data["tasks"] if t["id"] == task_id), None)


# ---------------------------------------------------------------------------
# Template management
# ---------------------------------------------------------------------------

def load_templates() -> dict:
    """Load task templates from bundled JSON file."""
    if TEMPLATES_PATH.exists():
        try:
            return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load templates: %s", exc)
    return {"templates": []}


def list_templates() -> None:
    """Print available task templates."""
    data = load_templates()
    templates = data.get("templates", [])
    if not templates:
        print("No templates available.")
        return
    for t in templates:
        print(f"  {t['name']:35s} — {t['description']}")
        print(f"    Schedule: {t['cron']}  ({describe_cron(t['cron'])})")
        print(f"    Action:   {t['action_type']}: {json.dumps(t.get('params', {}))}")
        print()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def list_tasks(tasks_file: str = DEFAULT_TASKS_FILE, tag: Optional[str] = None) -> None:
    """Print a human-readable task list, optionally filtered by tag."""
    data = _load_tasks(tasks_file)
    tasks = data.get("tasks", [])
    if tag:
        tasks = [t for t in tasks if tag in t.get("tags", [])]
    if not tasks:
        print("No tasks configured.")
        return
    print(f"{'ID':12s} {'Status':6s} {'Name':30s} {'Schedule':20s} {'Action':20s}")
    print("-" * 95)
    for t in tasks:
        status = "✅" if t.get("enabled") else "⏸️"
        print(f"  {t['id']:12s} {status:6s} {t['name'][:28]:30s} {t['cron']:20s} {t['action_type']}")
        if t.get("description"):
            print(f"    {t['description']}")
        if t.get("last_run"):
            print(f"    Last run: {t['last_run']}  Status: {t.get('last_status', '?')}")
        print()


# ---------------------------------------------------------------------------
# Crontab generation
# ---------------------------------------------------------------------------

def generate_crontab_entry(task: dict[str, Any], script_dir: Path) -> str:
    """
    Generate a crontab line for a task.

    Args:
        task:       Task dict with cron, action_type, params, id, name.
        script_dir: Directory containing scheduler.py.

    Returns:
        Crontab line string.
    """
    params_json = json.dumps(task["params"])
    cmd = (
        f"python3 {script_dir}/scheduler.py execute "
        f"--action-type {task['action_type']} "
        f"--params '{params_json}' "
        f"--task-id {task['id']}"
    )
    return f"{task['cron']}  {cmd}  # [{task['id']}] {task['name']}"


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

def execute_action(
    action_type: str,
    params: dict[str, Any],
    task_id: Optional[str] = None,
    tasks_file: str = DEFAULT_TASKS_FILE,
) -> dict[str, Any]:
    """
    Execute a NEAR action and update task run metadata.

    For transfer, contract_call, stake, etc. this prints the RPC payload that
    would be submitted. Extend this function to call ``near-cli`` or the RPC
    directly when keys are available.

    Args:
        action_type: One of SUPPORTED_ACTION_TYPES.
        params:      Action-specific parameters.
        task_id:     Optional task ID to update run stats in tasks_file.
        tasks_file:  Path to tasks JSON file.

    Returns:
        Result dict with ``action``, ``status``, and action-specific fields.
    """
    ts = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {"action": action_type, "params": params, "executed_at": ts}

    if action_type == "transfer":
        result.update({
            "method": "broadcast_tx_commit",
            "info": (
                f"Transfer {params.get('amount', '0')} NEAR "
                f"from {params.get('sender', '?')} "
                f"to {params.get('receiver', '?')}"
            ),
            "status": "simulated",
        })

    elif action_type == "contract_call":
        result.update({
            "method": "broadcast_tx_commit",
            "info": (
                f"Call {params.get('method', '?')} on {params.get('contract', '?')} "
                f"with args {json.dumps(params.get('args', {}))}"
            ),
            "status": "simulated",
        })

    elif action_type == "stake":
        result.update({
            "info": f"Stake {params.get('amount', '0')} NEAR with {params.get('validator', '?')}",
            "status": "simulated",
        })

    elif action_type == "unstake":
        result.update({
            "info": f"Unstake {params.get('amount', 'all')} NEAR from {params.get('validator', '?')}",
            "status": "simulated",
        })

    elif action_type == "stake_reward_claim":
        result.update({
            "info": f"Claim staking rewards from {params.get('validator', '?')}",
            "status": "simulated",
        })

    elif action_type == "ft_transfer":
        result.update({
            "info": (
                f"FT transfer {params.get('amount', '0')} "
                f"{params.get('token_id', '?')} "
                f"to {params.get('receiver', '?')}"
            ),
            "status": "simulated",
        })

    elif action_type == "account_create":
        result.update({
            "info": f"Create account {params.get('new_account_id', '?')}",
            "status": "simulated",
        })

    elif action_type == "price_check":
        result.update({
            "info": f"Price check for tokens: {params.get('tokens', ['near'])}",
            "status": "simulated",
        })

    elif action_type == "webhook":
        result.update({
            "info": f"HTTP {params.get('method', 'POST')} to {params.get('url', '?')}",
            "status": "simulated",
        })

    elif action_type == "custom":
        result.update({
            "info": f"Custom command: {params.get('command', '?')}",
            "status": "simulated",
        })

    else:
        result.update({"status": "unknown_action"})

    # Update persistence
    if task_id:
        update_task(
            task_id,
            tasks_file=tasks_file,
            last_run=ts,
            last_status=result.get("status", "ok"),
        )
        # Increment run_count safely
        data = _load_tasks(tasks_file)
        for task in data["tasks"]:
            if task["id"] == task_id:
                task["run_count"] = task.get("run_count", 0) + 1
                break
        _save_tasks(data, tasks_file)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NEAR Scheduled Tasks manager — OpenClaw Skill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List built-in templates
  python3 scheduler.py templates

  # Add a daily staking reward claim
  python3 scheduler.py add --name "claim-rewards" --cron "0 8 * * *" \\
      --action-type stake_reward_claim --params '{"validator":"aurora.pool.near"}'

  # List all tasks
  python3 scheduler.py list

  # Filter by tag
  python3 scheduler.py list --tag staking

  # Enable / disable
  python3 scheduler.py enable task_0001
  python3 scheduler.py disable task_0001

  # Delete
  python3 scheduler.py delete task_0001

  # Validate a cron expression
  python3 scheduler.py cron-check "*/15 * * * *"

  # Generate crontab lines
  python3 scheduler.py crontab

  # Execute an action directly
  python3 scheduler.py execute --action-type transfer \\
      --params '{"sender":"me.near","receiver":"vault.near","amount":"5.0"}'
""",
    )

    sub = parser.add_subparsers(dest="command")

    # templates
    sub.add_parser("templates", help="List available task templates")

    # list
    list_p = sub.add_parser("list", help="List configured tasks")
    list_p.add_argument("--tasks-file", default=DEFAULT_TASKS_FILE)
    list_p.add_argument("--tag", help="Filter by tag")
    list_p.add_argument("--json", action="store_true", help="JSON output")

    # add
    add_p = sub.add_parser("add", help="Add a new scheduled task")
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--cron", required=True, help="5-field cron expression")
    add_p.add_argument(
        "--action-type", required=True, choices=SUPPORTED_ACTION_TYPES
    )
    add_p.add_argument("--params", default="{}", help="JSON params string")
    add_p.add_argument("--description", default="")
    add_p.add_argument("--tags", nargs="*", default=[])
    add_p.add_argument("--tasks-file", default=DEFAULT_TASKS_FILE)
    add_p.add_argument("--json", action="store_true")

    # delete
    del_p = sub.add_parser("delete", help="Delete a task by ID")
    del_p.add_argument("task_id")
    del_p.add_argument("--tasks-file", default=DEFAULT_TASKS_FILE)

    # enable / disable
    en_p = sub.add_parser("enable", help="Enable a task")
    en_p.add_argument("task_id")
    en_p.add_argument("--tasks-file", default=DEFAULT_TASKS_FILE)

    dis_p = sub.add_parser("disable", help="Disable a task")
    dis_p.add_argument("task_id")
    dis_p.add_argument("--tasks-file", default=DEFAULT_TASKS_FILE)

    # crontab
    cron_p = sub.add_parser("crontab", help="Generate crontab entries for enabled tasks")
    cron_p.add_argument("--tasks-file", default=DEFAULT_TASKS_FILE)

    # cron-check
    cc_p = sub.add_parser("cron-check", help="Validate a cron expression")
    cc_p.add_argument("expr", help="Cron expression to validate")

    # execute
    ex_p = sub.add_parser("execute", help="Execute a NEAR action directly")
    ex_p.add_argument("--action-type", required=True, choices=SUPPORTED_ACTION_TYPES)
    ex_p.add_argument("--params", default="{}")
    ex_p.add_argument("--task-id", default=None)
    ex_p.add_argument("--tasks-file", default=DEFAULT_TASKS_FILE)
    ex_p.add_argument("--json", action="store_true")

    return parser


def main() -> None:
    """Entry point for the NEAR scheduled tasks skill."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "templates":
        list_templates()

    elif args.command == "list":
        if getattr(args, "json", False):
            data = _load_tasks(args.tasks_file)
            print(json.dumps(data, indent=2))
        else:
            list_tasks(args.tasks_file, tag=getattr(args, "tag", None))

    elif args.command == "add":
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            print(f"Error: invalid --params JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            task = create_task(
                args.name,
                args.cron,
                args.action_type,
                params,
                tasks_file=args.tasks_file,
                description=args.description,
                tags=args.tags,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json", False):
            print(json.dumps(task, indent=2))
        else:
            print(f"✅ Created task: {task['id']} — {task['name']}")
            print(f"   Schedule: {task['cron']}  ({task['cron_description']})")

    elif args.command == "delete":
        ok = delete_task(args.task_id, args.tasks_file)
        if ok:
            print(f"🗑️  Deleted task {args.task_id}")
        else:
            print(f"Error: task {args.task_id} not found", file=sys.stderr)
            sys.exit(1)

    elif args.command == "enable":
        t = update_task(args.task_id, args.tasks_file, enabled=True)
        print(f"✅ Enabled {args.task_id}" if t else f"Error: {args.task_id} not found")

    elif args.command == "disable":
        t = update_task(args.task_id, args.tasks_file, enabled=False)
        print(f"⏸️  Disabled {args.task_id}" if t else f"Error: {args.task_id} not found")

    elif args.command == "crontab":
        data = _load_tasks(args.tasks_file)
        script_dir = Path(__file__).parent
        for task in data.get("tasks", []):
            if task.get("enabled"):
                print(generate_crontab_entry(task, script_dir))

    elif args.command == "cron-check":
        valid, msg = parse_cron(args.expr)
        if valid:
            print(f"✅ Valid: {describe_cron(args.expr)}")
        else:
            print(f"❌ Invalid: {msg}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "execute":
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            print(f"Error: invalid --params JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        result = execute_action(
            args.action_type,
            params,
            task_id=getattr(args, "task_id", None),
            tasks_file=getattr(args, "tasks_file", DEFAULT_TASKS_FILE),
        )
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
        else:
            print(f"✅ {result.get('info', result)}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
