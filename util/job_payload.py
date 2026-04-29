"""Shared helpers for building the ``inputSchemaWithArgs`` payload that
``WorkerJobsClient.prepare_job`` accepts.

Used by both the run dialog (``ui/worker_run_dialog.py``) and the
processing-toolbox algorithm (``processing/remote_algorithm.py``) so the
two paths produce byte-identical payloads.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from qgis.core import Qgis, QgsMessageLog

from .messages import PLUGIN_LOG_TAG


SHP_EXTENSIONS = frozenset({".shp", ".shx", ".dbf", ".prj", ".cpg"})
EXPECTED_SHP_SIDECARS = (".shx", ".dbf", ".prj")

# Keys from an input definition that we copy verbatim into the schema entry
# sent to the prepare endpoint.
_PASSTHROUGH_KEYS = (
    "output", "required", "description", "enumValues", "default", "filetypes",
)


def missing_shapefile_sidecars(local_path: str) -> list[str]:
    """Return expected sidecar extensions missing next to ``local_path``.

    Returns [] when the path isn't a shapefile or the file doesn't exist.
    """
    if not local_path or not os.path.isfile(local_path):
        return []
    if os.path.splitext(local_path)[1].lower() != ".shp":
        return []
    directory = os.path.dirname(local_path)
    stem = os.path.splitext(os.path.basename(local_path))[0]
    try:
        names = os.listdir(directory)
    except OSError:
        return list(EXPECTED_SHP_SIDECARS)
    present = {
        os.path.splitext(n)[1].lower()
        for n in names
        if os.path.splitext(n)[0] == stem
    }
    return [ext for ext in EXPECTED_SHP_SIDECARS if ext not in present]


def build_directory_tree(local_path: str, inp_type: str) -> Optional[list[dict]]:
    """Build the ``directoryTree`` array the prepare endpoint expects."""
    if inp_type == "file" and os.path.isfile(local_path):
        entries = [{
            "path": os.path.basename(local_path),
            "sizeInBytes": os.path.getsize(local_path),
        }]
        if os.path.splitext(local_path)[1].lower() == ".shp":
            QgsMessageLog.logMessage(
                f"Shapefile input detected ({os.path.basename(local_path)}), "
                "loading sidecar files…",
                PLUGIN_LOG_TAG,
                Qgis.Info,
            )
            directory = os.path.dirname(local_path)
            stem = os.path.splitext(os.path.basename(local_path))[0]
            found = 0
            for fname in os.listdir(directory):
                fstem, fext = os.path.splitext(fname)
                if fstem != stem or fext.lower() not in SHP_EXTENSIONS:
                    continue
                if fname == os.path.basename(local_path):
                    continue
                full = os.path.join(directory, fname)
                if os.path.isfile(full):
                    entries.append({
                        "path": fname,
                        "sizeInBytes": os.path.getsize(full),
                    })
                    QgsMessageLog.logMessage(
                        f"Discovered {fext.lower()} sidecar: {fname}",
                        PLUGIN_LOG_TAG,
                        Qgis.Info,
                    )
                    found += 1
            if found == 0:
                QgsMessageLog.logMessage(
                    f"No sidecar files found for {os.path.basename(local_path)}",
                    PLUGIN_LOG_TAG,
                    Qgis.Warning,
                )
            else:
                QgsMessageLog.logMessage(
                    f"Bundled {found} sidecar file(s) with "
                    f"{os.path.basename(local_path)}",
                    PLUGIN_LOG_TAG,
                    Qgis.Info,
                )
        return entries
    if inp_type == "folder" and os.path.isdir(local_path):
        parent = os.path.dirname(local_path.rstrip(os.sep))
        tree = []
        for root, _dirs, files in os.walk(local_path):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, parent)
                tree.append({
                    "path": rel,
                    "sizeInBytes": os.path.getsize(full),
                })
        return tree if tree else None
    return None


def build_input_schema_with_args(
    inputs_def: list[dict],
    value_for: Callable[[dict], Optional[str]],
) -> tuple[list[dict], list[tuple[str, list[str]]]]:
    """Build the ``inputSchemaWithArgs`` payload for the prepare endpoint.

    Args:
        inputs_def: The worker's declared inputs (each one a dict with at
            least ``name``, ``type``, and optionally ``output``,
            ``required``, ``description``, ``enumValues``, ``default``,
            ``filetypes``).
        value_for: Callable invoked once per input that returns the user-
            entered value as a string (or None / empty when not set).

    Returns:
        ``(schema_with_args, missing_sidecars)`` where ``missing_sidecars``
        is a list of ``(filename, missing_extensions)`` tuples for any
        ``.shp`` inputs the user picked that are missing standard sidecar
        files. Callers decide how to surface that warning.
    """
    schema: list[dict] = []
    missing_sidecars: list[tuple[str, list[str]]] = []

    for inp_def in inputs_def:
        inp_type = inp_def.get("type", "string")
        is_output = inp_def.get("output", False)
        value = value_for(inp_def)

        entry: dict = {
            "name": inp_def.get("name", ""),
            "type": inp_type,
        }
        for key in _PASSTHROUGH_KEYS:
            if key in inp_def:
                entry[key] = inp_def[key]

        if is_output and value and inp_type == "folder":
            entry["args"] = value if value.endswith("/") else value + "/"
        elif value:
            entry["args"] = value

        if not is_output and value and inp_type in ("file", "folder"):
            tree = build_directory_tree(value, inp_type)
            if tree:
                entry["directoryTree"] = tree
            if inp_type == "file":
                missing = missing_shapefile_sidecars(value)
                if missing:
                    missing_sidecars.append((os.path.basename(value), missing))

        schema.append(entry)

    return schema, missing_sidecars
