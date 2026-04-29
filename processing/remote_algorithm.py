from __future__ import annotations

# QgsProcessingAlgorithm wrapper for a worker version fetched from the
# control server. Submits jobs through the same prepare → upload → submit
# → poll flow as the NikaPlanet panel's run dialog (see
# ui/job_session.py:_prepare_upload_submit).
import os
import time
from typing import Any, Callable, Optional

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)

from ..cloud.client import (
    ApiError,
    WorkerJobsClient,
    resolve_local_path,
    upload_file_to_gcs,
)
from ..cloud.models import TERMINAL_STATUS_NAMES
from ..util.job_payload import build_input_schema_with_args


_POLL_INTERVAL_SECONDS = 5
_MACHINE_PARAM = "MACHINE_TYPE"


def _enum_param_for(inp: dict) -> QgsProcessingParameterEnum:
    values = list(inp.get("enum_values") or [])
    default = inp.get("default")
    default_idx = values.index(default) if default in values else 0
    return QgsProcessingParameterEnum(
        inp["name"],
        inp.get("description", inp["name"]),
        options=values,
        defaultValue=default_idx,
    )


# Map (input type, output) -> a builder. ``output=False`` means input
# (file/folder picker), ``output=True`` means output (save dialog/text).
_PARAM_BUILDERS: dict[tuple[str, bool], Callable[[dict], Any]] = {
    ("file", False): lambda inp: QgsProcessingParameterFile(
        inp["name"], inp.get("description", inp["name"]),
    ),
    ("file", True): lambda inp: QgsProcessingParameterFileDestination(
        inp["name"], inp.get("description", inp["name"]),
    ),
    ("folder", False): lambda inp: QgsProcessingParameterFile(
        inp["name"], inp.get("description", inp["name"]),
        behavior=QgsProcessingParameterFile.Behavior.Folder,
    ),
    ("folder", True): lambda inp: QgsProcessingParameterString(
        inp["name"], inp.get("description", inp["name"]),
    ),
    ("boolean", False): lambda inp: QgsProcessingParameterBoolean(
        inp["name"], inp.get("description", inp["name"]),
        defaultValue=bool(inp.get("default", False)),
    ),
    ("enum", False): _enum_param_for,
    ("number", False): lambda inp: QgsProcessingParameterNumber(
        inp["name"], inp.get("description", inp["name"]),
        type=QgsProcessingParameterNumber.Type.Double,
    ),
}


def _default_param(inp: dict) -> QgsProcessingParameterString:
    p = QgsProcessingParameterString(
        inp["name"], inp.get("description", inp["name"]),
    )
    default = inp.get("default")
    if default is not None:
        p.setDefaultValue(str(default))
    return p


