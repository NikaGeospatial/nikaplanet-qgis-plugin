"""Data models for the Worker Jobs API (spec 2026-04-16)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class WorkerJobStatus(str, Enum):
    PREPARING = "PREPARING"
    EXPIRED = "EXPIRED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    SUBMIT_FAILED = "SUBMIT_FAILED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    CANCELLED = "CANCELLED"
    JOB_FAILED = "JOB_FAILED"
    SUCCESS = "SUCCESS"


TERMINAL_STATUSES = frozenset({
    WorkerJobStatus.SUCCESS,
    WorkerJobStatus.JOB_FAILED,
    WorkerJobStatus.CANCELLED,
    WorkerJobStatus.EXPIRED,
    WorkerJobStatus.UPLOAD_FAILED,
    WorkerJobStatus.SUBMIT_FAILED,
})


@dataclass
class DirectoryTreeEntry:
    path: str
    sizeInBytes: int
    uploadUrl: Optional[str] = None


@dataclass
class InputSchemaEntry:
    name: str
    type: str  # "file" | "folder" | "string" | "number" | "boolean" | "enum" | "datetime"
    readonly: Optional[bool] = None
    required: Optional[bool] = None
    description: Optional[str] = None
    default: Optional[str] = None
    enum_values: Optional[list[str]] = None
    filetypes: Optional[list[str]] = None  # e.g. [".csv", ".geojson"]
    args: Optional[str] = None
    directoryTree: Optional[list[DirectoryTreeEntry]] = None


@dataclass
class PrepareRequest:
    tenantId: str
    workerId: str
    versionTag: str
    inputSchemaWithArgs: list[dict]
    machineType: str = "CPUx3"


@dataclass
class PrepareResponse:
    jobId: str
    workerId: str
    workerVersionId: str
    uploadDeadline: str
    inputSchemaWithArgs: list[dict]


@dataclass
class SubmitResponse:
    jobId: str
    status: str


@dataclass
class WorkerJob:
    jobId: str
    workerId: str
    workerName: str
    workerVersionId: str
    versionTag: str
    createdBy: str
    createdByUserName: str
    tenantId: str
    status: str
    machineType: str
    createdAt: str
    tenantName: Optional[str] = None
    inputParams: Optional[list[dict]] = None
    exitCode: Optional[int] = None
    exitFailureReason: Optional[str] = None
    logUrl: Optional[str] = None
    logPreview: Optional[str] = None
    hasOutputFiles: bool = False  # Replaces outputFiles/outputExpiry (2026-04-16)
    jobStartedAt: Optional[str] = None
    jobEndedAt: Optional[str] = None


@dataclass
class OutputEntry:
    """A file or folder returned by GET /api/workers/job/{jobId}/outputs."""
    path: str
    isDir: bool
    size: Optional[str] = None
    lastModified: Optional[str] = None
