# CommonGround Puzzle

CommonGround is a collaborative puzzle environment for studying **common ground**:
the shared understanding that people and AI establish and maintain while working
together. It supports human-AI, human-human, and fully automated AI-AI games.

> **Research paper**
>
> Christian Poelitz, Finale Doshi-Velez, and Siân Lindley (2026).
> [**A Benchmark to Assess Common Ground in Human-AI Collaboration**](https://arxiv.org/abs/2602.21337).
> arXiv:2602.21337.

The paper introduces the benchmark and examines collaboration under different
levels of situation awareness. See it for the research motivation, study design,
and findings, and use the [BibTeX citation below](#citation) when referencing the
work.

## The task

- The **Worker** selects from 24 colored pattern tiles and places them on a
  **6x6 grid** to reproduce a target pattern.
- The **Helper** sees the target and guides the Worker through chat. The Worker
  cannot see the target.
- In **shared view**, the Helper can also see the Worker's board. In
  **non-shared view**, the Helper must rely on the conversation to track progress.
- Either role can be played by a human or an LLM agent.

The asymmetric information makes the task useful for studying descriptions,
clarification, coordination, and the repair of misunderstandings. The interactive
application uses Flask and Socket.IO; a separate headless runner supports
automated experiments.

## Quick start

Run these commands from the project root.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py human-human
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py human-human
```

The **human-human** mode needs no AI credentials. Open the two links printed by
the launcher in separate browsers or browser profiles, one for each role. Both
links contain the same room identifier.

## AI backend configuration

For human-AI or AI-AI mode, copy [`.env.example`](.env.example) to `.env` if you do
not already have one, then configure one backend:

| Backend | Configuration |
| --- | --- |
| **Standard OpenAI** | Set `OPENAI_API_KEY` to your API key and `OPENAI_GPT4_DEPLOYMENT` to a model name, such as `gpt-4o`. Leave `OPENAI_ENDPOINT` empty. |
| **Azure OpenAI with an API key** | Set `OPENAI_ENDPOINT`, `OPENAI_API_KEY`, `OPENAI_GPT4_DEPLOYMENT`, and `OPENAI_API_VERSION`. Leave `OPENAI_SCOPE` empty. |
| **Azure OpenAI with Entra ID** | Authenticate through Azure CLI or managed identity, then set `OPENAI_ENDPOINT`, `OPENAI_SCOPE`, `OPENAI_GPT4_DEPLOYMENT`, and `OPENAI_API_VERSION`. |

Choose a model or deployment that supports **image inputs**: agents receive
rendered boards and tile images alongside text. For Azure endpoints, a non-empty
`OPENAI_SCOPE` selects Entra ID authentication even if an API key is also set.
AI modes make external model calls and may incur API charges.

## Run modes

| Mode | Who plays | Command |
| --- | --- | --- |
| **human-human** | Two humans in separate browsers | `python run.py human-human` |
| **human-AI** | A human Worker and an AI Helper by default | `python run.py human-ai` |
| **AI-AI** | Two LLM agents, without a browser | `python run.py ai-ai` |

Convenience launchers are also available: `.\run.ps1 <mode>` on Windows and
`./run.sh <mode>` on macOS/Linux. They use the local virtual environment when
available.

### Human-AI

```powershell
python run.py human-ai
python run.py human-ai --role helper      # Human Helper + AI Worker
python run.py human-ai --no-shared-view   # Initial non-shared-view setting
```

Open <http://localhost:5000>; the trial starts automatically. Add `--port 5001`
to use a different port. A puzzle's `group` determines shared view when the trial
starts, overriding the initial CLI setting; see [puzzle configuration](#puzzles-and-experimental-conditions).

### Human-human

The launcher prints a pair of links:

```text
Worker: http://localhost:5000/worker?session=<room>&auto_worker=human&auto_helper=human
Helper: http://localhost:5000/helper?session=<room>&auto_worker=human&auto_helper=human
```

Both players must use the **same** `session=<room>` value to join the same game.
The `localhost` links work on the machine running the server; for another machine,
use the server's reachable hostname or IP address instead.

### AI-AI (headless)

```powershell
python run.py ai-ai                 # All configured puzzles
python run.py ai-ai --limit 1       # Only the first puzzle
python run.py ai-ai --max-turns 15  # Worker-turn limit per puzzle (default: 20)
```

The runner prints the dialogue, actions, and outcome for each puzzle and writes
logs. A puzzle is solved when the Worker's board **exactly matches** the target;
otherwise the runner stops that puzzle at the turn limit.

## Puzzles and experimental conditions

Puzzles are defined in [`utils/puzzles.json`](utils/puzzles.json) and run in file
order. Each entry supports:

| Field | Meaning |
| --- | --- |
| `puzzle_number` | Identifier displayed during the trial. |
| `tiles` / `positions` | Corresponding tile IDs (0-23) and `[x, y]` target cells. Coordinates start at `[0, 0]` in the top-left; each axis ranges from 0 to 5. |
| `group` | `"Shared view"` or `"Non-shared view"`; determines whether the Helper sees the Worker's board. |
| `condition` | `"uncertainty"` selects the AI Worker's ambiguity-aware prompts; `"control"` uses its standard prompts. |
| `require_complete` | If `true`, blocks "Next puzzle" until every target cell contains the correct tile, or the timeout expires. Extra tiles in non-target cells are allowed by this gate. |
| `require_complete_timeout` | Seconds before the completion gate unlocks automatically; defaults to 300. |

**Current configuration:** five four-tile puzzles, all using non-shared view,
the uncertainty condition, and the completion gate. Review these settings before
running a study; the launcher does not randomize or balance conditions.

Tile rendering is defined in [`puzzle_constants.py`](puzzle_constants.py), and
agent instructions are in [`ai/prompts.py`](ai/prompts.py).

## Running a study

The web modes accept `--study` to require consent and login:

```powershell
python run.py human-ai --role helper --study
```

Credentials are loaded from `USER_CREDENTIALS_FILE`, defaulting to
`utils/user_credentials.json`. [`generate_users.py`](generate_users.py) generates
a new credentials file, but its default output is `generated_users.json`; set
`USER_CREDENTIALS_FILE` to that path or explicitly choose an output location.
Do not overwrite credentials for an active study.

Set `FORMS_QUESTIONNAIRE_URL` to direct participants to a post-task questionnaire.
Authenticated admins can download collected logs at `/admin/download_logs`.

## Logging and analysis

Local runs write to [`logs/`](logs/) by default; override the location with
`LOG_DIR`. On Azure App Service, the default is `/home/logs`.

- `sessions/*.jsonl`: per-session event streams, including chat and game actions.
- `summaries/`: session summaries.
- `trial_summary.csv` and `*_detailed.json`: AI trial summaries and detailed records.

Analysis notebooks are in [`log_analysis/`](log_analysis/). Treat credentials,
conversation logs, and participant data as sensitive and keep them out of version
control.

Active game state is held in server memory, not restored from the logs. Restarting
the server loses active boards; multi-process or multi-instance deployment would
require shared session state.

## Companion rating application

[`uncertainty_grading/`](uncertainty_grading/) is a separate Flask application for
collecting human ratings of AI Worker behavior. It presents frozen dialogue and
board snapshots across conditions A-E, with ratings before or after a Worker
response, rather than running live puzzle agents.

See its [README](uncertainty_grading/README.md) for its own setup, participant
assignments, study conditions, and data-handling guidance.

## Project layout

| Path | Responsibility |
| --- | --- |
| [`run.py`](run.py) | Unified launcher for all three modes. |
| [`ai_vs_ai.py`](ai_vs_ai.py) | Headless AI-AI experiment runner. |
| [`web_app.py`](web_app.py), [`routes.py`](routes.py) | Flask application, pages, login, and consent. |
| [`socket_handlers.py`](socket_handlers.py) | Real-time game events and background AI turns. |
| [`game_session.py`](game_session.py) | Game state, board actions, trial progression, and AI integration. |
| [`ai/`](ai/) | Agents, model client, prompts, action parsing, image serialization, and trial logging. |
| [`utils/`](utils/) | Settings, puzzle definitions, and authentication helpers. |
| [`templates/`](templates/), [`static/`](static/) | Browser interfaces and styling. |
| [`web_logger.py`](web_logger.py) | Session event logging. |

Azure deployment helpers include [`deploy_azure.ps1`](deploy_azure.ps1),
[`startup.sh`](startup.sh), [`startup_minimal.sh`](startup_minimal.sh), and
[`puzzle-webapp.service`](puzzle-webapp.service).

## Citation

If you use the benchmark in your research, please cite:

```bibtex
@misc{poelitz2026benchmarkassesscommonground,
  title         = {A Benchmark to Assess Common Ground in Human-AI Collaboration},
  author        = {Christian Poelitz and Finale Doshi-Velez and Si{\^a}n Lindley},
  year          = {2026},
  eprint        = {2602.21337},
  archivePrefix = {arXiv},
  primaryClass  = {cs.HC},
  url           = {https://arxiv.org/abs/2602.21337}
}
```
