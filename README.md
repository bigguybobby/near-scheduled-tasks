# NEAR Scheduled Tasks — OpenClaw Skill

Schedule recurring NEAR blockchain operations via OpenClaw cron.

## Quick Start

```bash
# List templates
python3 scripts/scheduler.py templates

# Add a daily transfer task
python3 scripts/scheduler.py add --name "daily-reward" --cron "0 9 * * *" --action-type transfer --params '{"sender":"me.near","receiver":"vault.near","amount":"5.0"}'

# List tasks
python3 scripts/scheduler.py list

# Generate crontab
python3 scripts/scheduler.py crontab

# Execute directly
python3 scripts/scheduler.py execute --action-type transfer --params '{"sender":"a.near","receiver":"b.near","amount":"1"}'
```

## Requirements
- Python 3.8+ (stdlib only)

## License
MIT
