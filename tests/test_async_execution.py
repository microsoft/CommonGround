import argparse
import asyncio
import contextlib
import io
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

from openai import AsyncOpenAI, DefaultAsyncHttpxClient

import ai.agents as agents
import ai.async_executor as executor_module
import ai.client as client_module
import ai.integration as integration
import ai_vs_ai
import game_session
import routes
import socket_handlers
import web_app
from ai.async_executor import AsyncExecutor
from utils import settings


async def running_loop():
    await asyncio.sleep(0)
    return asyncio.get_running_loop()


class AsyncExecutorTests(unittest.TestCase):
    def setUp(self):
        self.executor = AsyncExecutor()
        self.addCleanup(self.executor.shutdown)

    def test_repeated_calls_keep_the_same_loop_open(self):
        first = self.executor.run_async(running_loop())
        second = self.executor.run_async(running_loop())
        self.assertIs(first, second)
        self.assertTrue(first.is_running())
        self.assertFalse(first.is_closed())

    def test_concurrent_callers_share_one_loop(self):
        with ThreadPoolExecutor(max_workers=4) as callers:
            loops = list(callers.map(
                lambda _: self.executor.run_async(running_loop()), range(12)))
        self.assertTrue(all(loop is loops[0] for loop in loops))
        self.assertTrue(loops[0].is_running())

    def test_coroutine_errors_propagate_without_closing_the_loop(self):
        async def fail():
            raise ValueError('test failure')

        with self.assertRaisesRegex(ValueError, 'test failure'):
            self.executor.run_async(fail())
        self.assertTrue(self.executor.run_async(running_loop()).is_running())

    def test_background_callback_uses_the_same_loop(self):
        loop = self.executor.run_async(running_loop())
        finished = threading.Event()
        results = []

        def callback(result):
            results.append(result)
            finished.set()

        self.executor.run_async_in_background(running_loop(), callback)
        self.assertTrue(finished.wait(5))
        self.assertEqual(results, [loop])
        self.assertFalse(loop.is_closed())

    def test_background_failures_are_logged_and_reported(self):
        async def fail():
            raise ValueError('background test failure')

        finished = threading.Event()
        results = []

        def callback(result):
            results.append(result)
            finished.set()

        with self.assertLogs('ai.async_executor', level='ERROR') as logs:
            self.executor.run_async_in_background(fail(), callback)
            self.assertTrue(finished.wait(5))
        self.assertEqual(results, [None])
        self.assertIn('background test failure', '\n'.join(logs.output))

    def test_shutdown_closes_the_loop_and_rejects_new_work(self):
        loop = self.executor.run_async(running_loop())
        self.executor.shutdown()
        self.assertTrue(loop.is_closed())
        self.assertFalse(self.executor.is_running)
        with self.assertRaisesRegex(RuntimeError, 'shut down'):
            self.executor.run_async(running_loop())

    def test_reentrant_sync_dispatch_fails_instead_of_deadlocking(self):
        async def reenter():
            return self.executor.run_async(running_loop())

        with self.assertRaisesRegex(RuntimeError, 'own event loop'):
            self.executor.run_async(reenter(), timeout=2)
        self.assertTrue(self.executor.run_async(running_loop()).is_running())

    def test_timeout_cancels_pending_work(self):
        cancelled = threading.Event()

        async def wait():
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()

        with self.assertRaises(FutureTimeoutError):
            self.executor.run_async(wait(), timeout=0.1)
        self.assertTrue(cancelled.wait(5))
        self.assertTrue(self.executor.run_async(running_loop()).is_running())


