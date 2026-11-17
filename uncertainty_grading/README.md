# Uncertainty Grading

Standalone Flask application for collecting human ratings of AI Worker behavior in Common Ground puzzle dialogues.

The folder is intentionally runtime-only. It contains the web application for
the A-E study conditions; all original-study manifests and data assets are
supplied locally. Historical results, analysis code, source corpora, stimulus
builders, and old environments are not included in the source tree.

> **Required local study files:** The snapshot matrix, practice manifest, frozen
> JSON snapshots, and rendered board images are excluded from Git checkouts and
> Python distribution packages. Keep your existing `stimuli\` directory, or
> restore matching, authorized study files before starting the app.
> See [Frozen Stimuli](#frozen-stimuli).

## Quick Start

With your Python environment active, open a terminal in this folder:

```powershell
python -m pip install -r requirements.txt  # First-time dependency setup
python run.py
```

Open:

```text
http://127.0.0.1:5004
```

Local grading starts without an access code, Prolific ID, or participant roster.
The defaults are condition **A**, rating type **CA**, the first matching dialogue
in the local snapshot matrix, and that dialogue's original board visibility.
Ratings are saved under a new random local session ID; local mode does not create
study credentials or modify a roster.

To choose another local configuration:

```powershell
python run.py --condition E --arm CA --view nonshared
python run.py --condition A --arm CB --dialogue <dialogue_id> --port 5005
```

Use a dialogue ID from your local snapshot matrix. Run `python run.py --help`
for options. The runner reports missing required stimulus files before starting;
it does not download or regenerate the excluded study assets.

From the repository root, `python uncertainty_grading\run.py` also works. The
runner uses the active interpreter and does not require an editable package
installation. If you already have the parent project's virtual environment but
have not activated it, use:

```powershell
..\.venv\Scripts\python.exe run.py
```

The optional `run.ps1` / `run.cmd` wrappers prefer an active virtual environment,
otherwise use the parent's `.venv` when available. `setup.ps1` installs only the
dependencies. No package installation or doctor command is needed.

## Included Conditions

| Condition | Description |
| --- | --- |
| A | Original Worker responses |
| B | Original responses with candidate pieces shown |
| C | Unambiguous piece descriptions |
| D | Descriptions with primarily correctness-targeted uncertainty |
| E | Descriptions with uncertainty selected from Worker model entropy |

Each condition supports both rating types:

- `CB`: rating before the current Worker response
- `CA`: rating after the current Worker response

The original study matrix contains 478 rows per condition and 2,390 rows total;
it is not distributed with this source release.

The local app goes straight to task instructions, practice ratings, main ratings,
and a completion screen with a button to start another session. Study mode adds
login first. Consent forms, post-task surveys, and the original-study
debrief are not included. Existing sessions retain their rating progress and
skip removed survey steps.


## Optional Study Mode

To use the existing participant login instead of local grading:

```powershell
python run.py --study
```

Study mode requires a Prolific ID and an access code. Conditions, rating types,
dialogues, and views come from the existing live assignment file:

```text
data\participant_roster.csv
```

Credentials are only needed for study mode. Preview new assignments with:

```powershell
python run.py credentials `
  --condition E --arm CA --dialogues nonshared --view nonshared `
  --pair --n 1 --dry-run
```

Remove `--dry-run` to append the rows:

```powershell
python run.py credentials `
  --condition E --arm CA --dialogues nonshared --view nonshared `
  --pair --n 1
