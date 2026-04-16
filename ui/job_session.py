from __future__ import annotations

import random
import threading
from datetime import datetime

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

TERMINAL_STATUSES = frozenset({
    "SUCCESS", "CANCELLED", "EXPIRED", "JOB_FAILED",
    "UPLOAD_FAILED", "SUBMIT_FAILED",
})

_POLL_INTERVAL_MS = 5000


class JobSession(QObject):
    """Tracks state for a submitted worker job.

    When *client* is provided the session runs the real prepare -> upload ->
    submit flow.  Without a client it falls back to fake logs for local UI
    development.  Use ``from_history()`` to create a read-only session from
    a historical ``WorkerJob`` dict.
    """

    log_added = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    session_id_changed = pyqtSignal(str)
    _submit_phase_done = pyqtSignal(bool)

    def __init__(
        self,
        worker_name: str,
        version: str,
        tenant_id: str,
        machine_type: str,
        input_args: list[dict],
        worker_id: str = "",
        client=None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.worker_id = worker_id
        self.worker_name = worker_name
        self.version = version
        self.tenant_id = tenant_id
        self.machine_type = machine_type
        self.input_args = input_args
        self.job_id: str | None = None
        self.session_id = f"WM-{random.randint(1000, 9999)}-ALPHA"
        self.start_time = datetime.now()
        self.logs: list[str] = []
        self.has_output_files = False

        self._client = client
        self._cancelled = False
        self._last_log_preview: str | None = None
        self._poll_timer: QTimer | None = None

        if client:
            self.status = "PREPARING"
            self._submit_phase_done.connect(self._on_submit_phase_done)
            threading.Thread(
                target=self._prepare_upload_submit, daemon=True,
            ).start()
        else:
            self.status = "RUNNING"
            self._fake_index = 0
            self._fake_timer = QTimer(self)
            self._fake_timer.timeout.connect(self._next_fake_log)
            self._fake_timer.start(2500)
            self._next_fake_log()

    # ── factory for historical jobs ──────────────────────────────

    @classmethod
    def from_history(cls, job_data: dict, client=None, parent=None):
        """Create a read-only session from a GET /api/workers/jobs entry."""
        session = cls(
            worker_name=job_data.get("workerName", ""),
            version=job_data.get("versionTag", ""),
            tenant_id=job_data.get("tenantId", ""),
            machine_type=job_data.get("machineType", ""),
            input_args=job_data.get("inputParams") or [],
            worker_id=job_data.get("workerId", ""),
            client=None,
            parent=parent,
        )
        # Stop the fake timer that __init__ started.
        session._fake_timer.stop()
        # Override with real data.
        session.job_id = job_data.get("jobId")
        session.session_id = (job_data.get("jobId") or "")[:13]
        session.status = job_data.get("status", "UNKNOWN")
        session.has_output_files = job_data.get("hasOutputFiles", False)
        session._client = client
        session.logs.clear()
        if job_data.get("logPreview"):
            session.logs.append(job_data["logPreview"])

        # Fetch the full log for terminal jobs that have a client.
        if session.status in TERMINAL_STATUSES and client and session.job_id:
            threading.Thread(
                target=session._try_fetch_full_log, daemon=True,
            ).start()

        return session

    # ── real flow (background thread) ────────────────────────────

    def _prepare_upload_submit(self):
        from ..cloud.client import upload_file_to_gcs, resolve_local_path, ApiError

        try:
            self._emit_log("[INFO]  Preparing job\u2026")
            resp = self._client.prepare_job(
                tenant_id=self.tenant_id,
                worker_id=self.worker_id,
                version_tag=self.version,
                input_schema_with_args=self.input_args,
                machine_type=self.machine_type,
            )
            self.job_id = resp.jobId
            self.session_id = resp.jobId[:13]
            self.session_id_changed.emit(self.session_id)
            self._emit_log(f"[INFO]  Job created: {resp.jobId}")
            self._emit_log(f"[INFO]  Upload deadline: {resp.uploadDeadline}")

            if self._cancelled:
                return

            uploads: list[tuple[str, str]] = []
            for entry in resp.inputSchemaWithArgs:
                for item in entry.get("directoryTree") or []:
                    if "uploadUrl" in item:
                        local = resolve_local_path(entry["args"], item["path"])
                        uploads.append((local, item["uploadUrl"]))

            if uploads:
                self._emit_log(f"[INFO]  Uploading {len(uploads)} file(s)\u2026")
                for i, (local, url) in enumerate(uploads, 1):
                    if self._cancelled:
                        return
                    name = local.rsplit("/", 1)[-1] if "/" in local else local.rsplit("\\", 1)[-1]
                    self._emit_log(f"[INFO]  [{i}/{len(uploads)}] {name}")
                    upload_file_to_gcs(local, url)
                self._emit_log("[INFO]  All files uploaded.")
            else:
                self._emit_log("[INFO]  No file uploads required.")

            if self._cancelled:
                return

            self._emit_log("[INFO]  Submitting job\u2026")
            submit_resp = self._client.submit_job(resp.jobId)
            self._set_status(submit_resp.status)
            self._emit_log(f"[INFO]  Job status: {submit_resp.status}")
            self._submit_phase_done.emit(True)

        except ApiError as exc:
            self._emit_log(f"[ERROR] API error: {exc}")
            self._set_status("JOB_FAILED")
            self._submit_phase_done.emit(False)
        except FileNotFoundError as exc:
            self._emit_log(f"[ERROR] File not found: {exc}")
            self._set_status("UPLOAD_FAILED")
            self._submit_phase_done.emit(False)
        except Exception as exc:
            self._emit_log(f"[ERROR] {exc}")
            self._set_status("JOB_FAILED")
            self._submit_phase_done.emit(False)

    # ── post-submit polling (main thread) ────────────────────────

    def _on_submit_phase_done(self, success: bool):
        if not success or self.status in TERMINAL_STATUSES:
            return
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_status)
        self._poll_timer.start(_POLL_INTERVAL_MS)

    def _poll_status(self):
        if not self._client or not self.job_id:
            return
        try:
            job = self._client.get_job(self.job_id)
        except Exception:
            return

        if job.status != self.status:
            self._set_status(job.status)
        self.has_output_files = job.hasOutputFiles

        if job.logPreview and job.logPreview != self._last_log_preview:
            old_lines = (self._last_log_preview or "").splitlines()
            new_lines = job.logPreview.splitlines()
            for line in new_lines[len(old_lines):]:
                self._emit_log(line)
            self._last_log_preview = job.logPreview

        if job.status in TERMINAL_STATUSES:
            self._poll_timer.stop()
            threading.Thread(
                target=self._try_fetch_full_log, daemon=True,
            ).start()

    def _try_fetch_full_log(self):
        if not self._client or not self.job_id:
            return
        try:
            signed_url = self._client.get_job_log_url(self.job_id)
            import urllib.request
            with urllib.request.urlopen(signed_url, timeout=30) as resp:
                log_text = resp.read().decode("utf-8", errors="replace")
            self._emit_log("--- full log ---")
            for line in log_text.splitlines():
                self._emit_log(line)
        except Exception:
            if not self.logs:
                self._emit_log("No logs found.")

    # ── cancel ───────────────────────────────────────────────────

    def cancel(self):
        self._cancelled = True
        if self._poll_timer:
            self._poll_timer.stop()
        if self._client and self.job_id:
            try:
                self._client.cancel_job(self.job_id)
            except Exception:
                pass
        self._set_status("CANCELLED")
        self._emit_log("[INFO]  Session cancelled by user.")

    # ── helpers ──────────────────────────────────────────────────

    def elapsed(self) -> str:
        delta = datetime.now() - self.start_time
        total = int(delta.total_seconds())
        return f"{total // 60}m {total % 60}s"

    def _emit_log(self, line: str):
        ts = datetime.now().strftime("%H:%M:%S")
        formatted = f"{ts}    {line}"
        self.logs.append(formatted)
        self.log_added.emit(formatted)

    def _set_status(self, status: str):
        self.status = status
        self.status_changed.emit(status)

    # ── fake flow (no client) ────────────────────────────────────

    _FAKE_LOGS = [
        ("[INFO]", "Initializing worker instance..."),
        ("[INFO]", "Loading input parameters..."),
        ("[INFO]", "Validating input schema..."),
        ("[INFO]", "Connecting to data source..."),
        ("[INFO]", "Reading input file..."),
        ("[INFO]", "Processing data block 1/4..."),
        ("[INFO]", "Processing data block 2/4..."),
        ("[INFO]", "Processing data block 3/4..."),
        ("[WARN]", "Retrying connection to tile server..."),
        ("[INFO]", "Processing data block 4/4..."),
        ("[INFO]", "Writing output file..."),
        ("[INFO]", "Finalizing results..."),
        ("[INFO]", "Worker completed successfully."),
    ]

    def _next_fake_log(self):
        if self._fake_index >= len(self._FAKE_LOGS):
            self._set_status("SUCCESS")
            self._fake_timer.stop()
            return
        level, msg = self._FAKE_LOGS[self._fake_index]
        self._emit_log(f"{level}  {msg}")
        self._fake_index += 1
