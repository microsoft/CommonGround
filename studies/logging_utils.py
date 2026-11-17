"""Event logging for study runs: JSONL events, the exact images each agent saw, and summaries."""
import csv
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class StudyLogger:
    """Writes ``events.jsonl`` and the PNGs behind every agent observation.

    Image data is moved out of the events into ``images/`` so the JSONL stays
    readable; each event keeps the file name instead. Observer-only ``truth``
    images are not stored because they can be re-rendered from the logged actions.
    """

    def __init__(self, run_dir: Optional[Path], save_images: bool = True):
        self.run_dir = Path(run_dir) if run_dir else None
        self.save_images = save_images
        self._lock = threading.Lock()
        self._sequence = 0
        self._handle = None
        if self.run_dir:
            (self.run_dir / 'images').mkdir(parents=True, exist_ok=True)
            self._handle = open(self.run_dir / 'events.jsonl', 'a', encoding='utf-8')

    def write(self, event: Dict[str, Any]) -> None:
        if not self._handle:
            return
        import base64
        with self._lock:
            self._sequence += 1
            record = {k: v for k, v in event.items() if k != 'truth'}
            images = []
            for index, image in enumerate(event.get('images') or []):
                entry = {'label': image['label']}
                if self.save_images:
                    name = f"{self._sequence:05d}_{event.get('role', 'x')}_{index}.png"
                    (self.run_dir / 'images' / name).write_bytes(base64.b64decode(image['png_b64']))
                    entry['file'] = f"images/{name}"
                images.append(entry)
            if 'images' in record:
                record['images'] = images
            self._handle.write(json.dumps(record, default=str) + '\n')
            self._handle.flush()

    def write_trials(self, trials: List[Dict[str, Any]]) -> None:
        if not (self.run_dir and trials):
            return
        with self._lock:
            columns = sorted({key for trial in trials for key in trial})
            with open(self.run_dir / 'trials.csv', 'w', newline='', encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(trials)

    def write_summary(self, summary: Dict[str, Any]) -> None:
        if not self.run_dir:
            return
        with self._lock:
            (self.run_dir / 'summary.json').write_text(
                json.dumps(summary, indent=2, default=str), encoding='utf-8')

    def close(self) -> None:
        with self._lock:
            if self._handle:
                self._handle.close()
                self._handle = None


def new_run_id(experiment: str) -> str:
    import uuid
    return f"{experiment}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
