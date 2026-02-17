# NEAR Scheduled Tasks — OpenClaw Skill

Schedule and persist recurring NEAR blockchain operations using cron-compatible expressions. Supports 10+ action types, file-locked persistence, cron validation, and crontab generation.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)

---

## Features

- ⏰ **10+ NEAR action types**: transfer, stake, unstake, stake_reward_claim, ft_transfer, contract_call, account_create, price_check, webhook, custom
- ✅ **Cron validation**: parse, validate, and describe any 5-field cron expression
- 💾 **File-locked JSON persistence**: safe concurrent writes via `fcntl` advisory locking
- 🏷️ **Tag-based filtering**: organise tasks by tag
- 📋 **Crontab generation**: emit ready-to-paste crontab lines for all enabled tasks
- 📦 **Template library**: pre-built templates for common NEAR workflows
- 🔄 **Run tracking**: per-task run count, last run timestamp, last status

---

## Installation

```bash
cd ~/projects/near-market/near-scheduled-tasks
python3 --version   # 3.8+ required (stdlib only)
```

---

## Usage

### List templates

```bash
python3 scripts/scheduler.py templates
```

### Add a task

```bash
# Daily stake reward claim at 08:00
python3 scripts/scheduler.py add \
  --name "claim-rewards" \
  --cron "0 8 * * *" \
  --action-type stake_reward_claim \
  --params '{"validator":"aurora.pool.near","account":"me.near"}' \
  --tags staking daily

# Transfer every Monday at 09:00
python3 scripts/scheduler.py add \
  --name "weekly-transfer" \
  --cron "0 9 * * 1" \
  --action-type transfer \
  --params '{"sender":"me.near","receiver":"vault.near","amount":"5.0"}'
```

### List tasks

```bash
python3 scripts/scheduler.py list
python3 scripts/scheduler.py list --tag staking
python3 scripts/scheduler.py list --json
```

### Enable / disable / delete

```bash
python3 scripts/scheduler.py disable task_0001
python3 scripts/scheduler.py enable task_0001
python3 scripts/scheduler.py delete task_0001
```

### Validate a cron expression

```bash
python3 scripts/scheduler.py cron-check "*/15 * * * *"
# ✅ Valid: Every day every 15 minutes

python3 scripts/scheduler.py cron-check "99 * * * *"
# ❌ Invalid: Invalid minute field: '99' (allowed 0–59)
```

### Generate crontab

```bash
python3 scripts/scheduler.py crontab >> /tmp/near-crontab
crontab /tmp/near-crontab
```

### Execute an action directly

```bash
python3 scripts/scheduler.py execute \
  --action-type transfer \
  --params '{"sender":"me.near","receiver":"vault.near","amount":"1.0"}' \
  --json
```

---

## Configuration

Tasks are stored in `scheduled_tasks.json` (configurable via `--tasks-file`).

### Task schema

```json
{
  "id": "task_0001",
  "name": "claim-rewards",
  "description": "Daily staking reward claim",
  "tags": ["staking", "daily"],
  "cron": "0 8 * * *",
  "cron_description": "Every day at 8:00",
  "action_type": "stake_reward_claim",
  "params": {"validator": "aurora.pool.near"},
  "enabled": true,
  "run_count": 42,
  "last_run": "2025-01-17T08:00:05Z",
  "last_status": "simulated",
  "created_at": "2025-01-01T00:00:00Z"
}
```

---

## Supported Action Types

| Type | Description | Key Params |
|------|-------------|------------|
| `transfer` | NEAR token transfer | `sender`, `receiver`, `amount` |
| `contract_call` | Call a contract method | `contract`, `method`, `args` |
| `stake` | Stake NEAR with validator | `validator`, `account`, `amount` |
| `unstake` | Unstake NEAR | `validator`, `account`, `amount` |
| `stake_reward_claim` | Claim staking rewards | `validator`, `account` |
| `ft_transfer` | Fungible token transfer | `token_id`, `receiver`, `amount` |
| `account_create` | Create a new account | `new_account_id`, `initial_balance` |
| `price_check` | Check token prices | `tokens` |
| `webhook` | HTTP webhook call | `url`, `method`, `body` |
| `custom` | Custom shell command | `command` |

---

## API Reference

### `create_task(name, cron, action_type, params, tasks_file, description, tags) → dict`

Create and persist a new task. Raises `ValueError` on invalid cron or action type.

### `update_task(task_id, tasks_file, **kwargs) → dict | None`

Update fields on an existing task. Returns updated task or `None` if not found.

### `delete_task(task_id, tasks_file) → bool`

Remove a task. Returns `True` if deleted.

### `parse_cron(expr) → (bool, str)`

Validate a 5-field cron expression. Returns `(valid, message)`.

### `describe_cron(expr) → str`

Convert a cron expression to plain English.

### `execute_action(action_type, params, task_id, tasks_file) → dict`

Execute a NEAR action and update run metadata.

### `generate_crontab_entry(task, script_dir) → str`

Emit a crontab line for a task.

---

## Testing

```bash
pip install pytest
cd ~/projects/near-market/near-scheduled-tasks
pytest tests/ -v
```

---

## License

[MIT](LICENSE) © 2025 bigguybobby
