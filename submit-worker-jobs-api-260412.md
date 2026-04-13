# Worker Jobs API Specification

_Excerpt: Prepare · Upload · Submit · Cancel_

## Changelog

### 2026-04-12

> **Action required for desktop clients (QGIS/ArcGIS plugins):** The `/prepare` request format has changed. See [§1 Prepare Job](#1-prepare-job) for the current `inputSchemaWithArgs` structure.

- **Output file inputs** (`type: "file"`, `readonly: false`): `/prepare` records the user's intended output filename via `args` (stored in `input_params`). `/submit` rewrites the Argo CLI arg to `/temp/{jobId}/outputs/{filename}`, where `filename` is extracted from the `args` value. `args` is required for required output file entries.
- **Output folder validation**: required output folders (`type: "folder"`, `readonly: false`) no longer require `args` — the server always sets the path to `/temp/{jobId}/outputs/` and ignores any client-supplied value.
- Updated the "How the server processes each input type" table to include `file, readonly: false`.
- **`/submit` response**: all `200 OK` responses return only `{ jobId, status }` — `argoWorkflowName` is never included. Desktop clients must branch on `status` to determine next action. Terminal states (`EXPIRED`, `UPLOAD_FAILED`, `CANCELLED`, `JOB_FAILED`) return HTTP errors (`400`/`410`), not `200`.
- **`/prepare` 409 handling**: the 409 response body includes `jobId`, `jobStatus`, and `inputSchemaWithArgs` (not `existingJobId` as previously documented). A `PREPARING` 409 is a resume opportunity — upload URLs in `inputSchemaWithArgs` are still valid; clients should upload and call `/submit`. `SUBMITTED` → call `/submit` with the returned `jobId`. `RUNNING` → go directly to SSE stream.

---

This document details the API endpoints for running GeoEngine workers and managing job lifecycle. Clients (NikaPlanet UI, QGIS plugin, ArcGIS plugin) use these endpoints to prepare, submit, monitor, and cancel worker jobs.

Reference:
[Mermaid diagram for run images](https://miro.com/app/board/uXjVKXLnGVA=/?moveToWidget=3458764667052119426&cot=14)

## Authentication

All client-facing endpoints require a Bearer token (Firebase ID token) in the `Authorization` header.

```http
Authorization: Bearer <firebase-id-token>
```

Service-to-service endpoints (Kopf operator, Cloud Tasks) use different auth mechanisms documented per-endpoint.

---

## Client Flow Overview

```
1. POST /api/workers/job/prepare       → get jobId + upload URLs
2. PUT files to GCS signed URLs        → direct upload (skip if no files)
3. POST /api/workers/job/submit        → trigger Argo workflow
4. POST /api/workers/job/{id}/stream-token → get SSE auth token
5. GET  https://stream.../stream/{id}  → SSE log stream
6. POST /api/workers/job/cancel        → cancel (optional)
7. GET  /api/workers/job/list          → job history
8. GET  /api/workers/job/{id}          → job detail
```

---

## 1. Prepare Job

`POST /api/workers/job/prepare`

Validates the worker and version, creates a job record, generates signed upload URLs, and schedules an expiry timer. This is always the first call in the run flow.

### Request Body

The client sends back the worker's `input_schema` (from the version), enriched with:
- `args`: the user's value for this input
- `directoryTree`: (file/folder inputs only) flat list of files to upload with relative paths

```json
{
    "tenantId": "tenant_456",
    "workerName": "pmtiles-converter",
    "versionTag": "1.0.11",
    "machineType": "CPUx3",
    "inputSchemaWithArgs": [
        {
            "name": "input_file",
            "type": "file",
            "readonly": true,
            "required": true,
            "description": "Input vector file",
            "args": "/Users/yl/Downloads/geospatial_data/pp-to-10m-income.csv",
            "directoryTree": [
                { "path": "pp-to-10m-income.csv", "sizeInBytes": 1048576 }
            ]
        },
        {
            "name": "input_folder",
            "type": "folder",
            "readonly": true,
            "required": true,
            "description": "Input folder with shapefiles",
            "args": "/Users/yl/files/my_folder",
            "directoryTree": [
                { "path": "my_folder/a.csv", "sizeInBytes": 1024 },
                { "path": "my_folder/sub/b.csv", "sizeInBytes": 2048 },
                { "path": "my_folder/sub/c.csv", "sizeInBytes": 512 }
            ]
        },
        {
            "name": "output_file",
            "type": "file",
            "readonly": false,
            "required": true,
            "description": "Output pmtiles file",
            "args": "/Users/yl/Downloads/geospatial_data/sub/folder/pp-to-10m-income-(output).pmtiles"
        },
        {
            "name": "output_folder",
            "type": "folder",
            "readonly": false,
            "required": true,
            "description": "Output folder for results",
            "args": "my_output"
        },
        {
            "name": "format",
            "type": "enum",
            "required": false,
            "default": "pmtiles",
            "description": "Output format",
            "enum_values": ["pmtiles"],
            "args": "pmtiles"
        }
    ]
}
```

> **Output file note:** For `output_file` above, the server strips everything before the last `/` and passes `--output_file /temp/{jobId}/outputs/pp-to-10m-income-(output).pmtiles` to Argo. The full local path in `args` is stored in `input_params` for reference but only the filename is used. The output folder (`output_folder`) ignores `args` entirely — the server always passes `--output_folder /temp/{jobId}/outputs/`.

| Field                | Type   | Required | Description                                                                                                  |
| :------------------- | :----- | :------- | :----------------------------------------------------------------------------------------------------------- |
| `tenantId`           | string | Yes      | Tenant UUID                                                                                                  |
| `workerName`         | string | Yes      | Worker name (lowercase alphanumeric, 1-64 chars)                                                             |
| `versionTag`         | string | Yes      | Semver version tag (e.g. `"1.0.11"`)                                                                         |
| `machineType`        | string | No       | Machine type from `constants/machine-types.ts` (default `"CPUx3"`)                                           |
| `inputSchemaWithArgs`| array  | Yes      | The version's `input_schema` array, with `args` (user value) and `directoryTree` (for file/folder uploads)   |

**Why `directoryTree` lives inside each entry (not at the top level)**

Earlier designs used a flat top-level `directoryTree` array shared across all inputs. This broke down when a worker has multiple file or folder inputs — there was no way to know which files belonged to which parameter. Embedding `directoryTree` inside each `inputSchemaWithArgs` entry makes the association explicit, keeps validation self-contained per entry, and allows the server to generate GCS upload paths scoped to the correct parameter name.

**`inputSchemaWithArgs` per-entry fields:**

| Field           | Type   | Present on         | Description                                                                                              |
| :-------------- | :----- | :----------------- | :------------------------------------------------------------------------------------------------------- |
| `name`          | string | All                | Input name from `input_schema`                                                                           |
| `type`          | string | All                | `"file"`, `"folder"`, `"string"`, `"number"`, `"boolean"`, `"enum"`, `"datetime"`                        |
| `readonly`      | bool   | file/folder        | `true` = input (upload to GCS), `false` = output (server sets path)                                      |
| `required`      | bool   | All                | Whether this input is required                                                                           |
| `args`          | string | All except output folders | User's value. For input file/folder: local path (used to derive `directoryTree`). For **output file**: the desired output filename or path — only the final path segment is used (e.g. `"/local/sub/result.pmtiles"` → `"result.pmtiles"`). For **output folder**: ignored by server — omit or pass any value. For scalars: the literal value. |
| `directoryTree` | array  | file/folder (readonly=true) | Files to upload. Each: `{ path, sizeInBytes }`. Path is relative to the folder root, preserving structure. |

**How the server processes each input type:**

| Type + readonly | What `/prepare` does | What `/submit` rewrites arg to |
| :-------------- | :------------------- | :----------------------------- |
| `file`, `readonly: true` | Generates upload URL for `{jobId}/inputs/{path}` | `--name /temp/{jobId}/inputs/{filename}` |
| `folder`, `readonly: true` | Generates upload URLs for each file in `directoryTree` under `{jobId}/inputs/{folderName}/...` | `--name /temp/{jobId}/inputs/{folderName}` |
| `file`, `readonly: false` | No upload. Records `args` (output filename) in `input_params`. | `--name /temp/{jobId}/outputs/{filename}` (last path segment of `args`) |
| `folder`, `readonly: false` | No upload. `args` is ignored. | `--name /temp/{jobId}/outputs/` |
| `string`, `number`, `enum`, `boolean`, `datetime` | No upload. | `--name {value}` (passed through as-is) |

### Response `200 OK`

```json
{
    "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "workerId": "550e8400-e29b-41d4-a716-446655440000",
    "workerVersionId": "2398y432-e29b-41d4-a716-446655440000",
    "uploadDeadline": "2026-04-10T11:30:00Z",
    "inputSchemaWithArgs": [
        {
            "name": "input_file",
            "type": "file",
            "args": "/Users/yl/Downloads/geospatial_data/pp-to-10m-income.csv",
            "directoryTree": [
                { "path": "pp-to-10m-income.csv", "sizeInBytes": 1048576, "uploadUrl": "https://storage.googleapis.com/..." }
            ]
        },
        {
            "name": "input_folder",
            "type": "folder",
            "args": "/Users/yl/files/my_folder",
            "directoryTree": [
                { "path": "my_folder/a.csv", "sizeInBytes": 1024, "uploadUrl": "https://storage.googleapis.com/..." },
                { "path": "my_folder/sub/b.csv", "sizeInBytes": 2048, "uploadUrl": "https://storage.googleapis.com/..." },
                { "path": "my_folder/sub/c.csv", "sizeInBytes": 512, "uploadUrl": "https://storage.googleapis.com/..." }
            ]
        },
        {
            "name": "output_folder",
            "type": "folder",
            "args": "my_output"
        },
        {
            "name": "format",
            "type": "enum",
            "args": "pmtiles"
        }
    ]
}
```

| Field                 | Type   | Description                                                                                                               |
| :-------------------- | :----- | :------------------------------------------------------------------------------------------------------------------------ |
| `jobId`               | string | Unique job identifier. Use this for all subsequent calls.                                                                 |
| `workerId`            | string | Resolved worker UUID                                                                                                      |
| `workerVersionId`     | string | Resolved version UUID                                                                                                     |
| `uploadDeadline`      | string | ISO 8601 timestamp. Uploads must complete before this time. Calculated as `max(30 min, totalFileSize / 5 Mbps)` from now. |
| `inputSchemaWithArgs` | array  | Same as request, with `uploadUrl` added to each `directoryTree` entry. Only file/folder (readonly) inputs have uploads.   |

### Error Responses

| Status | Condition                                                                                                                 |
| :----- | :------------------------------------------------------------------------------------------------------------------------ |
| `400`  | Invalid args (don't match `input_schema`), invalid worker name, missing required fields                                   |
| `401`  | Invalid or missing Bearer token                                                                                           |
| `403`  | User doesn't have access to this tenant, or tenant plan is expired/inactive                                               |
| `404`  | Worker not found, version not found, or version is deleted                                                                |
| `409`  | Duplicate active job — same user + worker + version already has a non-terminal job. See 409 handling below. |
| `422`  | Worker is REVOKED                                                                                            |
| `502`  | GAR image not found in Artifact Registry                                                                     |

### 409 Response Shape

All `409` responses include:

```json
{
    "status": 409,
    "error": "A job is already running for this worker version.",
    "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "jobStatus": "RUNNING",
    "inputSchemaWithArgs": [ ... ]
}
```

| Field                 | Type   | Description |
| :-------------------- | :----- | :---------- |
| `jobId`               | string | The existing job's UUID — use this for submit/cancel/stream |
| `jobStatus`           | string | Current status: `PREPARING`, `SUBMITTED`, or `RUNNING` |
| `inputSchemaWithArgs` | array  | Stored input params. If `jobStatus` is `PREPARING`, `directoryTree` entries include `uploadUrl`s that are still valid until `uploadDeadline`. |

### Client Handling by `jobStatus` on 409

Desktop clients must not treat all 409s as errors — a `PREPARING` 409 is a
resumable upload opportunity:

| `jobStatus`  | What client should do |
| :----------- | :-------------------- |
| `PREPARING`  | **Resume upload**: use the returned `jobId` and `inputSchemaWithArgs` (upload URLs still valid). Upload any missing files, then call `/submit` with `jobId`. |
| `SUBMITTED`  | **Skip upload**: call `/submit` with the returned `jobId` (idempotent — returns current status). |
| `RUNNING`    | **Skip to stream**: open SSE stream using the returned `jobId`. |

### Client Behavior After Prepare

1. Iterate through `inputSchemaWithArgs` in the response.
2. For each entry that has `directoryTree` with `uploadUrl`s, upload the local files to GCS using the signed resumable URIs.
3. If no entries have `directoryTree` (no file inputs), proceed directly to Submit.
4. After all uploads complete, call `POST /api/workers/job/submit`.

**Client-side speed check** (recommended): measure throughput on the first uploaded chunk. If `remainingBytes / measuredSpeed > timeUntilDeadline`, abort the upload and show a warning to the user. The server will automatically expire the job after `uploadDeadline`.

### Example: QGIS/ArcGIS Plugin Flow

```python
# 1. User selects worker "pmtiles-converter:1.0.11" in the plugin UI
# 2. Plugin fetches input_schema from GET /api/workers/{id}?version=1.0.11
# 3. User fills in values: picks a local CSV file, picks output folder name
# 4. Plugin builds inputSchemaWithArgs:

input_schema_with_args = [
    {
        "name": "input_file",
        "type": "file",
        "readonly": True,
        "required": True,
        "description": "Input vector file",
        "args": "/Users/yl/Downloads/geospatial_data/pp-to-10m-income.csv",
        "directoryTree": [
            # For a single file: just the filename
            {"path": "pp-to-10m-income.csv", "sizeInBytes": os.path.getsize(local_path)}
        ]
    },
    {
        "name": "output_file",
        "type": "file",
        "readonly": False,
        "required": True,
        "description": "Output pmtiles file",
        # Pass the user's local save path — server extracts only the filename.
        # e.g. "result.pmtiles" → /temp/{jobId}/outputs/result.pmtiles
        "args": "/Users/yl/Downloads/results/pp-to-10m-income-output.pmtiles"
    },
    {
        "name": "output_folder",
        "type": "folder",
        "readonly": False,
        "required": True,
        "description": "Output folder for PMTiles results",
        "args": "my_output"  # ignored by server — output path is always /temp/{jobId}/outputs/
    },
    {
        "name": "format",
        "type": "enum",
        "required": False,
        "default": "pmtiles",
        "enum_values": ["pmtiles"],
        "args": "pmtiles"
    }
]

# For a FOLDER input (e.g. user selects /Users/yl/files/my_folder):
# Plugin walks the local directory and builds directoryTree preserving structure:
folder_input = {
    "name": "input_data",
    "type": "folder",
    "readonly": True,
    "required": True,
    "args": "/Users/yl/files/my_folder",
    "directoryTree": [
        {"path": "my_folder/a.csv", "sizeInBytes": 1024},
        {"path": "my_folder/sub/b.csv", "sizeInBytes": 2048},
        {"path": "my_folder/sub/c.csv", "sizeInBytes": 512},
    ]
}
# Note: paths are relative, rooted at the folder name (not the full local path)

# 5. Call POST /api/workers/job/prepare
resp = requests.post(f"{base_url}/api/workers/job/prepare", json={
    "tenantId": tenant_id,
    "workerName": "pmtiles-converter",
    "versionTag": "1.0.11",
    "machineType": "CPUx3",
    "inputSchemaWithArgs": input_schema_with_args
}, headers={"Authorization": f"Bearer {token}"})

data = resp.json()
job_id = data["jobId"]
upload_deadline = data["uploadDeadline"]

# 6. Upload files using signed URLs from the response
for input_entry in data["inputSchemaWithArgs"]:
    if "directoryTree" not in input_entry:
        continue
    for file_entry in input_entry["directoryTree"]:
        upload_url = file_entry["uploadUrl"]
        local_file = resolve_local_path(input_entry["args"], file_entry["path"])
        upload_to_gcs(local_file, upload_url)

# 7. Submit the job
resp = requests.post(f"{base_url}/api/workers/job/submit", json={
    "jobId": job_id
}, headers={"Authorization": f"Bearer {token}"})
# resp.json() = {"jobId": "...", "status": "SUBMITTED"}
```

---

## 2. Upload Files (Direct to GCS) -- reference only (planned by Claude)

This is NOT an API route in this repo — clients upload directly to GCS using the
signed resumable URIs from the Prepare response.

### Resumable Upload Protocol

```http
PUT <uploadUrl>
Content-Type: application/octet-stream
Content-Length: <file-size>

<file-bytes>
```

For large files, use the [GCS resumable upload protocol](https://cloud.google.com/storage/docs/resumable-uploads):

1. First request: `PUT <uploadUrl>` with `Content-Range: bytes 0-<chunkSize-1>/<totalSize>`
2. Subsequent chunks: `PUT <uploadUrl>` with `Content-Range: bytes <start>-<end>/<totalSize>`
3. Final chunk: response `200 OK` confirms upload completion.

### Client-Side Speed Check (Recommended)

After uploading the first chunk, measure actual throughput:

```
measuredSpeed = chunkSize / uploadDuration  (bytes per second)
remainingBytes = totalSize - chunkSize
estimatedTime = remainingBytes / measuredSpeed
remainingDeadline = uploadDeadline - now()

if estimatedTime > remainingDeadline:
    abort upload
    show warning: "Connection too slow for this file size"
    // Do NOT call /submit — Cloud Tasks will expire the job automatically
```

### What Happens If Upload Is Abandoned

- The Cloud Tasks expiry timer fires at `uploadDeadline`.
- If the job is still in `PREPARING` status, it is marked `EXPIRED`.
- Orphaned GCS objects are cleaned up by a bucket lifecycle policy (7-day auto-delete for unsubmitted uploads).
- The client can check job status via `/job/list` or `/job/{id}` and retry with a new `/prepare` call.

---

## 3. Submit Job

`POST /api/workers/job/submit`

Verifies uploaded files exist in GCS, submits the Argo workflow, and transitions the job to `SUBMITTED`. Call this after all files are uploaded, or immediately after Prepare if the worker has no file inputs.

### Request Body

```json
{
    "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

| Field   | Type   | Required | Description                    |
| :------ | :----- | :------- | :----------------------------- |
| `jobId` | string | Yes      | Job UUID from Prepare response |

### Response `200 OK` — Fresh submit

Returned when the job was in `PREPARING` and Argo accepted the workflow.

```json
{
    "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "SUBMITTED"
}
```

### Response `200 OK` — Idempotent (job already advanced)

If the job has already moved past `PREPARING` into a non-terminal active state (`SUBMITTED`, `RUNNING`, `SUCCESS`), the endpoint returns the current status:

```json
{
    "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "RUNNING"
}
```

This prevents duplicate Argo workflows on client retries.

### Client Handling by `status`

Desktop clients must branch on the `status` field in every `200` response:

| `status` in response | What client should do |
| :------------------- | :-------------------- |
| `SUBMITTED`          | Job is newly queued — open SSE stream, show "Submitted" |
| `RUNNING`            | Job already started — open SSE stream, show "Running" |
| `SUCCESS`            | Job already finished — fetch `/job/{id}` for results |

### Error Responses

| Status | `job.status` that triggered it | Condition |
| :----- | :----------------------------- | :-------- |
| `400`  | `PREPARING` (GCS check failed) | Missing uploaded files — response includes `{ missingFiles: string[] }`. Job transitions to `UPLOAD_FAILED`. |
| `400`  | `UPLOAD_FAILED`                | Previous GCS check failed. Create a new job. |
| `400`  | `CANCELLED`                    | Job was cancelled. Create a new job. |
| `400`  | `JOB_FAILED`                   | Job already failed. Create a new job. |
| `401`  | —                              | Invalid or missing Bearer token |
| `403`  | —                              | Requesting user is not the job creator |
| `404`  | —                              | Job not found |
| `410`  | `EXPIRED`                      | Upload TTL elapsed. Create a new job. |
| `502`  | —                              | Argo workflow submission failed |

## 6. Cancel Job

`POST /api/workers/job/cancel`

Cancels a job. Only the job creator or a tenant OWNER can cancel.

### Request Body

```json
{
    "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### Response `200 OK`

```json
{
    "jobId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "CANCELLED"
}
```

### Cancellation by Job Phase

| Job Status                                                 | What Happens                                                                    |
| :--------------------------------------------------------- | :------------------------------------------------------------------------------ |
| `PREPARING`                                                | No Argo workflow exists. Cloud Tasks expiry is deleted. Job marked `CANCELLED`. |
| `SUBMITTED`                                                | Argo workflow is stopped. Job marked `CANCELLED`.                               |
| `RUNNING`                                                  | Argo workflow is stopped. Job marked `CANCELLED`.                               |
| Terminal (`SUCCESS`, `JOB_FAILED`, `CANCELLED`, `EXPIRED`) | Returns `409` — already in terminal state.                                      |

### Error Responses

| Status | Condition                                          |
| :----- | :------------------------------------------------- |
| `401`  | Invalid or missing Bearer token                    |
| `403`  | User is not the job creator and not a tenant OWNER |
| `404`  | Job not found                                      |
| `409`  | Job is already in a terminal state                 |

---
