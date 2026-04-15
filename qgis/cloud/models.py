"""Data models for the Worker Jobs API (spec 2026-04-15)."""

from __future__ import annotations

from dataclasses import dataclass, field
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
class OutputFile:
    name: str
    url: str


@dataclass
class PrepareRequest:
    tenantId: str
    workerId: str  # Changed from workerName in 2026-04-13
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
    logUrl: Optional[str] = None  # Raw GCS path — not directly accessible
    logPreview: Optional[str] = None
    outputFiles: Optional[list[OutputFile]] = None
    outputExpiry: Optional[str] = None
    jobStartedAt: Optional[str] = None  # Corrected from startedAt (2026-04-14)
    jobEndedAt: Optional[str] = None    # Corrected from endedAt (2026-04-14)