class LoopBoundSDK:
    """Offline transport that rejects closed-loop and cross-loop client reuse."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=self)
        self.owner_loop = None
        self.requests = []
        self.closed = False
        self.close_loop = None

    async def create(self, *, messages, **kwargs):
        loop = asyncio.get_running_loop()
        if self.owner_loop is None:
            self.owner_loop = loop
        elif self.owner_loop.is_closed():
            raise RuntimeError('Event loop is closed')
        elif self.owner_loop is not loop:
            raise RuntimeError('Client reused on a different event loop')
        if self.closed:
            raise RuntimeError('Client is closed')
        self.requests.append(messages)
        content = f'MESSAGE: "reply {len(self.requests)}"'
        await asyncio.sleep(0)
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=content)),
        ])

    async def close(self):
        self.close_loop = asyncio.get_running_loop()
        self.closed = True


class AIConversationLoopTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.executor = AsyncExecutor()
        self.stack.callback(self.executor.shutdown)
        self.sdk = LoopBoundSDK()
        self.stack.enter_context(
            patch.object(executor_module, '_shared_executor', self.executor))
        self.stack.enter_context(patch.object(client_module, 'ai_client', None))
        self.initialize_client = self.stack.enter_context(
            patch.object(client_module.AIClient, '_initialize_client', return_value=self.sdk))
        self.stack.enter_context(
            patch.object(integration, 'get_trial_logger', return_value=Mock()))
        self.stack.enter_context(patch.object(agents, 'open', mock_open(), create=True))
        for module in (client_module, integration, agents):
            self.stack.enter_context(patch.object(module, 'logger', Mock()))
        for module in (game_session, routes, socket_handlers):
            self.stack.enter_context(patch.object(module, 'LOGGING_AVAILABLE', False))
        self.stack.enter_context(patch.dict(game_session.user_sessions, clear=True))
        self.stack.enter_context(patch.dict(web_app.app.config, {
            'TESTING': True,
            'AUTO_START_MODE': 'worker',
            'RUN_STUDY_MODE': False,
        }))
        self.stack.enter_context(patch.object(settings, 'HELPER_PROACTIVE', True))
        self.stack.enter_context(patch.object(settings, 'HELPER_GUIDANCE_FREQUENCY', 1))
        self.stack.enter_context(patch.object(
            game_session.GameSession, '_load_puzzles', return_value=[{
                'puzzle_number': 1, 'tiles': [0], 'positions': [[0, 0]],
                'group': 'Shared view', 'condition': 'control',
            }]))
        self.tasks = []
        self.stack.enter_context(patch.object(
            web_app.socketio, 'start_background_task',
            side_effect=lambda target, *args, **kwargs: self.tasks.append((target, args, kwargs))))
        self.stack.enter_context(patch.object(web_app.socketio, 'sleep'))
        self.stack.callback(client_module._close_cached_client)

    def join(self, role, modes=None):
        client = web_app.app.test_client()
        self.assertEqual(client.get(f'/{role}').status_code, 200)
        with client.session_transaction() as session:
            session_id = session['game_session_id']
        socket = web_app.socketio.test_client(web_app.app, flask_test_client=client)
        self.addCleanup(socket.disconnect)
        payload = {'flask_game_session_id': session_id}
        if modes is not None:
            payload.update(worker_mode=modes[0], helper_mode=modes[1])
        socket.emit(f'join_as_{role}', payload)
        self.assertIn('joined', [event['name'] for event in socket.get_received()])
        return socket, game_session.user_sessions[session_id]

    def drain_tasks(self):
        while self.tasks:
            target, args, kwargs = self.tasks.pop(0)
            target(*args, **kwargs)

    def ai_messages(self, socket):
        events = socket.get_received()
        self.assertFalse([event for event in events if event['name'] == 'error'])
        return [
            event['args'][0]['message']
            for event in events
            if event['name'] == 'chat_message' and event['args'][0]['is_llm']
        ]

    def test_initial_helper_reply_followups_and_other_sessions_share_the_loop(self):
        socket, game = self.join('worker')
        socket.emit('start_trial', {'flask_game_session_id': game.session_id})
        self.drain_tasks()
        self.assertEqual(self.ai_messages(socket), ['reply 1'])
        self.assertFalse(self.sdk.owner_loop.is_closed())

        for number, message in enumerate(('which one?', 'where does it go?'), start=2):
            socket.emit('send_message', {
                'flask_game_session_id': game.session_id,
                'sender': 'worker', 'message': message,
            })
            self.drain_tasks()
            self.assertEqual(self.ai_messages(socket), [f'reply {number}'])
            self.assertFalse(self.sdk.owner_loop.is_closed())

        other_socket, other_game = self.join('worker')
        self.assertIs(game.async_executor, other_game.async_executor)
        self.assertIs(game.agent_controller.ai_client, other_game.agent_controller.ai_client)
        other_socket.emit('start_trial', {'flask_game_session_id': other_game.session_id})
        self.drain_tasks()
        self.assertEqual(self.ai_messages(other_socket), ['reply 4'])
        self.assertEqual(self.ai_messages(socket), [])
        self.assertNotIn('which one?', str(self.sdk.requests[-1]))
        self.assertIs(self.sdk.owner_loop, self.executor.loop)

    def test_repeated_ai_worker_trials_reuse_the_loop(self):
        for helper_mode, launch_mode in (('human', 'helper'), ('llm', None)):
            with self.subTest(helper_mode=helper_mode):
                web_app.app.config['AUTO_START_MODE'] = launch_mode
                socket, game = self.join('helper', modes=('llm', helper_mode))
                original_action = game.get_llm_worker_action

                async def one_action():
                    try:
                        return await original_action()
                    finally:
                        game.trial_active = False

                with patch.object(game, 'get_llm_worker_action', one_action):
                    for _ in range(2):
                        first_reply = len(self.sdk.requests) + 1
                        reply_count = 2 if helper_mode == 'llm' else 1
                        socket.emit('start_trial', {'flask_game_session_id': game.session_id})
                        self.drain_tasks()
                        self.assertEqual(self.ai_messages(socket), [
                            f'reply {number}' for number in range(first_reply, first_reply + reply_count)
                        ])
                        self.assertFalse(self.sdk.owner_loop.is_closed())
        self.assertIs(self.sdk.owner_loop, self.executor.loop)

    def test_sync_completions_reuse_the_web_client_loop(self):
        socket, game = self.join('worker')
        socket.emit('start_trial', {'flask_game_session_id': game.session_id})
        self.drain_tasks()
        client = client_module.get_ai_client()
        for number in (2, 3):
            response = client.get_chat_completion_sync([
                {'role': 'user', 'content': 'Offline test'},
            ])
            self.assertEqual(response, f'MESSAGE: "reply {number}"')
        self.assertIs(self.sdk.owner_loop, self.executor.loop)
        self.assertFalse(self.sdk.owner_loop.is_closed())

    def test_real_sdk_reuses_a_local_http_connection_for_followups(self):
        peers = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                peers.append(self.client_address)
                body = json.dumps({
                    'id': 'offline-completion',
                    'object': 'chat.completion',
                    'created': 0,
                    'model': 'offline-model',
                    'choices': [{
                        'index': 0,
                        'message': {'role': 'assistant', 'content': f'reply {len(peers)}'},
                        'finish_reason': 'stop',
                    }],
                }).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        with contextlib.ExitStack() as resources:
            server = resources.enter_context(ThreadingHTTPServer(('127.0.0.1', 0), Handler))
            server_thread = threading.Thread(
                target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
            server_thread.start()
            resources.callback(server_thread.join, 5)
            resources.callback(server.shutdown)
            sdk = AsyncOpenAI(
                api_key='offline-test-key',
                base_url=f'http://127.0.0.1:{server.server_port}/v1',
                http_client=DefaultAsyncHttpxClient(trust_env=False),
                max_retries=0, timeout=2.0,
            )
            resources.callback(lambda: self.executor.run_async(sdk.close(), timeout=5))
            resources.callback(client_module._close_cached_client)
            resources.enter_context(patch.object(settings, 'OPENAI_GPT4_DEPLOYMENT', 'offline-model'))
            self.initialize_client.return_value = sdk
            client = client_module.get_ai_client()
            for number, message in enumerate(('Start', 'which one?', 'Thanks'), start=1):
                response = client.get_chat_completion_sync([{'role': 'user', 'content': message}])
                self.assertEqual(response, f'reply {number}')
            self.assertEqual(len(peers), 3)
            self.assertEqual(len(set(peers)), 1)
        self.assertFalse(server_thread.is_alive())
        self.assertTrue(sdk.is_closed())

    def test_concurrent_sessions_initialize_only_one_client(self):
        def initialize():
            time.sleep(0.01)
            return self.sdk

        self.initialize_client.side_effect = initialize
        with ThreadPoolExecutor(max_workers=4) as callers:
            clients = list(callers.map(lambda _: client_module.get_ai_client(), range(12)))
        self.assertTrue(all(client is clients[0] for client in clients))
        self.initialize_client.assert_called_once()

    def test_headless_mode_keeps_its_existing_single_loop_execution(self):
        asyncio.run(ai_vs_ai.main_async(argparse.Namespace(limit=1, max_turns=1)))
        self.assertEqual(len(self.sdk.requests), 3)
        self.assertNotIn('ERROR:', self.output.getvalue())
        self.assertIsNone(self.executor.loop)

    def test_cached_client_closes_before_the_executor_loop(self):
        client = client_module.get_ai_client()
        client.get_chat_completion_sync([{'role': 'user', 'content': 'Offline test'}])
        client_module._close_cached_client()
        self.assertTrue(self.sdk.closed)
        self.assertIs(self.sdk.close_loop, self.sdk.owner_loop)
        self.assertFalse(self.sdk.owner_loop.is_closed())
        self.assertIsNone(client_module.ai_client)
        self.executor.shutdown()
        self.assertTrue(self.sdk.owner_loop.is_closed())


if __name__ == '__main__':
    unittest.main()
