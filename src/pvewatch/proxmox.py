"""Proxmox API client wrapping proxmoxer."""
import logging
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

    def get_vzdump_tasks(self, since: int | None = None) -> list[dict]:
        """Return raw vzdump task dicts from the node task log."""
        kwargs: dict = {"typefilter": "vzdump", "limit": 500}
        if since:
            kwargs["start"] = 0  # proxmox paginates differently; we filter by starttime client-side
        tasks = self._api.nodes(self._node).tasks.get(**kwargs)
        if since:
            tasks = [t for t in tasks if t.get("starttime", 0) >= since]
        return tasks

    def get_task_status(self, upid: str) -> dict:
        return self._api.nodes(self._node).tasks(upid).status.get()

    def get_task_log(self, upid: str, limit: int = 20) -> str:
        """Return the last `limit` lines of the task log as a single string."""
        try:
            lines = self._api.nodes(self._node).tasks(upid).log.get(limit=limit, start=0)
            # The API may return them oldest-first; we want the tail
            entries = [entry.get("t", "") for entry in lines if isinstance(entry, dict)]
            return "\n".join(entries[-limit:])
        except Exception as exc:
            log.warning("Could not fetch log for %s: %s", upid, exc)
            return ""

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
            # Fallback: query node directly if cluster API is unavailable
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
        """Build a TaskInfo from a raw task dict + status/log API calls.

        Returns None for tasks that are still running.
        """
        upid = raw_task.get("upid", "")
        status_str = raw_task.get("status", "")

        # status field from task list is 'stopped' when done, 'running' when active
        if status_str == "running":
            return None

        start_time = int(raw_task.get("starttime", 0))
        end_time_raw = raw_task.get("endtime")
        end_time = int(end_time_raw) if end_time_raw else None
        duration = (end_time - start_time) if (end_time and start_time) else None

        # exitstatus is in the task list response for stopped tasks
        exit_status = raw_task.get("exitstatus", "")

        # Prefer the top-level 'id' field (present for PBS-targeted tasks where
        # the UPID vmid slot is empty), fall back to UPID parsing.
        raw_id = raw_task.get("id", "")
        try:
            vmid = int(raw_id) if raw_id else _parse_vmid_from_upid(upid)
        except (ValueError, TypeError):
            vmid = _parse_vmid_from_upid(upid)

        log_tail = ""
        if exit_status and exit_status != "OK":
            log_tail = self.get_task_log(upid)

        return TaskInfo(
            upid=upid,
            vmid=vmid,
            node=raw_task.get("node", self._node),
            status=status_str,
            exit_status=exit_status,
            start_time=start_time,
            end_time=end_time,
            duration_sec=duration,
            log_tail=log_tail,
        )


def _parse_vmid_from_upid(upid: str) -> int:
    """Extract the VMID from a Proxmox UPID string.

    UPID format: UPID:{node}:{pid}:{pstart}:{starttime}:{type}:{id}:{user}:
    For vzdump tasks the id field is the VMID.
    """
    try:
        parts = upid.split(":")
        # parts[6] is the id for vzdump tasks
        if len(parts) >= 7:
            id_field = parts[6]
            if id_field.isdigit():
                return int(id_field)
    except Exception:
        pass
    return 0
