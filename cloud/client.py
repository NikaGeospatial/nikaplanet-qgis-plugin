"""HTTP client for the Worker Jobs API (spec 2026-04-16).

Implements: prepare, submit, cancel, get job, list jobs,
            get log URL, list outputs, download output file.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.error import HTTPError

from qgis.core import QgsMessageLog, Qgis

from .auth import AuthManager
from .models import PrepareResponse, SubmitResponse, WorkerJob, OutputEntry
from ..util.messages import PLUGIN_LOG_TAG as LOG_TAG
from ..util.settings import get_control_server_url


class WorkerJobsClient:
    """Thin wrapper around the worker jobs REST API."""

    def __init__(self, auth: AuthManager):
        self._auth = auth

    # ── helpers ───────────────────────────────────────────────────

    def _base_url(self) -> str:
        return get_control_server_url()

    def _auth_header(self) -> dict[str, str]:
        token = self._auth.ensure_valid_token()
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        params: dict[str, str] | None = None,
    ) -> dict | list:
        url = f"{self._base_url()}{path}"
        if params:
            qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
            url = f"{url}?{qs}"

        headers = {"Content-Type": "application/json", **self._auth_header()}
        data = json.dumps(body).encode() if body else None

        req = urllib.request.Request(url, data=data, method=method, headers=headers)

        QgsMessageLog.logMessage(f"{method} {url}", LOG_TAG, Qgis.Info)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            QgsMessageLog.logMessage(
                f"{method} {url} → {exc.code}: {raw}", LOG_TAG, Qgis.Warning,
            )
            try:
                detail = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                detail = {"error": raw}
            raise ApiError(exc.code, detail) from None

    # ── 1. Prepare Job ────────────────────────────────────────────

    def prepare_job(
        self,
        tenant_id: str,
        worker_id: str,
        version_tag: str,
        input_schema_with_args: list[dict],
        machine_type: str = "CPUx3",
    ) -> PrepareResponse:
        """POST /api/workers/job/prepare"""
        body = {
            "tenantId": tenant_id,
            "workerId": worker_id,
            "versionTag": version_tag,
            "machineType": machine_type,
            "inputSchemaWithArgs": input_schema_with_args,
        }
        data = self._request("POST", "/api/workers/job/prepare", body=body)
        return PrepareResponse(
            jobId=data["jobId"],
            workerId=data["workerId"],
            workerVersionId=data["workerVersionId"],
            uploadDeadline=data["uploadDeadline"],
            inputSchemaWithArgs=data.get("inputSchemaWithArgs", []),
        )

    # ── 3. Submit Job ─────────────────────────────────────────────

    def submit_job(self, job_id: str) -> SubmitResponse:
        """POST /api/workers/job/submit"""
        data = self._request("POST", "/api/workers/job/submit", body={"jobId": job_id})
        return SubmitResponse(jobId=data["jobId"], status=data["status"])

    # ── 6. Cancel Job ─────────────────────────────────────────────

    def cancel_job(self, job_id: str) -> SubmitResponse:
        """POST /api/workers/job/cancel"""
        data = self._request("POST", "/api/workers/job/cancel", body={"jobId": job_id})
        return SubmitResponse(jobId=data["jobId"], status=data["status"])

    # ── 8. Get Job ────────────────────────────────────────────────

    def get_job(self, job_id: str) -> WorkerJob:
        """GET /api/workers/job/{jobId}"""
        data = self._request("GET", f"/api/workers/job/{job_id}")
        return _parse_worker_job(data)

    # ── List Jobs (added 2026-04-16) ──────────────────────────────

    def list_jobs(
        self,
        worker_id: str | None = None,
        status: str | None = None,
    ) -> list[WorkerJob]:
        """GET /api/workers/jobs

        Returns all jobs created by the authenticated user.
        """
        params: dict[str, str] = {}
        if worker_id:
            params["workerId"] = worker_id
        if status:
            params["status"] = status
        data = self._request("GET", "/api/workers/jobs", params=params)
        return [_parse_worker_job(j) for j in data.get("jobs", [])]

    # ── 9. Get Log URL ────────────────────────────────────────────

    def get_job_log_url(self, job_id: str, disposition: str = "inline") -> str:
        """GET /api/workers/job/{jobId}/log — returns signed URL (15 min)."""
        params: dict[str, str] = {}
        if disposition != "inline":
            params["disposition"] = disposition
        data = self._request("GET", f"/api/workers/job/{job_id}/log", params=params)
        return data["signedUrl"]

    # ── 10. List Outputs (added 2026-04-16) ───────────────────────

    def list_outputs(
        self, job_id: str, path: str = "/",
    ) -> tuple[list[OutputEntry], list[OutputEntry]]:
        """GET /api/workers/job/{jobId}/outputs

        Returns (files, subDirs).
        """
        params: dict[str, str] = {}
        if path != "/":
            params["path"] = path
        data = self._request("GET", f"/api/workers/job/{job_id}/outputs", params=params)
        files = [
            OutputEntry(
                path=f["path"], isDir=f.get("isDir", False),
                size=f.get("size"), lastModified=f.get("lastModified"),
            )
            for f in data.get("files", [])
        ]
        sub_dirs = [
            OutputEntry(path=d["path"], isDir=True)
            for d in data.get("subDirs", [])
        ]
        return files, sub_dirs

    # ── 11. Download Output File (added 2026-04-16) ───────────────

    def get_output_download_url(self, job_id: str, path: str) -> str:
        """GET /api/workers/job/{jobId}/outputs/download-file

        Returns a signed URL (15 min) for a single output file.
        ``path`` is relative to outputs — strip ``/outputs`` prefix from
        the list endpoint's ``path`` values.
        """
        data = self._request(
            "GET", f"/api/workers/job/{job_id}/outputs/download-file",
            params={"path": path},
        )
        return data["signedUrl"]


    # ── 12. Download Output Folder ──────────────────────────────────

    def download_output_folder(
        self, job_id: str, path: str, local_path: str,
    ) -> None:
        """GET /api/workers/job/{jobId}/outputs/download-folder

        Streams a zip archive of the folder at *path* to *local_path*.
        """
        import os

        params: dict[str, str] = {}
        if path != "/":
            params["path"] = path
        url = f"{self._base_url()}/api/workers/job/{job_id}/outputs/download-folder"
        if params:
            qs = "&".join(
                f"{k}={urllib.request.quote(str(v))}" for k, v in params.items()
            )
            url = f"{url}?{qs}"

        headers = self._auth_header()
        req = urllib.request.Request(url, method="GET", headers=headers)
        QgsMessageLog.logMessage(f"GET {url}", LOG_TAG, Qgis.Info)

        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                with open(local_path, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            QgsMessageLog.logMessage(
                f"GET {url} → {exc.code}: {raw}", LOG_TAG, Qgis.Warning,
            )
            try:
                detail = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                detail = {"error": raw}
            raise ApiError(exc.code, detail) from None


def _parse_worker_job(data: dict) -> WorkerJob:
    return WorkerJob(
        jobId=data["jobId"],
        workerId=data["workerId"],
        workerName=data["workerName"],
        workerVersionId=data["workerVersionId"],
        versionTag=data["versionTag"],
        createdBy=data["createdBy"],
        createdByUserName=data["createdByUserName"],
        tenantId=data["tenantId"],
        tenantName=data.get("tenantName"),
        status=data["status"],
        machineType=data["machineType"],
        inputParams=data.get("inputParams"),
        exitCode=data.get("exitCode"),
        exitFailureReason=data.get("exitFailureReason"),
        logUrl=data.get("logUrl"),
        logPreview=data.get("logPreview"),
        hasOutputFiles=data.get("hasOutputFiles", False),
        jobStartedAt=data.get("jobStartedAt"),
        jobEndedAt=data.get("jobEndedAt"),
        createdAt=data["createdAt"],
    )


def upload_file_to_gcs(local_path: str, upload_url: str) -> None:
    """PUT a local file to a GCS signed resumable URL."""
    import os

    size = os.path.getsize(local_path)
    with open(local_path, "rb") as f:
        req = urllib.request.Request(upload_url, data=f, method="PUT")
        req.add_header("Content-Type", "application/octet-stream")
        req.add_header("Content-Length", str(size))
        timeout = max(60, size // (1024 * 1024) * 2)
        urllib.request.urlopen(req, timeout=timeout)


def download_file(url: str, local_path: str) -> None:
    """Download a file from a signed URL to a local path."""
    import os

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=300) as resp:
        with open(local_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)


def resolve_local_path(args: str, entry_path: str) -> str:
    """Map a directoryTree ``path`` back to an absolute local file."""
    import os
    return os.path.join(os.path.dirname(args.rstrip(os.sep)), entry_path)


class ApiError(Exception):
    """Raised when the API returns an HTTP error."""

    def __init__(self, status_code: int, detail: dict):
        self.status_code = status_code
        self.detail = detail
        message = detail.get("error") or detail.get("message") or str(detail)
        super().__init__(f"HTTP {status_code}: {message}")
