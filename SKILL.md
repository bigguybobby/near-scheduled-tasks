# near-scheduled-tasks

## Description
Schedule and manage recurring NEAR blockchain tasks via OpenClaw cron. Supports token transfers, contract calls, and custom actions on configurable schedules.

## Commands
- `scheduler.py templates` — List built-in task templates
- `scheduler.py list` — Show configured tasks
- `scheduler.py add --name NAME --cron EXPR --action-type TYPE --params JSON` — Create task
- `scheduler.py crontab` — Generate crontab entries
- `scheduler.py execute --action-type TYPE --params JSON` — Run action directly

## Action Types
- `transfer` — NEAR token transfer
- `contract_call` — Smart contract method call
- `price_check` — Token price check
- `custom` — Custom action

## Integration
Use `crontab` output to install into system cron or OpenClaw scheduler.
