from __future__ import annotations

import random
from datetime import datetime

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

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


TERMINAL_STATUSES = frozenset({
    "SUCCESS", "CANCELLED", "EXPIRED", "JOB_FAILED",
    "UPLOAD_FAILED", "SUBMIT_FAILED",
})


class JobSession(QObject):
    """Tracks state and fake logs for a submitted worker job."""

    log_added = pyqtSignal(str)
    status_changed = pyqtSignal(str)

    def __init__(
        self,
        worker_name: str,
        version: str,
        tenant_id: str,
        machine_type: str,
        input_args: list[dict],
        worker_id: str = "",
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
        self.status = "RUNNING"
        self.start_time = datetime.now()
        self.logs: list[str] = []
        self._log_index = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._next_log)
        self._timer.start(2500)
        self._next_log()

    def _next_log(self):
        if self._log_index >= len(_FAKE_LOGS):
            self.status = "SUCCESS"
            self.status_changed.emit(self.status)
            self._timer.stop()
            return
        level, msg = _FAKE_LOGS[self._log_index]
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts}    {level}    {msg}"
        self.logs.append(line)
        self.log_added.emit(line)
        self._log_index += 1

    def elapsed(self) -> str:
        delta = datetime.now() - self.start_time
        total = int(delta.total_seconds())
        return f"{total // 60}m {total % 60}s"

    def cancel(self):
        self._timer.stop()
        self.status = "CANCELLED"
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts}    [INFO]    Session cancelled by user."
        self.logs.append(line)
        self.log_added.emit(line)
        self.status_changed.emit(self.status)
