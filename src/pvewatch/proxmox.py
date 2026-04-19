"""Proxmox API client wrapping proxmoxer."""
import logging
import re
import time
from dataclasses import dataclass

from proxmoxer import ProxmoxAPI

from pvewatch.config import Settings

log = logging.getLogger(__name__)


@dataclass
class TaskInfo:
    upid: str
    vmid: int
    node: str
    status: str        # 'running' | 'stopped'
    exit_status: str   # 'OK' | error string | '' if running
    start_time: int
    end_time: int | None
    duration_sec: int | None
    log_tail: str


@dataclass
class StorageInfo:
    storage_id: str
    total_bytes: int
    used_bytes: int


@dataclass
class VMInfo:
    vmid: int
    name: str
    status: str   # 'running' | 'stopped' | 'paused'
    vm_type: str  # 'qemu' | 'lxc'
    node: str


class ProxmoxClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        token_parts = settings.pve_token_id.split("!")
        self._api = ProxmoxAPI(
            settings.pve_host,
            port=settings.pve_port,
            user=token_parts[0],
            token_name=token_parts[1] if len(token_parts) > 1 else "",
            token_value=settings.pve_token_secret,
            verify_ssl=settings.pve_verify_ssl,
            timeout=30,
        )
        self._node = settings.pve_node

    def validate(self) -> str:
        """Return Proxmox version string or raise on auth failure."""
        try:
            version = self._api.version.get()
            return version.get("version", "unknown")
        except Exception as exc:
            raise RuntimeError(f"Failed to connect to Proxmox at {self._settings.pve_host}: {exc}") from exc

    def _node_names(self) -> list[str]:
        """Return all online node names in the cluster."""
        try:
            return [n["node"] for n in self._api.nodes.get() if n.get("status") == "online"]
        except Exception as exc:
            log.warning("Could not list cluster nodes, falling back to configured node: %s", exc)
            return [self._node]

    def get_vzdump_tasks(self, since: int | None = None) -> list[dict]:
        """Return raw vzdump task dicts from ALL cluster nodes."""
        all_tasks: list[dict] = []
        for node in self._node_names():
            try:
                tasks = self._api.nodes(node).tasks.get(typefilter="vzdump", limit=500)
                if since:
                    tasks = [t for t in tasks if t.get("starttime", 0) >= since]
                # Ensure the node name is set on every task dict
                for t in tasks:
                    t.setdefault("node", node)
                all_tasks.extend(tasks)
            except Exception as exc:
                log.warning("Could not fetch tasks from node %s: %s", node, exc)
        return all_tasks

    def _fetch_full_log(self, upid: str, node: str) -> str:
        """Fetch the complete task log (up to 5000 lines) from the given node."""
        try:
            lines = self._api.nodes(node).tasks(upid).log.get(limit=5000, start=0)
            return "\n".join(e.get("t", "") for e in lines if isinstance(e, dict))
        except Exception as exc:
            log.warning("Could not fetch log for %s on %s: %s", upid, node, exc)
            return ""

    def get_task_log(self, upid: str, node: str | None = None, limit: int = 20) -> str:
        """Return the last `limit` lines of a task log."""
        target_node = node or self._node
        try:
            lines = self._api.nodes(target_node).tasks(upid).log.get(limit=limit, start=0)
            entries = [entry.get("t", "") for entry in lines if isinstance(entry, dict)]
            return "\n".join(entries[-limit:])
        except Exception as exc:
            log.warning("Could not fetch log for %s: %s", upid, exc)
            return ""

    def parse_batch_task(self, raw_task: dict) -> list[TaskInfo]:
        """Parse a batch vzdump task (all-VM backup job) into per-VM TaskInfo objects.

        Proxmox runs a single task when the backup scope is 'all'. The per-VM
        results are embedded in the task log as structured INFO lines.
        """
        upid = raw_task.get("upid", "")
        node = raw_task.get("node", self._node)
        batch_start = int(raw_task.get("starttime", 0))

        log_text = self._fetch_full_log(upid, node)
        return _parse_batch_log(log_text, upid, node, batch_start)

    def get_storage(self) -> list[StorageInfo]:
        storages = self._api.nodes(self._node).storage.get()
        result = []
        for s in storages:
            total = s.get("total", 0)
            used = s.get("used", 0)
            if total and total > 0:
                result.append(StorageInfo(
                    storage_id=s["storage"],
                    total_bytes=total,
                    used_bytes=used,
                ))
        return result

    def get_vms(self) -> list[VMInfo]:
        """Return all VMs and containers across the cluster."""
        try:
            resources = self._api.cluster.resources.get(type="vm")
        except Exception:
            resources = (
                [dict(r, type="qemu") for r in self._api.nodes(self._node).qemu.get()]
                + [dict(r, type="lxc") for r in self._api.nodes(self._node).lxc.get()]
            )
        result = []
        for r in resources:
            vmid = r.get("vmid")
            if not vmid:
                continue
            result.append(VMInfo(
                vmid=int(vmid),
                name=r.get("name") or f"VM {vmid}",
                status=r.get("status", "unknown"),
                vm_type=r.get("type", "qemu"),
                node=r.get("node", self._node),
            ))
        return result

    def build_task_info(self, raw_task: dict) -> TaskInfo | None:
        """Build a TaskInfo for a single-VM vzdump task.

        Returns None if the task is still running or is a batch task (no vmid).
        Batch tasks should be handled via parse_batch_task() instead.
        """
        upid = raw_task.get("upid", "")
        status_str = raw_task.get("status", "")

        if status_str == "running":
            return None

        start_time = int(raw_task.get("starttime", 0))
        end_time_raw = raw_task.get("endtime")
        end_time = int(end_time_raw) if end_time_raw else None
        duration = (end_time - start_time) if (end_time and start_time) else None

        exit_status = raw_task.get("exitstatus", "")

        raw_id = raw_task.get("id", "")
        try:
            vmid = int(raw_id) if raw_id else _parse_vmid_from_upid(upid)
        except (ValueError, TypeError):
            vmid = _parse_vmid_from_upid(upid)

        # Batch task — caller should use parse_batch_task() instead
        if vmid == 0:
            return None

        node = raw_task.get("node", self._node)
        log_tail = ""
        if exit_status and exit_status != "OK":
            log_tail = self.get_task_log(upid, node=node)

        return TaskInfo(
            upid=upid,
            vmid=vmid,
            node=node,
            status=status_str,
            exit_status=exit_status,
            start_time=start_time,
            end_time=end_time,
            duration_sec=duration,
            log_tail=log_tail,
        )


