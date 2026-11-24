"""Publish verified output files with the native operation that produced them."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from task_recovery import RecoveryConflict


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prefix(identity):
    return "teams/{team_id}/shared/tasks/{task_id}/checkpoints/outputs/".format(**identity)


def publish(identity, workspace, path, operation):
    path = (workspace / path).resolve()
    name = path.relative_to(workspace.resolve()).as_posix()
    sha = digest(path)
    key = prefix(identity) + operation.removeprefix("tools:") + "/" + sha + "/" + name
    subprocess.run(["mc", "cp", str(path), os.environ["AGENTTEAMS_STORAGE_PREFIX"].rstrip("/") + "/" + key],
                   check=True, capture_output=True, timeout=60)
    return {"key": key, "sha256": sha, "size": path.stat().st_size}


def restore(identity, checkpoint, workspace):
    files = {}
    for artifact in checkpoint.get("artifacts") or []:
        base = prefix(identity)
        if artifact["key"].startswith(base):
            parts = artifact["key"][len(base):].split("/", 2)
            if len(parts) != 3 or parts[1] != artifact["sha256"] or not parts[2]:
                raise RecoveryConflict("Invalid output checkpoint reference")
            path = (workspace / parts[2]).resolve()
            if path == workspace or not path.is_relative_to(workspace.resolve()):
                raise RecoveryConflict("Checkpoint output escapes its task directory")
            files[path] = artifact
    for path, artifact in files.items():
        if path.is_file() and digest(path) == artifact["sha256"]:
            continue
        path.parent.mkdir(exist_ok=True, parents=True)
        with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
            copy = Path(tmp) / "verified"
            subprocess.run(["mc", "cp", os.environ["AGENTTEAMS_STORAGE_PREFIX"].rstrip("/") + "/" + artifact["key"], str(copy)],
                           check=True, capture_output=True, timeout=60)
            if copy.stat().st_size != artifact["size"] or digest(copy) != artifact["sha256"]:
                raise RecoveryConflict("Checkpoint output does not match its recorded bytes")
            copy.replace(path)


def terminal_path(identity, operation):
    name = operation.removeprefix("tools:")
    if len(name) != 64 or any(c not in "0123456789abcdef" for c in name):
        raise RecoveryConflict("Invalid native operation identifier")
    prefix = os.environ["AGENTTEAMS_STORAGE_PREFIX"].rstrip("/")
    member = os.environ["AGENTTEAMS_WORKER_NAME"]
    return f"{prefix}/agents/{member}/claude-code/receipts/{identity['team_id']}/{identity['task_id']}/{name}.json"


def persist_terminal(identity, operation, result, artifacts):
    record = {"identity": identity, "operation": operation, "result": result, "artifacts": artifacts}
    subprocess.run(["mc", "pipe", terminal_path(identity, operation)], input=json.dumps(record).encode(),
                   check=True, capture_output=True, timeout=30)


def load_terminal(identity, operation, expected_call):
    key = terminal_path(identity, operation)
    parent, name = key.rsplit("/", 1)
    rows = subprocess.run(["mc", "ls", "--json", parent + "/"], check=True, capture_output=True, timeout=30)
    if not any(json.loads(line).get("key") == name for line in rows.stdout.splitlines()):
        return None
    data = subprocess.run(["mc", "cat", key], check=True, capture_output=True, timeout=30)
    record = json.loads(data.stdout)
    original = record.get("identity") or {}
    if (record.get("operation") != operation or (record.get("result") or {}).get("id") != expected_call
            or any(original.get(k) != identity[k] for k in ("task_id", "team_id"))
            or not 0 < original.get("generation", 0) <= identity["generation"]):
        raise RecoveryConflict("Stored native receipt does not match the claimed task operation")
    return record
