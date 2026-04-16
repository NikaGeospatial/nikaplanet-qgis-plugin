# QgsProcessingAlgorithm wrapper for remote task definitions fetched from
# the geoengine-control server.
import json
import urllib.request
from typing import Any, Optional

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterString,
)

from ..cloud.auth import AuthManager
from ..util.settings import get_control_server_url

# Map YAML input type + readonly to a QGIS parameter builder.
_PARAM_BUILDERS = {
    ("file", True): lambda inp: QgsProcessingParameterFile(
        inp["name"], inp.get("description", inp["name"]),
    ),
    ("file", False): lambda inp: QgsProcessingParameterFileDestination(
        inp["name"], inp.get("description", inp["name"]),
    ),
}

_DEFAULT_PARAM = lambda inp: QgsProcessingParameterString(
    inp["name"], inp.get("description", inp["name"]),
)


class RemoteAlgorithm(QgsProcessingAlgorithm):
    """A processing algorithm built dynamically from a control-server task
    definition (one entry from the ``GET /list`` response)."""

    def __init__(self, task_def: Optional[dict] = None, auth: Optional[AuthManager] = None):
        super().__init__()
        self._task_def = task_def or {}
        self._auth = auth

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

    # -- parameters --------------------------------------------------------

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        # Loop over each input defined in the YAML's command.inputs array.
        # This builds the parameter dialog that QGIS shows when the user
        # opens this algorithm in the Processing Toolbox.
        for inp in self._task_def.get("inputs") or self._task_def.get("command", {}).get("inputs", []):
            # Look up a QGIS parameter builder based on (type, readonly).
            # e.g. ("file", True)  -> QgsProcessingParameterFile (file picker)
            #      ("file", False) -> QgsProcessingParameterFileDestination (save dialog)
            # Anything else falls back to a plain string input.
            key = (inp.get("type", "string"), inp.get("readonly", False))
            builder = _PARAM_BUILDERS.get(key, _DEFAULT_PARAM)
            param = builder(inp)

            # If the YAML input is not marked required, flag it as optional
            # so QGIS won't enforce it in the dialog.
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
        # Collect the values the user entered in the dialog for each input
        # defined in the YAML. parameterAsString extracts the value as a
        # string regardless of the parameter widget type.
        inputs = {}
        for inp in self._task_def.get("inputs") or self._task_def.get("command", {}).get("inputs", []):
            val = self.parameterAsString(parameters, inp["name"], context)
            if val:
                inputs[inp["name"]] = val

        # Build the JSON payload matching the POST /run schema:
        #   { "task": "<task-name>", "inputs": { "<name>": "<value>", ... } }
        payload = json.dumps({"task": self.name(), "inputs": inputs}).encode()
        url = f"{get_control_server_url()}/run"

        # Send the request to the control server
        feedback.pushInfo(f"POST {url}")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"},
        )
        if self._auth:
            token = self._auth.ensure_valid_token()
            if token:
                req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
        except Exception as exc:
            # Surface server errors as a QGIS processing exception so the
            # error appears in the processing log panel.
            raise QgsProcessingException(f"Control server error: {exc}")

        feedback.pushInfo(f"Response: {body}")
        return {}

    # -- boilerplate -------------------------------------------------------

    def createInstance(self):
        return RemoteAlgorithm(self._task_def, self._auth)
