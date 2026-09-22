# Uncertainty Grading

Standalone Flask application for collecting human ratings of AI Worker behavior in Common Ground puzzle dialogues.

The folder is intentionally runtime-only. It contains the frozen A-E study conditions, participant assignments, web application, and empty directories for newly collected responses. Historical results, analysis code, source corpora, stimulus builders, and old environments are not included.

## Quick Start

Open PowerShell in this folder:

```powershell
.\run.ps1
```

The application opens at:

```text
http://127.0.0.1:5004
```

The app uses the parent project environment at `..\.venv`. It does not create or
use a virtual environment inside this folder.

Manual setup and validation:

```powershell
.\setup.ps1
.\doctor.ps1
.\run.ps1
```

A Command Prompt wrapper is also available:

```bat
run.cmd
```

## Included Conditions

| Condition | Frozen version | Description |
| --- | --- | --- |
| A | A | Original Worker responses |
| B | B | Original responses with candidate pieces shown |
| C | C5 | Unambiguous piece descriptions |
| D | D2 | C5 descriptions with primarily correctness-targeted uncertainty |
| E | E1 | C5 descriptions with uncertainty selected from Worker model entropy |

Each condition supports both rating types:

- `CB`: rating before the current Worker response
- `CA`: rating after the current Worker response

The frozen matrix contains 478 rows per condition and 2,390 rows total.

## Validate the Installation

Run:

```powershell
.\doctor.ps1
```

The check validates:

- the snapshot matrix and condition versions;
- every snapshot JSON file;
- every referenced target and Worker board image;
- the participant roster schema;
- credential and participant-ID uniqueness;
- condition, arm, and dialogue assignments.

Direct CLI equivalent:

```powershell
..\.venv\Scripts\python.exe -m uncertainty_grading doctor
```

## Participant Credentials

The live assignment file is:

```text
data\participant_roster.csv
```

Generate credentials with the CLI. Always preview first:

```powershell
..\.venv\Scripts\python.exe -m uncertainty_grading credentials `
  --condition E --arm CA --dialogues nonshared --view nonshared `
  --pair --n 1 --dry-run
```

Remove `--dry-run` to append the rows:

```powershell
..\.venv\Scripts\python.exe -m uncertainty_grading credentials `
  --condition E --arm CA --dialogues nonshared --view nonshared `
  --pair --n 1
```

The generator archives the roster before changing it. New archive directories are created only when needed.

## Runtime Data

The application creates these directories automatically:

```text
data\raw\              participant event streams
data\gradings\         rating-focused JSONL records
data\exports\          generated CSV exports
data\roster_snapshots\ roster backups created before changes
```

They are empty in the cleaned distribution. Treat future contents and `participant_roster.csv` as sensitive study data.

The application uses local append-only files and should run as a single application instance. Do not scale to multiple instances without moving writes to shared durable storage.

## Frozen Stimuli

Only files needed to serve the conditions are retained:

```text
stimuli\snapshot_matrix.csv
stimuli\practice_manifest.json
stimuli\snapshots\
stimuli\boards\
```

The original source corpora and rebuild pipeline were deliberately removed. Restore them from their source repository if the frozen stimuli must be regenerated.

## Local Configuration

Configuration uses `UNCERTAINTY_GRADING_*` environment variables. Legacy `STUDY4_*` names remain accepted.

Common settings:

| Variable | Default |
| --- | --- |
| `UNCERTAINTY_GRADING_HOST` | `127.0.0.1` |
| `UNCERTAINTY_GRADING_PORT` | `5004` |
| `UNCERTAINTY_GRADING_SECRET_KEY` | insecure development value |
| `UNCERTAINTY_GRADING_DEBUG` | `true` |
| `UNCERTAINTY_GRADING_COOKIE_SECURE` | `true` |
| `UNCERTAINTY_GRADING_TRUST_PROXY_PROTO` | `true` |
| `UNCERTAINTY_GRADING_HSTS_ENABLED` | `true` |
| `UNCERTAINTY_GRADING_HSTS_MAX_AGE` | `31536000` |
| `UNCERTAINTY_GRADING_HSTS_INCLUDE_SUBDOMAINS` | `true` |
| `UNCERTAINTY_GRADING_HSTS_PRELOAD` | `false` |
| `UNCERTAINTY_GRADING_PROLIFIC_COMPLETION_URL` | placeholder URL |
| `UNCERTAINTY_GRADING_PROLIFIC_COMPLETION_CODE` | empty |

Local `run.ps1` disables Secure cookies, HSTS, and proxy trust for localhost HTTP without changing production defaults.

## Production Run

Set at least:

```powershell
$env:UNCERTAINTY_GRADING_SECRET_KEY = '<long-random-secret>'
$env:UNCERTAINTY_GRADING_DEBUG = 'false'
$env:UNCERTAINTY_GRADING_COOKIE_SECURE = 'true'
$env:UNCERTAINTY_GRADING_HSTS_ENABLED = 'true'
$env:UNCERTAINTY_GRADING_TRUST_PROXY_PROTO = 'true'
```

Validate production configuration:

```powershell
..\.venv\Scripts\python.exe -m uncertainty_grading doctor --production
```

Start with Waitress:

```powershell
.\run.ps1 -Production -HostName 0.0.0.0 -Port 5004
```

For Linux deployments, `startup.sh` launches Gunicorn.

## Minimal Layout

```text
uncertainty_grading\
  app.py, routes.py       Flask app and participant flow
  assignment.py           roster-driven assignments
  storage.py              event, grading, and export storage
  settings.py             local paths and configuration
  cli.py, __main__.py     serve, doctor, and credentials commands
  setup.ps1               creates the local runtime environment
  run.ps1, run.cmd        local or production launchers
  doctor.ps1              installation validation
  data\                    live roster and future outputs only
  stimuli\                frozen A-E snapshots and boards
  templates\, static\     user interface
```
