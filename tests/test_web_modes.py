import contextlib
import io
import re
import sys
import unittest
from unittest.mock import patch

from flask import template_rendered

import game_session
import routes
import run
import socket_handlers
import web_app


class WebModeTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(patch.dict(web_app.app.config, {
            'TESTING': True,
            'AUTO_START_MODE': None,
            'RUN_STUDY_MODE': False,
            'SHARED_VIEW_ENABLED': True,
        }))
        self.stack.enter_context(patch.dict(game_session.user_sessions, clear=True))
        for module in (game_session, routes, socket_handlers):
            self.stack.enter_context(patch.object(module, 'LOGGING_AVAILABLE', False))
        self.controller = self.stack.enter_context(
            patch.object(game_session, 'AgentController', autospec=True))
        self.stack.enter_context(
            patch.object(game_session, 'get_async_executor', autospec=True))
        self.stack.enter_context(patch.object(web_app.socketio, 'run'))
        self.background_task = self.stack.enter_context(
            patch.object(web_app.socketio, 'start_background_task'))

    def launch(self, *args):
        with patch.object(sys, 'argv', ['run.py', *args]):
            run.main()

    def render_page(self, path, client=None):
        client = client or web_app.app.test_client()
        contexts = []

        def capture(sender, template, context, **extra):
            contexts.append(context.copy())

        with template_rendered.connected_to(capture, web_app.app):
            response = client.get(path, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(contexts), 1)
        return client, response, contexts[0]

    def join(self, role, path=None, modes=None):
        client, _, context = self.render_page(path or f'/{role}')
        with client.session_transaction() as session:
            session_id = session['game_session_id']
        socket = web_app.socketio.test_client(
            web_app.app, flask_test_client=client)
        self.addCleanup(socket.disconnect)
        worker_mode, helper_mode = modes or (
            context['auto_worker'] or 'human',
            context['auto_helper'] or 'human',
        )
        socket.emit(f'join_as_{role}', {
            'worker_mode': worker_mode,
            'helper_mode': helper_mode,
            'shared_view': context['shared_view'] == 'true',
            'flask_game_session_id': session_id,
        })
        events = socket.get_received()
        self.assertFalse([event for event in events if event['name'] == 'error'])
        joined = [event for event in events if event['name'] == 'joined']
        self.assertEqual(len(joined), 1)
        return socket, game_session.user_sessions[session_id], joined[0]['args'][0]

    def start_trial(self, socket, game):
        socket.emit('start_trial', {'flask_game_session_id': game.session_id})
        events = socket.get_received()
        self.assertFalse([event for event in events if event['name'] == 'error'])
        self.assertIn('trial_started', [event['name'] for event in events])
        self.assertTrue(game.trial_active)

    def test_helper_command_starts_ai_worker_from_direct_page(self):
        self.launch('human-ai', '--role', 'helper')
        socket, game, joined = self.join('helper')
        self.start_trial(socket, game)
        self.assertEqual((game.worker_mode, game.helper_mode), ('llm', 'human'))
        self.assertEqual((joined['worker_mode'], joined['helper_mode']), ('llm', 'human'))
        self.controller.assert_called_once_with(worker_mode='llm', helper_mode='human')
        self.assertIn('llm_worker_action_loop', [
            call.args[0].__name__ for call in self.background_task.call_args_list
        ])
        self.assertNotIn('LLM modes not active', self.output.getvalue())

    def test_default_command_starts_ai_helper_from_direct_page(self):
        self.launch('human-ai')
        socket, game, joined = self.join('worker')
        self.start_trial(socket, game)
        self.assertEqual((game.worker_mode, game.helper_mode), ('human', 'llm'))
        self.assertEqual((joined['worker_mode'], joined['helper_mode']), ('human', 'llm'))
        self.controller.assert_called_once_with(worker_mode='human', helper_mode='llm')
        self.assertIn('_send_llm_helper_guidance', [
            call.args[0].__name__ for call in self.background_task.call_args_list
        ])

    def test_launcher_roles_override_stale_role_urls(self):
        for human_role, expected in (
            ('helper', ('llm', 'human')),
            ('worker', ('human', 'llm')),
        ):
            self.launch('human-ai', '--role', human_role)
            for page_role in ('worker', 'helper'):
                with self.subTest(human_role=human_role, page_role=page_role):
                    _, _, context = self.render_page(
                        f'/{page_role}?auto_worker=human&auto_helper=human')
                    self.assertEqual(
                        (context['auto_worker'], context['auto_helper']), expected)

    def test_launcher_roles_override_stale_socket_payloads(self):
        for human_role, expected in (
            ('helper', ('llm', 'human')),
            ('worker', ('human', 'llm')),
        ):
            self.launch('human-ai', '--role', human_role)
            for page_role in ('worker', 'helper'):
                with self.subTest(human_role=human_role, page_role=page_role):
                    _, game, joined = self.join(
                        page_role, modes=('human', 'human'))
                    self.assertEqual((game.worker_mode, game.helper_mode), expected)
                    self.assertEqual(
                        (joined['worker_mode'], joined['helper_mode']), expected)

    def test_stale_join_does_not_replace_an_active_ai_session(self):
        self.launch('human-ai', '--role', 'helper')
        socket, game, _ = self.join(
            'helper', path='/helper?auto_worker=llm&auto_helper=human')
        self.start_trial(socket, game)
        loop_id = game.worker_loop_id
        _, rejoined_game, _ = self.join(
            'worker', path=f'/worker?session={game.session_id}',
            modes=('human', 'human'))
        self.assertIs(rejoined_game, game)
        self.assertTrue(game.trial_active)
        self.assertEqual(game.worker_loop_id, loop_id)
        self.assertEqual((game.worker_mode, game.helper_mode), ('llm', 'human'))

    def test_landing_page_still_selects_the_requested_human_role(self):
        for human_role, expected in (
            ('helper', ('llm', 'human')),
            ('worker', ('human', 'llm')),
        ):
            with self.subTest(human_role=human_role):
                self.launch('human-ai', '--role', human_role, '--no-shared-view')
                _, response, context = self.render_page('/')
                self.assertEqual(response.request.path, f'/{human_role}')
                self.assertEqual(
                    (context['auto_worker'], context['auto_helper']), expected)
                self.assertEqual(context['shared_view'], 'false')

    def test_human_human_launcher_still_pairs_two_browsers(self):
        self.launch('human-human')
        links = re.findall(
            r'http://localhost:\d+(/(?:worker|helper)\?\S+)',
            self.output.getvalue())
        self.assertEqual(len(links), 2)
        _, worker_game, _ = self.join('worker', path=links[0])
        _, helper_game, _ = self.join('helper', path=links[1])
        self.assertIs(worker_game, helper_game)
        self.assertEqual(
            (worker_game.worker_mode, worker_game.helper_mode), ('human', 'human'))
        self.controller.assert_not_called()

    def test_manual_pages_still_allow_browser_role_selection(self):
        for role, modes in (
            ('helper', ('llm', 'human')),
            ('worker', ('human', 'llm')),
        ):
            with self.subTest(role=role):
                _, _, context = self.render_page(f'/{role}')
                self.assertIsNone(context['auto_worker'])
                self.assertIsNone(context['auto_helper'])
                _, game, _ = self.join(role, modes=modes)
                self.assertEqual((game.worker_mode, game.helper_mode), modes)

    def test_manual_pages_preserve_explicit_mode_and_view_parameters(self):
        _, game, joined = self.join(
            'helper', path='/helper?auto_worker=llm&auto_helper=human&shared_view=false')
        self.assertEqual((game.worker_mode, game.helper_mode), ('llm', 'human'))
        self.assertFalse(game.shared_view)
        self.assertFalse(joined['shared_view'])

    def test_study_mode_still_requires_consent(self):
        self.launch('human-ai', '--role', 'helper', '--study')
        for path in ('/', '/worker', '/helper'):
            with self.subTest(path=path):
                response = web_app.app.test_client().get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.location, '/consent')

    def test_study_credentials_still_select_roles_without_a_cli_override(self):
        web_app.app.config['RUN_STUDY_MODE'] = True
        for human_role, expected in (
            ('helper', ('llm', 'human')),
            ('worker', ('human', 'llm')),
        ):
            with self.subTest(human_role=human_role):
                client = web_app.app.test_client()
                with client.session_transaction() as session:
                    session.update(
                        consent_given=True, authenticated=True,
                        role='participant', user_function=human_role)
                _, response, context = self.render_page('/', client)
                self.assertEqual(response.request.path, f'/{human_role}')
                self.assertEqual(
                    (context['auto_worker'], context['auto_helper']), expected)


if __name__ == '__main__':
    unittest.main()