class RemoteAlgorithm(QgsProcessingAlgorithm):
    """A processing algorithm built dynamically from a worker version
    returned by ``GET /api/workers``."""

    def __init__(
        self,
        task_def: Optional[dict] = None,
        client: Optional[WorkerJobsClient] = None,
    ):
        super().__init__()
        self._task_def = task_def or {}
        self._client = client

    # -- identity ----------------------------------------------------------

    def name(self) -> str:
        return self._task_def.get("name", "unknown-remote-task")

    def displayName(self) -> str:
        return self._task_def.get("name", "Unknown Remote Task")

    def group(self) -> str:
        return "Remote Tasks"

    def groupId(self) -> str:
        return "remotetasks"

    def shortHelpString(self) -> str:
        return self._task_def.get("description", "")

    # -- helpers -----------------------------------------------------------

    def _inputs(self) -> list[dict]:
        return (
            self._task_def.get("inputs")
            or self._task_def.get("command", {}).get("inputs", [])
            or []
        )

    def _machine_type_choices(self) -> list[str]:
        plan = self._task_def.get("planFeatures") or {}
        cpu = plan.get("cpu_machine_types") or []
        gpu = plan.get("gpu_machine_types") or []
        choices = list(cpu) + list(gpu)
        return choices or ["CPUx3"]

    def _read_param_value(
        self,
        inp: dict,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
    ) -> Optional[str]:
        """Pull a user-entered value out of QGIS parameters as the string
        the prepare endpoint expects."""
        name = inp.get("name", "")
        inp_type = inp.get("type", "string")
        if name not in parameters or parameters[name] is None:
            return None

        if inp_type == "boolean":
            return "true" if self.parameterAsBool(parameters, name, context) else "false"
        if inp_type == "enum":
            values = list(inp.get("enum_values") or [])
            idx = self.parameterAsEnum(parameters, name, context)
            if 0 <= idx < len(values):
                return values[idx]
            return None
        if inp_type == "number":
            return str(self.parameterAsDouble(parameters, name, context))

        # file / folder / string / datetime / anything else -> string
        value = self.parameterAsString(parameters, name, context)
        return value or None

    # -- parameters --------------------------------------------------------

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        # First parameter: machine type, populated from the worker's plan.
        choices = self._machine_type_choices()
        self.addParameter(QgsProcessingParameterEnum(
            _MACHINE_PARAM, "Compute", options=choices, defaultValue=0,
        ))

        for inp in self._inputs():
            inp_type = inp.get("type", "string")
            is_output = inp.get("output", False)
            builder = _PARAM_BUILDERS.get((inp_type, is_output), _default_param)
            param = builder(inp)
            if not inp.get("required", False):
                param.setFlags(
                    param.flags()
                    | QgsProcessingParameterFile.Flag.FlagOptional
                )
            self.addParameter(param)

    # -- execution ---------------------------------------------------------

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        if not self._client:
            raise QgsProcessingException(
                "Not signed in to NikaPlanet. Open the NikaPlanet panel "
                "and sign in, then re-run this algorithm."
            )

        machine_choices = self._machine_type_choices()
        machine_idx = self.parameterAsEnum(parameters, _MACHINE_PARAM, context)
        machine_type = machine_choices[machine_idx] if machine_choices else "CPUx3"

        schema, missing_sidecars = build_input_schema_with_args(
            self._inputs(),
            value_for=lambda inp: self._read_param_value(inp, parameters, context),
        )
        for fname, exts in missing_sidecars:
            feedback.pushWarning(
                f"Missing sidecars for {fname}: {', '.join(exts)} "
                "(continuing anyway)"
            )

        # 1. Prepare
        feedback.pushInfo("Preparing job…")
        try:
            prepare = self._client.prepare_job(
                tenant_public_id=self._task_def.get("tenantPublicId", ""),
                worker_id=self._task_def.get("id", ""),
                version_tag=self._task_def.get("version", ""),
                input_schema_with_args=schema,
                machine_type=machine_type,
            )
        except ApiError as exc:
            raise QgsProcessingException(f"Prepare failed: {exc}") from exc
        job_id = prepare.jobId
        feedback.pushInfo(f"Job created: {job_id}")
        feedback.pushInfo(f"Upload deadline: {prepare.uploadDeadline}")

        # 2. Upload any required files to the signed GCS URLs
        uploads: list[tuple[str, str]] = []
        for entry in prepare.inputSchemaWithArgs:
            for item in entry.get("directoryTree") or []:
                if "uploadUrl" in item:
                    local = resolve_local_path(entry["args"], item["path"])
                    uploads.append((local, item["uploadUrl"]))

        if uploads:
            feedback.pushInfo(f"Uploading {len(uploads)} file(s)…")
            for i, (local, url) in enumerate(uploads, 1):
                if feedback.isCanceled():
                    self._safe_cancel(job_id)
                    raise QgsProcessingException("Cancelled by user.")
                feedback.pushInfo(
                    f"  [{i}/{len(uploads)}] {os.path.basename(local)}"
                )
                try:
                    upload_file_to_gcs(local, url)
                except FileNotFoundError as exc:
                    self._safe_cancel(job_id)
                    raise QgsProcessingException(
                        f"File not found: {exc}"
                    ) from exc
                except Exception as exc:
                    self._safe_cancel(job_id)
                    raise QgsProcessingException(
                        f"Upload failed: {exc}"
                    ) from exc
                # Reserve 0–30% of the progress bar for uploads.
                feedback.setProgress(int(i / max(len(uploads), 1) * 30))
        else:
            feedback.pushInfo("No file uploads required.")

        if feedback.isCanceled():
            self._safe_cancel(job_id)
            raise QgsProcessingException("Cancelled by user.")

        # 3. Submit
        feedback.pushInfo("Submitting job…")
        try:
            submit = self._client.submit_job(job_id)
        except ApiError as exc:
            raise QgsProcessingException(f"Submit failed: {exc}") from exc
        feedback.pushInfo(f"Job status: {submit.status}")
        feedback.setProgress(35)

        # 4. Poll until terminal
        last_log_preview = ""
        job = None
        while True:
            if feedback.isCanceled():
                self._safe_cancel(job_id)
                raise QgsProcessingException("Cancelled by user.")
            time.sleep(_POLL_INTERVAL_SECONDS)
            try:
                job = self._client.get_job(job_id)
            except Exception as exc:
                # Transient polling errors shouldn't kill the algorithm —
                # surface them and try again on the next tick.
                feedback.pushWarning(f"Status poll failed: {exc}")
                continue

            if job.logPreview and job.logPreview != last_log_preview:
                old_lines = last_log_preview.splitlines()
                new_lines = job.logPreview.splitlines()
                for line in new_lines[len(old_lines):]:
                    feedback.pushInfo(line)
                last_log_preview = job.logPreview

            if job.status in TERMINAL_STATUS_NAMES:
                break

        feedback.setProgress(100)
        if job.status != "SUCCESS":
            raise QgsProcessingException(
                f"Job ended with status: {job.status}"
            )

        if job.hasOutputFiles:
            feedback.pushInfo(
                "Outputs available in the NikaPlanet panel under "
                "Job History → this job → Outputs tab."
            )
        return {"jobId": job_id, "status": job.status}

    def _safe_cancel(self, job_id: str) -> None:
        if not self._client:
            return
        try:
            self._client.cancel_job(job_id)
        except Exception:
            pass

    # -- boilerplate -------------------------------------------------------

    def createInstance(self):
        return RemoteAlgorithm(self._task_def, self._client)