def _parse_batch_log(log_text: str, batch_upid: str, node: str, batch_start: int) -> list[TaskInfo]:
    """Parse a batch vzdump task log into individual per-VM TaskInfo objects.

    Log structure (repeated per VM):
        INFO: Starting Backup of VM {vmid} ({type})
        INFO: Backup started at {YYYY-MM-DD HH:MM:SS}
        ... progress lines ...
        INFO: Finished Backup of VM {vmid} ({duration})   ← success
        INFO: Backup finished at {YYYY-MM-DD HH:MM:SS}
    On failure an ERROR line appears instead of / before the Finished line.
    """
    results: list[TaskInfo] = []
    current_vmid: int | None = None
    vm_start: int | None = None
    vm_end: int | None = None
    exit_status = "OK"
    error_lines: list[str] = []

    for line in log_text.splitlines():
        m = re.match(r"INFO: Starting Backup of VM (\d+)", line)
        if m:
            current_vmid = int(m.group(1))
            vm_start = None
            vm_end = None
            exit_status = "OK"
            error_lines = []
            continue

        if current_vmid is None:
            continue

        m = re.match(r"INFO: Backup started at (.+)", line)
        if m:
            try:
                vm_start = int(time.mktime(time.strptime(m.group(1).strip(), "%Y-%m-%d %H:%M:%S")))
            except ValueError:
                pass
            continue

        if "ERROR:" in line:
            exit_status = line.strip().lstrip("ERROR: ").strip()
            error_lines.append(line)
            continue

        m = re.match(r"INFO: Backup finished at (.+)", line)
        if m:
            try:
                vm_end = int(time.mktime(time.strptime(m.group(1).strip(), "%Y-%m-%d %H:%M:%S")))
            except ValueError:
                pass
            start = vm_start or batch_start
            results.append(TaskInfo(
                upid=f"{batch_upid}|{current_vmid}",
                vmid=current_vmid,
                node=node,
                status="stopped",
                exit_status=exit_status,
                start_time=start,
                end_time=vm_end,
                duration_sec=(vm_end - start) if vm_end else None,
                log_tail="\n".join(error_lines[-20:]),
            ))
            current_vmid = None

    return results


def _parse_vmid_from_upid(upid: str) -> int:
    """Extract the VMID from a Proxmox UPID string.

    UPID format: UPID:{node}:{pid}:{pstart}:{starttime}:{type}:{id}:{user}:
    """
    try:
        parts = upid.split(":")
        if len(parts) >= 7:
            id_field = parts[6]
            if id_field.isdigit():
                return int(id_field)
    except Exception:
        pass
    return 0
