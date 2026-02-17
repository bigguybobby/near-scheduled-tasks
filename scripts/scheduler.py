#!/usr/bin/env python3
"""NEAR scheduled tasks skill for OpenClaw. Wraps cron for NEAR-specific operations."""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

TEMPLATES_PATH = Path(__file__).parent.parent / "templates" / "cron-templates.json"

def load_templates():
    if TEMPLATES_PATH.exists():
        return json.loads(TEMPLATES_PATH.read_text())
    return {"templates": []}

def list_templates():
    data = load_templates()
    for t in data.get("templates", []):
        print(f"  {t['name']:30s} — {t['description']}")
        print(f"    Schedule: {t['cron']}")
        print(f"    Action:   {t['action_type']}: {json.dumps(t.get('params', {}))}")
        print()

def create_task(name, cron, action_type, params, tasks_file="scheduled_tasks.json"):
    """Create a new scheduled task entry."""
    path = Path(tasks_file)
    tasks = json.loads(path.read_text()) if path.exists() else {"tasks": []}
    task = {
        "id": f"task_{len(tasks['tasks'])+1:04d}",
        "name": name,
        "cron": cron,
        "action_type": action_type,
        "params": params,
        "enabled": True,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    tasks["tasks"].append(task)
    path.write_text(json.dumps(tasks, indent=2))
    return task

def list_tasks(tasks_file="scheduled_tasks.json"):
    path = Path(tasks_file)
    if not path.exists():
        print("No tasks configured.")
        return
    tasks = json.loads(path.read_text())
    for t in tasks.get("tasks", []):
        status = "✅" if t.get("enabled") else "⏸️"
        print(f"  {status} [{t['id']}] {t['name']}")
        print(f"    Cron: {t['cron']} | Action: {t['action_type']}")
        print(f"    Params: {json.dumps(t.get('params', {}))}")
        print()

def generate_crontab_entry(task, script_dir):
    """Generate a crontab line for OpenClaw execution."""
    params_json = json.dumps(task["params"]).replace('"', '\\"')
    return f"{task['cron']} cd {script_dir} && python3 scheduler.py --execute --action-type {task['action_type']} --params '{params_json}' # {task['name']}"

def execute_action(action_type, params):
    """Execute a NEAR action (stub — prints the RPC call that would be made)."""
    if action_type == "transfer":
        print(json.dumps({
            "jsonrpc": "2.0", "id": "1", "method": "broadcast_tx_commit",
            "info": f"Transfer {params.get('amount', '0')} NEAR from {params.get('sender', '?')} to {params.get('receiver', '?')}"
        }, indent=2))
    elif action_type == "contract_call":
        print(json.dumps({
            "jsonrpc": "2.0", "id": "1", "method": "broadcast_tx_commit",
            "info": f"Call {params.get('method', '?')} on {params.get('contract', '?')}"
        }, indent=2))
    elif action_type == "price_check":
        print(json.dumps({"action": "price_check", "tokens": params.get("tokens", ["near"])}))
    else:
        print(json.dumps({"action": action_type, "params": params}))

def main():
    parser = argparse.ArgumentParser(description="NEAR scheduled tasks manager for OpenClaw")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("templates", help="List available task templates")
    sub.add_parser("list", help="List configured tasks")

    add_p = sub.add_parser("add", help="Add a new scheduled task")
    add_p.add_argument("--name", required=True, help="Task name")
    add_p.add_argument("--cron", required=True, help="Cron expression (5 fields)")
    add_p.add_argument("--action-type", required=True, choices=["transfer", "contract_call", "price_check", "custom"])
    add_p.add_argument("--params", type=str, default="{}", help="JSON params string")
    add_p.add_argument("--tasks-file", default="scheduled_tasks.json")

    cron_p = sub.add_parser("crontab", help="Generate crontab entries")
    cron_p.add_argument("--tasks-file", default="scheduled_tasks.json")

    exec_p = sub.add_parser("execute", help="Execute a NEAR action directly")
    exec_p.add_argument("--action-type", required=True)
    exec_p.add_argument("--params", type=str, default="{}")

    args = parser.parse_args()

    if args.command == "templates":
        list_templates()
    elif args.command == "list":
        list_tasks(getattr(args, "tasks_file", "scheduled_tasks.json"))
    elif args.command == "add":
        params = json.loads(args.params)
        task = create_task(args.name, args.cron, args.action_type, params, args.tasks_file)
        print(f"✅ Created task: {task['id']} — {task['name']}")
    elif args.command == "crontab":
        path = Path(getattr(args, "tasks_file", "scheduled_tasks.json"))
        if path.exists():
            tasks = json.loads(path.read_text())
            for t in tasks.get("tasks", []):
                if t.get("enabled"):
                    print(generate_crontab_entry(t, Path(__file__).parent))
    elif args.command == "execute":
        execute_action(args.action_type, json.loads(args.params))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
