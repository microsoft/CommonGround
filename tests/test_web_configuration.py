import contextlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from utils.settings import Settings


ROOT = Path(__file__).resolve().parents[1]


class WebConfigurationTests(unittest.TestCase):
    def check_startup(self, checks, dotenv_text='', environment=None):
        env = os.environ.copy()
        for name in (
            'FLASK_SECRET_KEY', 'AUTO_START_MODE', 'SHARED_VIEW_ENABLED',
            'RUN_STUDY_MODE', 'SOCKETIO_ALLOWED_ORIGINS', 'WEBSITE_SITE_NAME',
            'PORT', 'FLASK_DEBUG', 'PYTHONPATH', 'PYTHON_DOTENV_DISABLED',
            'PYTHONOPTIMIZE',
        ):
            env.pop(name, None)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env.update(environment or {})
        with tempfile.TemporaryDirectory() as directory:
            dotenv_path = Path(directory) / '.env'
            dotenv_path.write_text(dotenv_text, encoding='utf-8')
            code = (
                'from functools import partial\n'
                'from unittest.mock import patch\n'
                'import dotenv\n'
                "with patch('dotenv.load_dotenv', partial(dotenv.load_dotenv, "
                f'dotenv_path={str(dotenv_path)!r})):\n'
                '    import web_app\n'
                + textwrap.dedent(checks)
            )
            result = subprocess.run(
                [sys.executable, '-B', '-c', code],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dotenv_is_loaded_before_web_configuration(self):
        self.check_startup(
            """
            assert web_app.app.config['SECRET_KEY'] == 'test-session-key'
            assert web_app.app.config['AUTO_START_MODE'] == 'helper'
            assert web_app.app.config['RUN_STUDY_MODE'] is True
            assert web_app.app.config['SHARED_VIEW_ENABLED'] is False
            assert web_app.socketio.server.eio.cors_allowed_origins == [
                'http://localhost:5000', 'http://127.0.0.1:5000']
            """,
            dotenv_text=(
                'FLASK_SECRET_KEY=test-session-key\n'
                'AUTO_START_MODE=helper\n'
                'RUN_STUDY_MODE=true\n'
                'SHARED_VIEW_ENABLED=false\n'
                'SOCKETIO_ALLOWED_ORIGINS=http://localhost:5000, http://127.0.0.1:5000\n'
            ),
        )

    def test_process_environment_takes_precedence_over_dotenv(self):
        self.check_startup(
            """
            assert web_app.app.config['SECRET_KEY'] == 'environment-session-key'
            assert web_app.app.config['RUN_STUDY_MODE'] is False
            """,
            dotenv_text='FLASK_SECRET_KEY=dotenv-session-key\nRUN_STUDY_MODE=true\n',
            environment={
                'FLASK_SECRET_KEY': 'environment-session-key',
                'RUN_STUDY_MODE': 'false',
            },
        )

    def test_platform_metadata_does_not_change_local_startup(self):
        self.check_startup(
            """
            assert web_app.app.config['SECRET_KEY']
            assert web_app.app.config['SESSION_COOKIE_SECURE'] is False
            assert web_app.app.config['AUTO_START_MODE'] is None
            assert web_app.app.config['RUN_STUDY_MODE'] is False
            assert web_app.app.config['SHARED_VIEW_ENABLED'] is True
            assert web_app.socketio.server.eio.cors_allowed_origins is None
            with patch.object(web_app.socketio, 'run') as run:
                web_app.run_server()
                run.assert_called_once_with(
                    web_app.app, host='0.0.0.0', port=5000, debug=True,
                    allow_unsafe_werkzeug=True)
            """,
            environment={'WEBSITE_SITE_NAME': 'unused-platform-metadata'},
        )

    def test_port_and_debug_configuration_remain_available(self):
        self.check_startup(
            """
            with patch.object(web_app.socketio, 'run') as run:
                web_app.run_server()
                run.assert_called_once_with(
                    web_app.app, host='0.0.0.0', port=5050, debug=False,
                    allow_unsafe_werkzeug=True)
                run.reset_mock()
                web_app.run_server(host='127.0.0.1', port=5051, debug=True)
                run.assert_called_once_with(
                    web_app.app, host='127.0.0.1', port=5051, debug=True,
                    allow_unsafe_werkzeug=True)
            """,
            environment={'PORT': '5050', 'FLASK_DEBUG': '0'},
        )

    def test_health_and_browser_headers_work_over_local_http(self):
        self.check_startup(
            """
            response = web_app.app.test_client().get('/healthz')
            assert response.status_code == 200
            assert response.get_json() == {'status': 'ok'}
            assert response.headers['X-Content-Type-Options'] == 'nosniff'
            assert response.headers['X-Frame-Options'] == 'DENY'
            assert 'Strict-Transport-Security' not in response.headers
            """,
        )


class LocalLogSettingsTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch('utils.settings.load_dotenv', return_value=False))

    def test_default_logs_do_not_depend_on_existing_directories(self):
        with patch('utils.settings.os.path.exists', return_value=True):
            configuration = Settings()
        self.assertEqual(Path(configuration.LOG_DIR), ROOT / 'logs')
        self.assertEqual(Path(configuration.LOGS_DIR), ROOT.parent / 'conversation_logs')

    def test_relative_and_absolute_log_overrides(self):
        for path, expected in (
            ('study-logs', ROOT / 'study-logs'),
            (str(ROOT / 'custom-logs'), ROOT / 'custom-logs'),
        ):
            with self.subTest(path=path), patch.dict(os.environ, {'LOG_DIR': path}):
                self.assertEqual(Path(Settings().LOG_DIR), expected)


if __name__ == '__main__':
    unittest.main()
