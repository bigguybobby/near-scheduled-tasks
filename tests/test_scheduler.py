"""Tests for NEAR scheduled tasks skill."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import scheduler as sc  # noqa: E402


# ---------------------------------------------------------------------------
# Cron parsing
# ---------------------------------------------------------------------------

class TestParseCron:
    @pytest.mark.parametrize("expr", [
        "* * * * *",
        "0 9 * * *",
        "*/15 * * * *",
        "0 8 1 * *",
        "0 0 * * 1",
        "30 23 31 12 7",
        "0,30 9,17 * * 1-5",
    ])
    def test_valid_expressions(self, expr):
        valid, msg = sc.parse_cron(expr)
        assert valid, f"'{expr}' should be valid but got: {msg}"

    @pytest.mark.parametrize("expr,contains", [
        ("* * * *", "5 fields"),
        ("60 * * * *", "minute"),
        ("* 24 * * *", "hour"),
        ("* * 0 * *", "day-of-month"),
        ("* * * 13 *", "month"),
        ("* * * * 8", "day-of-week"),
        ("abc * * * *", "minute"),
    ])
    def test_invalid_expressions(self, expr, contains):
        valid, msg = sc.parse_cron(expr)
        assert not valid
        assert contains.lower() in msg.lower()

    def test_step_notation(self):
        valid, _ = sc.parse_cron("*/5 */2 * * *")
        assert valid

    def test_list_notation(self):
        valid, _ = sc.parse_cron("0,30 9,17 * * *")
        assert valid

    def test_range_notation(self):
        valid, _ = sc.parse_cron("0 9 1-15 * *")
        assert valid


class TestDescribeCron:
    def test_daily(self):
        desc = sc.describe_cron("0 9 * * *")
        assert "9" in desc

    def test_every_15_minutes(self):
        desc = sc.describe_cron("*/15 * * * *")
        assert "15" in desc

    def test_weekly(self):
        desc = sc.describe_cron("0 8 * * 1")
        assert "mon" in desc.lower() or "1" in desc


# ---------------------------------------------------------------------------
# Task CRUD (using temp files)
# ---------------------------------------------------------------------------

@pytest.fixture
def tasks_file(tmp_path):
    return str(tmp_path / "tasks.json")


class TestCreateTask:
    def test_basic_create(self, tasks_file):
        task = sc.create_task(
            name="test-transfer",
            cron="0 9 * * *",
            action_type="transfer",
            params={"sender": "me.near", "receiver": "vault.near", "amount": "5.0"},
            tasks_file=tasks_file,
        )
        assert task["id"].startswith("task_")
        assert task["name"] == "test-transfer"
        assert task["enabled"] is True
        assert task["run_count"] == 0

    def test_invalid_cron_raises(self, tasks_file):
        with pytest.raises(ValueError, match="Invalid cron"):
            sc.create_task("bad", "99 * * *", "transfer", {}, tasks_file=tasks_file)

    def test_invalid_action_type_raises(self, tasks_file):
        with pytest.raises(ValueError, match="Unsupported action type"):
            sc.create_task("bad", "0 9 * * *", "fly_to_moon", {}, tasks_file=tasks_file)

    def test_multiple_tasks_unique_ids(self, tasks_file):
        t1 = sc.create_task("t1", "0 9 * * *", "transfer", {}, tasks_file=tasks_file)
        t2 = sc.create_task("t2", "0 10 * * *", "stake", {}, tasks_file=tasks_file)
        assert t1["id"] != t2["id"]

    def test_persistence(self, tasks_file):
        sc.create_task("persist-test", "0 9 * * *", "price_check", {}, tasks_file=tasks_file)
        data = sc._load_tasks(tasks_file)
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["name"] == "persist-test"

    def test_tags_stored(self, tasks_file):
        task = sc.create_task(
            "tagged", "0 9 * * *", "stake", {},
            tasks_file=tasks_file, tags=["staking", "daily"]
        )
        assert "staking" in task["tags"]


class TestUpdateTask:
    def test_enable_disable(self, tasks_file):
        task = sc.create_task("t", "0 9 * * *", "transfer", {}, tasks_file=tasks_file)
        updated = sc.update_task(task["id"], tasks_file=tasks_file, enabled=False)
        assert updated["enabled"] is False
        re_enabled = sc.update_task(task["id"], tasks_file=tasks_file, enabled=True)
        assert re_enabled["enabled"] is True

    def test_update_cron(self, tasks_file):
        task = sc.create_task("t", "0 9 * * *", "transfer", {}, tasks_file=tasks_file)
        updated = sc.update_task(task["id"], tasks_file=tasks_file, cron="0 10 * * *")
        assert updated["cron"] == "0 10 * * *"

    def test_update_nonexistent_returns_none(self, tasks_file):
        result = sc.update_task("task_9999", tasks_file=tasks_file, enabled=False)
        assert result is None

    def test_invalid_cron_on_update_raises(self, tasks_file):
        task = sc.create_task("t", "0 9 * * *", "transfer", {}, tasks_file=tasks_file)
        with pytest.raises(ValueError):
            sc.update_task(task["id"], tasks_file=tasks_file, cron="bad cron")


class TestDeleteTask:
    def test_delete_existing(self, tasks_file):
        task = sc.create_task("t", "0 9 * * *", "transfer", {}, tasks_file=tasks_file)
        ok = sc.delete_task(task["id"], tasks_file=tasks_file)
        assert ok is True
        data = sc._load_tasks(tasks_file)
        assert len(data["tasks"]) == 0

    def test_delete_nonexistent(self, tasks_file):
        ok = sc.delete_task("task_9999", tasks_file=tasks_file)
        assert ok is False


class TestGetTask:
    def test_get_existing(self, tasks_file):
        task = sc.create_task("t", "0 9 * * *", "transfer", {}, tasks_file=tasks_file)
        found = sc.get_task(task["id"], tasks_file=tasks_file)
        assert found is not None
        assert found["name"] == "t"

    def test_get_nonexistent(self, tasks_file):
        result = sc.get_task("task_9999", tasks_file=tasks_file)
        assert result is None


# ---------------------------------------------------------------------------
# execute_action
# ---------------------------------------------------------------------------

class TestExecuteAction:
    @pytest.mark.parametrize("action_type", sc.SUPPORTED_ACTION_TYPES)
    def test_all_action_types_return_result(self, action_type):
        result = sc.execute_action(action_type, {})
        assert "action" in result
        assert result["action"] == action_type

    def test_transfer_info(self):
        result = sc.execute_action(
            "transfer",
            {"sender": "me.near", "receiver": "you.near", "amount": "1.0"}
        )
        assert "me.near" in result["info"]
        assert "you.near" in result["info"]

    def test_stake_info(self):
        result = sc.execute_action("stake", {"validator": "aurora.pool.near", "amount": "10"})
        assert "aurora.pool.near" in result["info"]

    def test_updates_task_metadata(self, tasks_file):
        task = sc.create_task("t", "0 9 * * *", "transfer", {}, tasks_file=tasks_file)
        sc.execute_action("transfer", {}, task_id=task["id"], tasks_file=tasks_file)
        updated = sc.get_task(task["id"], tasks_file=tasks_file)
        assert updated["last_run"] is not None


# ---------------------------------------------------------------------------
# generate_crontab_entry
# ---------------------------------------------------------------------------

class TestGenerateCrontab:
    def test_crontab_contains_cron(self, tasks_file):
        task = sc.create_task("t", "0 9 * * *", "transfer", {"amount": "1"}, tasks_file=tasks_file)
        entry = sc.generate_crontab_entry(task, Path("/usr/local/scripts"))
        assert "0 9 * * *" in entry
        assert "scheduler.py" in entry