```

The generator archives the roster before changing it. New archive directories are created only when needed.
The `--pair --n 1` example requires an even number of at least two non-shared
dialogues. Omit `--pair` for independent single-dialogue assignments.
Use `python run.py credentials --help` for details.

## Runtime Data

The application creates these directories automatically:

```text
data\raw\              participant event streams
data\gradings\         rating-focused JSONL records
data\exports\          generated CSV exports
data\roster_snapshots\ roster backups created before changes
```

They are empty in the cleaned distribution. Treat future contents and `participant_roster.csv` as sensitive study data.
The entire `data\` directory is ignored, including processed results and legacy
roster backups. Never add these records to a source release.

Event and grading log identifiers must be non-empty and contain only ASCII
letters, digits, hyphens, or underscores. Invalid identifiers raise an error
instead of being silently rewritten. Generated 32-character credentials and
their existing log filenames are unchanged.

CSV exports retain legacy survey columns for compatibility with existing logs;
the app no longer collects those survey responses.

The application uses local append-only files and should run as a single application instance. Do not scale to multiple instances without moving writes to shared durable storage.

## Frozen Stimuli

All files below are required local inputs, not versioned release assets:

```text
stimuli\snapshot_matrix.csv
stimuli\practice_manifest.json
stimuli\snapshots\      frozen dialogue and board-state JSON
stimuli\boards\         rendered PNG images
```

On a fresh checkout or deployment, restore the manifests and both asset
directories from an authorized source. The matrix contains study-session
identifiers and per-turn measurements, so it must be handled as study data rather
than generic configuration.

Removing these paths from Git tracking preserves local files but does not erase
older commits. Review historical copies separately before redistributing the
repository. Package builds exclude `stimuli\` and `data\` even when those
directories are populated locally.

The original source corpora and rebuild pipeline were deliberately removed. Restore them from their source repository if the frozen stimuli must be regenerated.

## Local Configuration

Configuration uses `UNCERTAINTY_GRADING_*` environment variables. Legacy `STUDY4_*` names remain accepted.

Common settings:

| Variable | Default |
| --- | --- |
| `UNCERTAINTY_GRADING_HOST` | `127.0.0.1` |
| `UNCERTAINTY_GRADING_PORT` | `5004` |
| `UNCERTAINTY_GRADING_SECRET_KEY` | insecure development value |
| `UNCERTAINTY_GRADING_DEBUG` | `false` |
| `UNCERTAINTY_GRADING_COOKIE_SECURE` | `true` |
| `UNCERTAINTY_GRADING_TRUST_PROXY_PROTO` | `true` |
| `UNCERTAINTY_GRADING_HSTS_ENABLED` | `true` |
| `UNCERTAINTY_GRADING_HSTS_MAX_AGE` | `31536000` |
| `UNCERTAINTY_GRADING_HSTS_INCLUDE_SUBDOMAINS` | `true` |
| `UNCERTAINTY_GRADING_HSTS_PRELOAD` | `false` |
| `UNCERTAINTY_GRADING_PROLIFIC_COMPLETION_URL` | placeholder URL |
| `UNCERTAINTY_GRADING_PROLIFIC_COMPLETION_CODE` | empty |

Local `python run.py` disables Secure cookies, HSTS, and proxy trust for localhost
HTTP without changing production defaults. The local CLI server also disables
Flask debug mode, the interactive debugger,
and the reloader, including when `FLASK_DEBUG` or a study debug setting is enabled.
Use the production server below when serving participants.

## Production Run

Set at least:

```powershell
$env:UNCERTAINTY_GRADING_SECRET_KEY = '<long-random-secret>'
$env:UNCERTAINTY_GRADING_DEBUG = 'false'
$env:UNCERTAINTY_GRADING_COOKIE_SECURE = 'true'
$env:UNCERTAINTY_GRADING_HSTS_ENABLED = 'true'
$env:UNCERTAINTY_GRADING_TRUST_PROXY_PROTO = 'true'
```

Start with Waitress and study login. Required runtime inputs and production
settings are checked at startup:

```powershell
python run.py --production --host 0.0.0.0 --port 5004
```

For Linux deployments, `startup.sh` launches Gunicorn with study login. Install
dependencies beforehand; the startup script does not install packages.

## Minimal Layout

```text
uncertainty_grading\
  app.py, routes.py       Flask app and participant flow
  run.py                  direct local launcher; --study enables login
  assignment.py           local and roster-driven assignments
  storage.py              event, grading, and export storage
  settings.py             local paths and configuration
  cli.py, __main__.py     serve and credentials commands
  setup.ps1               installs dependencies into the selected environment
  run.ps1, run.cmd        local or production launchers
  data\                    live roster and future outputs only
  stimuli\                local-only A-E manifests and study assets
    snapshots\            required local JSON snapshots, excluded from Git
    boards\               required local image assets, excluded from Git
  templates\, static\     user interface
```
