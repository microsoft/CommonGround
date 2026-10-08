import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uncertainty_grading import cli, storage
from uncertainty_grading.settings import Settings


class LogFileTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.raw_dir = root / "raw"
        self.gradings_dir = root / "gradings"
        self.raw_dir.mkdir()
        self.gradings_dir.mkdir()
        self.stack.enter_context(patch.multiple(
            storage.S, RAW_DIR=self.raw_dir, GRADINGS_DIR=self.gradings_dir,
        ))
        self.stack.enter_context(patch.dict(storage._LOCKS, {}, clear=True))

    def log_grading(self, credentials):
        storage.log_grading(
            credentials=credentials,
            participant_id="test-participant",
            dialogue_id="test-dialogue",
            condition="A",
            view="shared",
            turn="W1",
            grade=75,
            rt_ms=1000,
            arm="CA",
        )

    def test_valid_event_filenames_and_records_are_preserved(self):
        for identifier in ("0123456789abcdef" * 2, "Participant-1_ab"):
            with self.subTest(identifier=identifier):
                storage.log_event(identifier, "session_started", {"value": 1}, arm="CA")
                storage.log_event(identifier, "completed")
                self.assertEqual(
                    storage._participant_file(identifier),
                    self.raw_dir / f"participant_{identifier}.jsonl",
                )
                events = storage.read_events(identifier)
                self.assertEqual(
                    [event["event_type"] for event in events],
                    ["session_started", "completed"],
                )
                self.assertEqual(events[0]["participant_id"], identifier)
                self.assertEqual(events[0]["data"], {"value": 1})
                self.assertEqual(events[0]["arm"], "CA")

    def test_valid_grading_filename_and_records_are_preserved(self):
        credentials = "0123456789abcdef" * 2
        self.log_grading(credentials)
        self.log_grading(credentials)
        self.assertEqual(
            storage._grading_file(credentials),
            self.gradings_dir / f"grading_{credentials}.jsonl",
        )
        records = storage.read_gradings()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["credentials"], credentials)
        self.assertEqual(records[0]["participant_id"], "test-participant")
        self.assertEqual(records[0]["grade"], 75)

    def test_missing_valid_event_log_is_still_empty(self):
        self.assertEqual(storage.read_events("new-participant"), [])

    def test_invalid_identifiers_are_rejected_without_reading_or_writing(self):
        invalid = (
            "", ".", "..", "../review-user", r"..\review-user",
            "/tmp/review-user", r"C:\temp\review-user",
            r"\\server\share\review-user", "user/subdir", r"user\subdir",
            "user:stream", "user name", "user\n", "user\x00",
            "user.", "%2e%2e%2freview-user", "\u00e9",
        )
        operations = (
            ("log_event", lambda value: storage.log_event(value, "invalid")),
            ("read_events", storage.read_events),
            ("log_grading", self.log_grading),
        )
        with patch.object(Path, "open") as open_file:
            for identifier in invalid:
                for name, operation in operations:
                    with self.subTest(identifier=identifier, operation=name):
                        with self.assertRaises(ValueError):
                            operation(identifier)
            open_file.assert_not_called()
        self.assertEqual(list(self.raw_dir.iterdir()), [])
        self.assertEqual(list(self.gradings_dir.iterdir()), [])
        self.assertEqual(storage._LOCKS, {})

    def test_invalid_identifier_cannot_alias_an_existing_event_log(self):
        storage.log_event("review-user", "original")
        with self.assertRaises(ValueError):
            storage.log_event("../review-user", "different-input")
        self.assertEqual(
            [event["event_type"] for event in storage.read_events("review-user")],
            ["original"],
        )


class GradingCliTests(unittest.TestCase):
    def test_local_server_disables_debugger_even_when_environment_enables_debug(self):
        for host in (None, "0.0.0.0"):
            with self.subTest(host=host), contextlib.ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {
                    "FLASK_DEBUG": "1", "FLASK_RUN_FROM_CLI": "false",
                }))
                stack.enter_context(patch("uncertainty_grading.settings.settings.DEBUG", True))
                stack.enter_context(patch("uncertainty_grading.settings.settings.PORT", 5004))
                stack.enter_context(patch("flask.cli.load_dotenv", return_value=False))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                run = stack.enter_context(patch("werkzeug.serving.run_simple"))

                self.assertEqual(cli.serve(host, 5050, production=False), 0)
                app = run.call_args.args[2]
                self.assertIs(app.debug, False)
                self.assertIs(app.config["SESSION_COOKIE_SECURE"], False)
                self.assertIs(app.config["HSTS_ENABLED"], False)
                self.assertIs(app.config["TRUST_PROXY_PROTO"], False)
                run.assert_called_once_with(
                    host or "127.0.0.1", 5050, app,
                    use_debugger=False, use_reloader=False, threaded=True,
                )

    def test_cli_keeps_local_and_production_arguments(self):
        with patch.object(cli, "serve", return_value=0) as serve:
            self.assertEqual(cli.main([]), 0)
            serve.assert_called_once_with(None, None, False)
            serve.reset_mock()
            self.assertEqual(cli.main([
                "serve", "--host", "127.0.0.1", "--port", "5050", "--production",
            ]), 0)
            serve.assert_called_once_with("127.0.0.1", 5050, True)

    def test_debug_defaults_to_false(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("uncertainty_grading.settings.load_dotenv"),
            patch("uncertainty_grading.settings._ensure_dirs"),
        ):
            self.assertIs(Settings().DEBUG, False)


if __name__ == "__main__":
    unittest.main()
