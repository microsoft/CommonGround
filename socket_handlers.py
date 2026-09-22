"""
Socket.IO event handlers for puzzle collaboration web app.
Registered via register_handlers() in web_app.py.
"""
import asyncio
import time
import os
from flask_socketio import emit, join_room
from flask import request, session
from datetime import datetime

from game_session import (
    user_sessions, get_user_session_id, get_session_id_from_data,
    get_or_create_game_session, get_game_session,
    LOGGING_AVAILABLE
)

# Import logger factory if available
if LOGGING_AVAILABLE:
    from web_logger import get_user_session_logger


def register_handlers(socketio, app):
    """Register all Socket.IO event handlers."""

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        print(f"Client connected: {request.sid}")
        
        session_id = get_user_session_id()
        if session_id and LOGGING_AVAILABLE:
            user_logger = get_user_session_logger()
            user_logger.log_socket_event(
                session_id=session_id,
                event_name='connect',
                data={'socket_id': request.sid}
            )

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        print(f"Client disconnected: {request.sid}")
        
        session_id = get_user_session_id()
        game_session = get_game_session()
        
        if game_session:
            if game_session.session_logger:
                role = 'worker' if game_session.worker_sid == request.sid else 'helper'
                game_session.session_logger.log_socket_event(
                    session_id=session_id,
                    event_name='disconnect',
                    data={'socket_id': request.sid, 'role': role}
                )
            
            if game_session.worker_sid == request.sid:
                game_session.worker_sid = None
                print(f"[DEBUG] Worker disconnected from session {session_id}")
            elif game_session.helper_sid == request.sid:
                game_session.helper_sid = None
                print(f"[DEBUG] Helper disconnected from session {session_id}")

    @socketio.on('join_as_worker')
    def handle_join_worker(data):
        """Worker joins the game session."""
        SHARED_VIEW_ENABLED = app.config.get('SHARED_VIEW_ENABLED', True)
        RUN_STUDY_MODE = app.config.get('RUN_STUDY_MODE', False)

        worker_mode = data.get('worker_mode', 'human')
        helper_mode = data.get('helper_mode', 'human')
        shared_view = data.get('shared_view', SHARED_VIEW_ENABLED)
        
        session_id = get_session_id_from_data(data)
        print(f"[DEBUG] Worker joining with session_id={session_id}, worker_mode={worker_mode}, helper_mode={helper_mode}, shared_view={shared_view}")
        print(f"[ISOLATION-CRITICAL] WORKER JOIN: session_id={session_id}, socket_id={request.sid}, flask_game_session_id from client={data.get('flask_game_session_id', 'MISSING')}")
        
        game_session = get_or_create_game_session(session_id, worker_mode, helper_mode, shared_view, socket_id=request.sid)
        game_session.worker_sid = request.sid
        
        try:
            user_id = session.get('user_id', session_id)
            prolific_pid = session.get('prolific_pid', '')
            study_id = session.get('study_id', '')
            custom_session_id = session.get('custom_session_id', '')
            user_function = session.get('user_function', 'worker')
        except RuntimeError:
            user_id = data.get('flask_user_id', session_id)
            prolific_pid = data.get('prolific_pid', '')
            study_id = data.get('study_id', '')
            custom_session_id = data.get('flask_custom_session_id', '')
            user_function = 'worker'
            print(f"[DEBUG] Flask session not available, using client-provided data")
        
        game_session.user_id = user_id
        game_session.prolific_pid = prolific_pid
        game_session.study_id = study_id
        game_session.user_function = user_function
        print(f"[USER-INFO] Worker session user_id={user_id}, prolific_pid={prolific_pid}, study_id={study_id}, function={user_function}")
        
        if game_session.session_logger:
            game_session.session_logger.start_session(
                session_id=session_id,
                user_id=user_id or prolific_pid or session_id,
                role='worker',
                config={
                    'worker_mode': worker_mode,
                    'helper_mode': helper_mode,
                    'shared_view': shared_view,
                    'study_mode': RUN_STUDY_MODE,
                    'study_id': study_id,
                    'custom_session_id': custom_session_id,
                    'prolific_pid': prolific_pid
                }
            )
            
            game_session.session_logger.log_socket_event(
                session_id=session_id,
                event_name='join_as_worker',
                data={
                    'worker_mode': worker_mode,
                    'helper_mode': helper_mode,
                    'shared_view': shared_view,
                    'socket_id': request.sid
                }
            )
        
        print(f"[SESSION-DEBUG] Worker joining room: session_id={session_id}, socket_id={request.sid}")
        print(f"[SESSION-DEBUG] All active sessions: {list(user_sessions.keys())}")
        print(f"[SESSION-DEBUG] GameSession object id for this session: {id(game_session)}")
        print(f"[ISOLATION-CRITICAL] WORKER ROOM JOIN: About to join room={session_id}")
        print(f"[ISOLATION-CRITICAL] IMPORTANT: This socket ({request.sid}) should ONLY receive broadcasts to room={session_id}")
        print(f"[ISOLATION-CRITICAL] If this socket receives broadcasts from other session IDs, there is a ROOM COLLISION BUG")
        join_room(session_id)
        print(f"[ISOLATION-CRITICAL] WORKER ROOM JOINED: socket {request.sid} is now in room {session_id}")
        
        emit('joined', {
            'role': 'worker',
            'session_id': session_id,
            'worker_mode': worker_mode,
            'helper_mode': helper_mode,
            'shared_view': shared_view,
            'piece_images': game_session.piece_images_b64
        })
        
        print(f"[DEBUG] Worker joined session {session_id}. worker_mode={game_session.worker_mode}, helper_mode={game_session.helper_mode}, agent_controller={game_session.agent_controller is not None}")

    @socketio.on('join_as_helper')
    def handle_join_helper(data):
        """Helper joins the game session."""
        SHARED_VIEW_ENABLED = app.config.get('SHARED_VIEW_ENABLED', True)
        RUN_STUDY_MODE = app.config.get('RUN_STUDY_MODE', False)

        worker_mode = data.get('worker_mode', 'human')
        helper_mode = data.get('helper_mode', 'human')
        shared_view = data.get('shared_view', SHARED_VIEW_ENABLED)
        
        session_id = get_session_id_from_data(data)
        print(f"[DEBUG] Helper joining with session_id={session_id}, worker_mode={worker_mode}, helper_mode={helper_mode}, shared_view={shared_view}")
        print(f"[ISOLATION-CRITICAL] HELPER JOIN: session_id={session_id}, socket_id={request.sid}, flask_game_session_id from client={data.get('flask_game_session_id', 'MISSING')}")
        
        game_session = get_or_create_game_session(session_id, worker_mode, helper_mode, shared_view, socket_id=request.sid)
        game_session.helper_sid = request.sid
        
        try:
            user_id = session.get('user_id', session_id)
            prolific_pid = session.get('prolific_pid', '')
            study_id = session.get('study_id', '')
            custom_session_id = session.get('custom_session_id', '')
            user_function = session.get('user_function', 'helper')
        except RuntimeError:
            user_id = data.get('flask_user_id', session_id)
            prolific_pid = data.get('prolific_pid', '')
            study_id = data.get('study_id', '')
            custom_session_id = data.get('flask_custom_session_id', '')
            user_function = 'helper'
            print(f"[DEBUG] Flask session not available, using client-provided data")
        
        game_session.user_id = user_id
        game_session.prolific_pid = prolific_pid
        game_session.study_id = study_id
        game_session.user_function = user_function
        print(f"[USER-INFO] Helper session user_id={user_id}, prolific_pid={prolific_pid}, study_id={study_id}, function={user_function}")
        
        if game_session.session_logger:
            game_session.session_logger.start_session(
                session_id=session_id,
                user_id=game_session.user_id or game_session.prolific_pid or session_id,
                role='helper',
                config={
                    'worker_mode': worker_mode,
                    'helper_mode': 'human',
                    'shared_view': shared_view,
                    'study_mode': RUN_STUDY_MODE,
                    'study_id': game_session.study_id,
                    'custom_session_id': custom_session_id,
                    'prolific_pid': game_session.prolific_pid
                }
            )
            
            game_session.session_logger.log_socket_event(
                session_id=session_id,
                event_name='join_as_helper',
                data={
                    'worker_mode': worker_mode,
                    'shared_view': shared_view,
                    'socket_id': request.sid
                }
            )
        
        print(f"[ISOLATION-CRITICAL] HELPER ROOM JOIN: About to join room={session_id}")
        print(f"[ISOLATION-CRITICAL] This socket ({request.sid}) should ONLY receive broadcasts to room={session_id}")
        print(f"[ISOLATION-CRITICAL] Helper GameSession ID={id(game_session)}, worker_sid={game_session.worker_sid}, helper_sid={game_session.helper_sid}")
        join_room(session_id)
        print(f"[ISOLATION-CRITICAL] HELPER ROOM JOINED: socket {request.sid} is now in room {session_id}")
        
        emit('joined', {
            'role': 'helper',
            'session_id': session_id,
            'worker_mode': game_session.worker_mode,
            'helper_mode': game_session.helper_mode,
            'shared_view': game_session.shared_view,
            'piece_images': game_session.piece_images_b64
        })
        
        print(f"[DEBUG] Helper joined session {session_id}")

    def _broadcast_advance_state(game_session, session_id):
        """Broadcast whether advancing to the next puzzle is currently allowed.

        Sent to the whole room (worker + helper) as booleans only, so it works in
        non-shared view too without revealing the worker's board layout.
        """
        socketio.emit('advance_state', {
            'can_advance': game_session.can_advance(),
            'require_complete': game_session.require_complete
        }, room=session_id)

    def _schedule_require_complete_timeout(game_session, session_id):
        """Auto-unlock the require_complete gate after its timeout so a participant
        can never get permanently stuck on a gated puzzle (e.g. if the AI worker
        can't be guided to place every piece).
        """
        if not game_session.require_complete:
            return
        captured_start = game_session.start_time
        timeout = game_session.require_complete_timeout

        def _timer():
            socketio.sleep(timeout)
            # Only fire if this exact gated trial is still active and still
            # incomplete (start_time changes when a new puzzle begins, so a stale
            # timer from a previous puzzle is ignored).
            if (game_session.trial_active
                    and game_session.start_time == captured_start
                    and game_session.require_complete
                    and not game_session.all_targets_placed()):
                print(f"[DEBUG] require_complete timeout ({timeout}s) reached for session {session_id}; unlocking Next")
                _broadcast_advance_state(game_session, session_id)
                socketio.emit('chat_message', {
                    'sender': 'system',
                    'message': '⏱️ Time limit reached — you can now continue to the next puzzle.',
                    'is_llm': False
                }, room=session_id)

        socketio.start_background_task(_timer)

    def _broadcast_work_area(game_session, session_id):
        """Helper to broadcast work area respecting shared_view setting."""
        if game_session.shared_view:
            socketio.emit('work_area_updated', {
                'work_area': game_session.work_area,
                'waiting_for_helper': game_session.waiting_for_helper,
                'shared_view': True
            }, room=session_id)
        else:
            if game_session.worker_sid:
                socketio.emit('work_area_updated', {
                    'work_area': game_session.work_area,
                    'waiting_for_helper': game_session.waiting_for_helper,
                    'shared_view': False
                }, to=game_session.worker_sid)
        # Always refresh the advance-gate state for both roles (boolean only)
        _broadcast_advance_state(game_session, session_id)

    def _send_llm_helper_guidance(game_session, session_id, trigger_message):
        """Background task: get LLM helper response and broadcast it."""
        try:
            response = asyncio.run(game_session.get_llm_helper_response(trigger_message))
            
            if response:
                game_session.add_message('helper', response)
                socketio.emit('chat_message', {
                    'sender': 'helper',
                    'message': response,
                    'is_llm': True
                }, room=session_id)
                socketio.sleep(0.1)
                socketio.emit('llm_done_thinking', {'role': 'helper'}, room=session_id)
            else:
                socketio.emit('llm_done_thinking', {'role': 'helper'}, room=session_id)
        except Exception as e:
            print(f"[ERROR] Error getting LLM guidance: {e}")
            import traceback
            traceback.print_exc()
            socketio.emit('llm_done_thinking', {'role': 'helper'}, room=session_id)

    def llm_worker_action_loop(session_id, game_session, expected_loop_id=None):
        """Background task for LLM worker to take actions autonomously."""
        if not game_session:
            print(f"[ERROR] No game session provided to llm_worker_action_loop")
            return
        
        my_loop_id = expected_loop_id if expected_loop_id is not None else game_session.worker_loop_id
        print(f"[DEBUG] Starting LLM worker action loop with loop_id={my_loop_id} (expected={expected_loop_id}, current={game_session.worker_loop_id})")
        print(f"[ISOLATION-DEBUG] llm_worker_action_loop: session_id={session_id}, GameSession.session_id={game_session.session_id}, GameSession object id={id(game_session)}")
        print(f"[DEBUG] Loop {my_loop_id} state check: trial_active={game_session.trial_active}, worker_mode={game_session.worker_mode}, worker_loop_id={game_session.worker_loop_id}")
        
        game_session.worker_loop_running = True
        
        try:
            while game_session and game_session.trial_active and game_session.worker_mode == 'llm' and game_session.worker_loop_id == my_loop_id:
                if game_session.waiting_for_helper:
                    socketio.sleep(1)
                    continue
                
                print(f"[DEBUG] Getting LLM worker action (loop_id={my_loop_id})...")
                
                socketio.emit('llm_thinking', {'role': 'worker'}, room=session_id)
                print(f"[DEBUG] llm_thinking emitted for worker to room {session_id}")
                print(f"[DEBUG] Loop {my_loop_id}: About to call get_llm_worker_action()...")
                
                action_result = asyncio.run(game_session.get_llm_worker_action())
                
                print(f"[DEBUG] Loop {my_loop_id}: get_llm_worker_action() returned, result={action_result is not None}")
                
                if game_session.worker_loop_id != my_loop_id:
                    print(f"[DEBUG] Loop {my_loop_id} superseded during LLM call, exiting without processing action")
                    break
                
                if not action_result:
                    print(f"[DEBUG] No action from LLM worker")
                    socketio.emit('llm_done_thinking', {'role': 'worker'}, room=session_id)
                    break
                
                action_executed = False
                message_sent = False
                
                if action_result.get('message'):
                    message = action_result['message']
                    print(f"[DEBUG] LLM worker sending message: {message[:50]}...")
                    game_session.add_message('worker', message)
                    socketio.emit('chat_message', {
                        'sender': 'worker',
                        'message': message,
                        'is_llm': True
                    }, room=session_id)
                    print(f"[DEBUG] chat_message emitted to room {session_id}")
                    message_sent = True
                    
                    if game_session.helper_mode == 'llm':
                        socketio.sleep(1)
                        socketio.emit('llm_thinking', {'role': 'helper'}, room=session_id)
                        
                        helper_response = asyncio.run(game_session.get_llm_helper_response(message))
                        
                        if game_session.worker_loop_id != my_loop_id:
                            print(f"[DEBUG] Loop {my_loop_id} superseded during helper response, exiting without processing")
                            break
                        
                        if helper_response:
                            game_session.add_message('helper', helper_response)
                            socketio.emit('chat_message', {
                                'sender': 'helper',
                                'message': helper_response,
                                'is_llm': True
                            }, room=session_id)
                            socketio.sleep(0.1)
                            socketio.emit('llm_done_thinking', {'role': 'helper'}, room=session_id)
                            game_session.waiting_for_helper = False
                        else:
                            socketio.emit('llm_done_thinking', {'role': 'helper'}, room=session_id)
                        
                        socketio.sleep(0.1)
                        socketio.emit('llm_done_thinking', {'role': 'worker'}, room=session_id)
                        print(f"[DEBUG] Helper responded, waiting for next iteration")
                        socketio.sleep(1)
                        continue
                
                actions = action_result.get('actions', [])
                for action in actions:
                    if action.get('action') == 'place':
                        piece_idx = action.get('piece')
                        x, y = action.get('position', (0, 0))
                        success, msg = game_session.place_piece(piece_idx, x, y)
                        print(f"[DEBUG] LLM worker place action: piece={piece_idx}, pos=({x},{y}), success={success}")
                        
                        if success:
                            action_executed = True
                            print(f"[ISOLATION-DEBUG] LLM worker place: Broadcasting to session_id={session_id}, GameSession.session_id={game_session.session_id}, shared_view={game_session.shared_view}")
                            print(f"[ISOLATION-DEBUG] LLM worker place: worker_sid={game_session.worker_sid}, helper_sid={game_session.helper_sid}, worker_mode={game_session.worker_mode}")
                            _broadcast_work_area(game_session, session_id)
                    
                    elif action.get('action') == 'move':
                        from_x, from_y = action.get('from', (0, 0))
                        to_x, to_y = action.get('to', (0, 0))
                        success, msg = game_session.move_piece(from_x, from_y, to_x, to_y)
                        print(f"[DEBUG] LLM worker move action: from=({from_x},{from_y}), to=({to_x},{to_y}), success={success}")
                        
                        if success:
                            action_executed = True
                            _broadcast_work_area(game_session, session_id)
                    
                    elif action.get('action') == 'remove':
                        x, y = action.get('position', (0, 0))
                        success, msg = game_session.remove_piece(x, y)
                        print(f"[DEBUG] LLM worker remove action: pos=({x},{y}), success={success}")
                        
                        if success:
                            action_executed = True
                            _broadcast_work_area(game_session, session_id)
                
                socketio.sleep(0.1)

                # Only emit if this loop is still the active one
                if game_session.worker_loop_id != my_loop_id:
                    print(f"[DEBUG] Loop {my_loop_id} superseded during action processing, exiting")
                    break

                print(f"[DEBUG] About to emit llm_done_thinking for worker (action_executed={action_executed}, message_sent={message_sent})")
                socketio.emit('llm_done_thinking', {'role': 'worker'}, room=session_id)
                print(f"[DEBUG] llm_done_thinking emitted to room {session_id}")

                if action_executed or message_sent:
                    if not (game_session.helper_mode == 'llm' and message_sent):
                        if game_session.trial_active and game_session.worker_loop_id == my_loop_id:
                            game_session.waiting_for_helper = True
                            socketio.emit('chat_message', {
                                'sender': 'system',
                                'message': '⏳ AI Worker waiting for helper response...',
                                'is_llm': False
                            }, room=session_id)
                        else:
                            print(f"[DEBUG] Trial completed or loop superseded, not setting waiting_for_helper")
                
                socketio.sleep(1)
            
            print(f"[DEBUG] LLM worker action loop ended (loop_id={my_loop_id})")
            print(f"[DEBUG] Loop {my_loop_id} exit state: trial_active={game_session.trial_active}, worker_mode={game_session.worker_mode}, worker_loop_id={game_session.worker_loop_id}")
            
        except Exception as e:
            print(f"[ERROR] Error in LLM worker action loop (loop_id={my_loop_id}): {e}")
            import traceback
            traceback.print_exc()
            # Only clear indicator if this loop is still the active one
            if game_session.worker_loop_id == my_loop_id:
                socketio.emit('llm_done_thinking', {'role': 'worker'}, room=session_id)
                print(f"[DEBUG] Thinking indicator cleared due to exception (loop_id={my_loop_id})")
            else:
                print(f"[DEBUG] Loop {my_loop_id} exception but superseded, not clearing indicator")
        finally:
            game_session.worker_loop_running = False
            print(f"[DEBUG] Loop {my_loop_id}: Set worker_loop_running = False")
            
            if game_session.worker_loop_id == my_loop_id:
                socketio.emit('llm_done_thinking', {'role': 'worker'}, room=session_id)
                print(f"[DEBUG] Worker loop (loop_id={my_loop_id}) exited normally, thinking indicator cleared")
            else:
                print(f"[DEBUG] Worker loop (loop_id={my_loop_id}) superseded by loop {game_session.worker_loop_id}, NOT clearing indicator (new loop owns it)")

    @socketio.on('start_trial')
    def handle_start_trial(data):
        """Start a new trial - INITIAL puzzle."""
        try:
            session_id = get_session_id_from_data(data)
            print(f"[DEBUG] handle_start_trial - session_id: {session_id}")
            print(f"[DEBUG] handle_start_trial - Available user_sessions keys: {list(user_sessions.keys())}")
            
            game_session = user_sessions.get(session_id)
            if not game_session:
                print(f"[DEBUG] handle_start_trial - No game session for {session_id}, trying request.sid: {request.sid}")
                game_session = user_sessions.get(request.sid)
                if not game_session:
                    print(f"[DEBUG] handle_start_trial - No game session found. Client needs to rejoin.")
                    emit('error', {'message': 'Session expired. Please refresh the page to rejoin.'})
                    return
                session_id = request.sid
        except Exception as e:
            print(f"[DEBUG] handle_start_trial - Exception in session lookup: {e}")
            import traceback
            traceback.print_exc()
            emit('error', {'message': f'Error starting trial: {str(e)}'})
            return
        
        if game_session.session_logger:
            game_session.session_logger.log_socket_event(
                session_id=session_id,
                event_name='start_trial',
                data=data
            )
        
        result = game_session.start_trial()
        
        if result[0] is None:
            emit('error', {'message': result[1]})
            return
        
        num_pieces, puzzle = result
        trial_info = game_session.get_trial_info()
        
        if game_session.helper_sid:
            socketio.emit('target_updated', {
                'target_area': game_session.target_area,
                'num_pieces': num_pieces,
                'puzzle_info': puzzle,
                'trial_info': trial_info,
                'shared_view': game_session.shared_view
            }, room=game_session.helper_sid)
        
        socketio.emit('trial_started', {
            'num_pieces': num_pieces,
            'puzzle_info': puzzle,
            'trial_info': trial_info,
            'shared_view': game_session.shared_view,
            'require_complete': game_session.require_complete,
            'message': f"Puzzle {puzzle['puzzle_number']}/{trial_info['total']} started ({puzzle['group']})!"
        }, room=session_id)
        _broadcast_advance_state(game_session, session_id)
        _schedule_require_complete_timeout(game_session, session_id)
        
        if game_session.worker_mode == 'llm' and game_session.agent_controller:
            expected_loop_id = game_session.worker_loop_id
            print(f"[DEBUG] LLM worker mode active, starting action loop (loop_id will be {expected_loop_id})...")
            
            socketio.emit('llm_thinking', {'role': 'worker'}, room=session_id)
            socketio.start_background_task(llm_worker_action_loop, session_id, game_session, expected_loop_id)
        
        elif game_session.helper_mode == 'llm' and game_session.agent_controller:
            print(f"[DEBUG] LLM helper mode active, sending initial guidance...")
            socketio.emit('llm_thinking', {'role': 'helper'}, room=session_id)
            socketio.start_background_task(_send_llm_helper_guidance, game_session, session_id, "Trial started")
        else:
            print(f"[DEBUG] LLM modes not active. worker_mode={game_session.worker_mode}, helper_mode={game_session.helper_mode}")

    @socketio.on('next_trial')
    def handle_next_trial(data):
        """Move to the next trial."""
        print(f"[DEBUG] ============ handle_next_trial CALLED ============")
        try:
            session_id = get_session_id_from_data(data)
            print(f"[DEBUG] handle_next_trial - session_id: {session_id}")
            print(f"[DEBUG] handle_next_trial - Available user_sessions keys: {list(user_sessions.keys())}")
            
            game_session = user_sessions.get(session_id)
            if not game_session:
                print(f"[DEBUG] handle_next_trial - No game session for {session_id}, trying request.sid: {request.sid}")
                game_session = user_sessions.get(request.sid)
                if not game_session:
                    print(f"[DEBUG] handle_next_trial - No game session found. Client needs to rejoin.")
                    emit('error', {'message': 'Session expired. Please refresh the page to rejoin.'})
                    return
                session_id = request.sid
        except Exception as e:
            print(f"[DEBUG] handle_next_trial - Exception in session lookup: {e}")
            import traceback
            traceback.print_exc()
            emit('error', {'message': f'Error moving to next trial: {str(e)}'})
            return
        
        # Gate: under require_complete, only advance once all target pieces are
        # correctly placed. Works for shared and non-shared view (server-side).
        if game_session.trial_active and not game_session.can_advance():
            print(f"[DEBUG] handle_next_trial - Blocked: require_complete active and board incomplete")
            emit('advance_blocked', {
                'message': 'All target pieces must be correctly placed on the board before continuing.'
            })
            _broadcast_advance_state(game_session, session_id)
            return
        
        if game_session.transitioning_to_next_trial:
            print(f"[DEBUG] handle_next_trial - Already transitioning, ignoring duplicate request")
            emit('error', {'message': 'Already loading next puzzle, please wait...'})
            return
        
        game_session.transitioning_to_next_trial = True
        print(f"[DEBUG] handle_next_trial - Set transitioning flag to True")
        
        if game_session.session_logger:
            game_session.session_logger.log_socket_event(
                session_id=session_id,
                event_name='next_trial',
                data=data
            )
        
        if game_session.trial_active:
            elapsed = time.time() - game_session.start_time
            board_complete = game_session.all_targets_placed()
            if game_session.session_logger:
                game_session.session_logger.log_action(
                    session_id=session_id,
                    action_type='game_action',
                    event_name='trial_advanced',
                    details={
                        'require_complete': game_session.require_complete,
                        'board_complete': board_complete,
                        'advanced_via_timeout': game_session.require_complete and not board_complete,
                        'trial_elapsed': elapsed
                    },
                    metadata=game_session._get_current_metadata()
                )
            game_session.trial_active = False
            if game_session.agent_controller:
                game_session.agent_controller.end_trial(False, elapsed)
        
        result = game_session.next_trial()
        
        if result[0] is None:
            game_session.transitioning_to_next_trial = False
            questionnaire_url = os.environ.get('FORMS_QUESTIONNAIRE_URL', '')
            if questionnaire_url:
                try:
                    prolific_pid = session.get('prolific_pid', '')
                    custom_session_id = session.get('custom_session_id', '')
                    questionnaire_url = questionnaire_url.replace('PROLIFIC_USER_ID', prolific_pid or 'N/A')
                    questionnaire_url = questionnaire_url.replace('PROLIFIC_SESSION_ID', custom_session_id or 'N/A')
                except RuntimeError:
                    pass
            
            socketio.emit('all_trials_complete', {
                'message': 'All puzzles completed! Thank you for participating.',
                'questionnaire_url': questionnaire_url
            }, room=session_id)
            return
        
        num_pieces, puzzle = result
        trial_info = game_session.get_trial_info()
        
        if game_session.helper_sid:
            socketio.emit('target_updated', {
                'target_area': game_session.target_area,
                'num_pieces': num_pieces,
                'puzzle_info': puzzle,
                'trial_info': trial_info,
                'shared_view': game_session.shared_view
            }, room=game_session.helper_sid)
        
        socketio.emit('work_area_updated', {
            'work_area': game_session.work_area,
            'waiting_for_helper': game_session.waiting_for_helper
        }, room=session_id)
        
        socketio.emit('trial_started', {
            'num_pieces': num_pieces,
            'puzzle_info': puzzle,
            'trial_info': trial_info,
            'shared_view': game_session.shared_view,
            'require_complete': game_session.require_complete,
            'message': f"Puzzle {puzzle['puzzle_number']}/{trial_info['total']} started ({puzzle['group']})!"
        }, room=session_id)
        _broadcast_advance_state(game_session, session_id)
        _schedule_require_complete_timeout(game_session, session_id)
        
        if game_session.worker_mode == 'llm' and game_session.agent_controller:
            expected_loop_id = game_session.worker_loop_id
            print(f"[DEBUG] handle_next_trial: About to start loop for loop_id={expected_loop_id}, trial_active={game_session.trial_active}")
            
            socketio.emit('llm_thinking', {'role': 'worker'}, room=session_id)
            socketio.start_background_task(llm_worker_action_loop, session_id, game_session, expected_loop_id)
            print(f"[DEBUG] handle_next_trial: Background task scheduled for loop_id={expected_loop_id}")
        
        game_session.transitioning_to_next_trial = False
        print(f"[DEBUG] handle_next_trial: Cleared transitioning flag")
        
        if game_session.helper_mode == 'llm' and game_session.agent_controller:
            print(f"[DEBUG] LLM helper mode active, sending initial guidance...")
            socketio.emit('llm_thinking', {'role': 'helper'}, room=session_id)
            socketio.start_background_task(_send_llm_helper_guidance, game_session, session_id, "New trial started")

    @socketio.on('place_piece')
    def handle_place_piece(data):
        """Worker places a piece."""
        session_id = get_session_id_from_data(data)
        if not session_id or session_id not in user_sessions:
            emit('error', {'message': 'No active game session'})
            return
        
        game_session = user_sessions[session_id]
        
        if game_session.session_logger:
            game_session.session_logger.log_socket_event(
                session_id=session_id,
                event_name='place_piece',
                data=data
            )
        
        piece_idx = data.get('piece_idx')
        x = data.get('x')
        y = data.get('y')
        
        success, message = game_session.place_piece(piece_idx, x, y)
        
        if success:
            print(f"[BROADCAST-DEBUG] place_piece: session_id={session_id}, GameSession id={id(game_session)}")
            print(f"[BROADCAST-DEBUG] place_piece: Broadcasting to room={session_id}, shared_view={game_session.shared_view}")
            _broadcast_work_area(game_session, session_id)
            
            if game_session.worker_sid:
                socketio.emit('update_staging', {
                    'staging_pieces': game_session.staging_pieces
                }, to=game_session.worker_sid)
            
            emit('action_result', {'success': True, 'message': message})
        else:
            emit('action_result', {'success': False, 'message': message})

    @socketio.on('move_piece')
    def handle_move_piece(data):
        """Worker moves a piece."""
        session_id = get_session_id_from_data(data)
        if not session_id or session_id not in user_sessions:
            emit('error', {'message': 'No active game session'})
            return
        
        game_session = user_sessions[session_id]
        
        if game_session.session_logger:
            game_session.session_logger.log_socket_event(
                session_id=session_id,
                event_name='move_piece',
                data=data
            )
        
        from_x = data.get('from_x')
        from_y = data.get('from_y')
        to_x = data.get('to_x')
        to_y = data.get('to_y')
        
        success, message = game_session.move_piece(from_x, from_y, to_x, to_y)
        
        if success:
            print(f"[BROADCAST-DEBUG] move_piece: shared_view={game_session.shared_view}, worker_sid={game_session.worker_sid}, helper_sid={game_session.helper_sid}")
            _broadcast_work_area(game_session, session_id)
            
            if game_session.worker_sid:
                socketio.emit('update_staging', {
                    'staging_pieces': game_session.staging_pieces
                }, to=game_session.worker_sid)
            
            emit('action_result', {'success': True, 'message': message})
        else:
            emit('action_result', {'success': False, 'message': message})

    @socketio.on('remove_piece')
    def handle_remove_piece(data):
        """Worker removes a piece."""
        session_id = get_session_id_from_data(data)
        if not session_id or session_id not in user_sessions:
            emit('error', {'message': 'No active game session'})
            return
        
        game_session = user_sessions[session_id]
        
        if game_session.session_logger:
            game_session.session_logger.log_socket_event(
                session_id=session_id,
                event_name='remove_piece',
                data=data
            )
        
        x = data.get('x')
        y = data.get('y')
        
        success, message = game_session.remove_piece(x, y)
        
        if success:
            print(f"[BROADCAST-DEBUG] remove_piece: shared_view={game_session.shared_view}, worker_sid={game_session.worker_sid}, helper_sid={game_session.helper_sid}")
            _broadcast_work_area(game_session, session_id)
            
            if game_session.worker_sid:
                socketio.emit('update_staging', {
                    'staging_pieces': game_session.staging_pieces
                }, to=game_session.worker_sid)
            
            emit('action_result', {'success': True, 'message': message})
        else:
            emit('action_result', {'success': False, 'message': message})

    @socketio.on('next_turn')
    def handle_next_turn(data):
        """Worker advances to next turn."""
        game_session = get_game_session()
        if not game_session:
            emit('error', {'message': 'No active game session'})
            return
        
        success, message = game_session.next_turn()
        
        if success:
            emit('action_result', {'success': True, 'message': message})
        else:
            emit('action_result', {'success': False, 'message': message})

    @socketio.on('send_message')
    def handle_send_message(data):
        """Send a chat message."""
        try:
            session_id = get_session_id_from_data(data)
            print(f"[DEBUG] handle_send_message - session_id: {session_id}")
            
            game_session = user_sessions.get(session_id)
            if not game_session:
                print(f"[DEBUG] handle_send_message - No game session for {session_id}, trying request.sid: {request.sid}")
                game_session = user_sessions.get(request.sid)
                if not game_session:
                    print(f"[DEBUG] handle_send_message - No game session found")
                    emit('error', {'message': 'No active game session'})
                    return
                session_id = request.sid
        except Exception as e:
            print(f"[DEBUG] handle_send_message - Exception: {e}")
            import traceback
            traceback.print_exc()
            emit('error', {'message': f'Error sending message: {str(e)}'})
            return
        
        if not game_session.trial_active:
            print(f"[DEBUG] Message blocked - trial is not active")
            return
        
        if game_session.session_logger:
            game_session.session_logger.log_socket_event(
                session_id=session_id,
                event_name='send_message',
                data=data
            )
        
        sender = data.get('sender')
        message = data.get('message')
        
        print(f"[CHAT-DEBUG] handle_send_message: session_id={session_id}, GameSession.session_id={game_session.session_id}, sender={sender}")
        print(f"[CHAT-DEBUG] handle_send_message: GameSession object id={id(game_session)}")
        
        game_session.add_message(sender, message)
        
        if sender == 'helper' and game_session.worker_mode == 'llm':
            if game_session.trial_active:
                game_session.waiting_for_helper = False
                print(f"[DEBUG] Helper responded, worker can continue")
            else:
                print(f"[DEBUG] Helper responded but trial is not active, worker will not continue")
        
        socketio.emit('chat_message', {
            'sender': sender,
            'message': message,
            'is_llm': False
        }, room=session_id)
        
        if sender == 'worker' and game_session.helper_mode == 'llm' and game_session.agent_controller:
            print(f"[DEBUG] Worker message received, triggering LLM response...")
            socketio.emit('llm_thinking', {'role': 'helper'}, room=session_id)
            
            def send_llm_response():
                try:
                    print(f"[DEBUG] send_llm_response: session_id={session_id}, GameSession.session_id={game_session.session_id}")
                    print(f"[DEBUG] send_llm_response: GameSession object id={id(game_session)}")
                    print(f"[DEBUG] Calling get_llm_helper_response with message: {message}")
                    response = asyncio.run(game_session.get_llm_helper_response(message))
                    
                    print(f"[DEBUG] LLM response received: {response[:100] if response else 'None'}...")
                    print(f"[DEBUG] Full LLM response length: {len(response) if response else 0}")
                    print(f"[DEBUG] Full LLM response: {repr(response)}")
                    if response:
                        game_session.add_message('helper', response)
                        socketio.emit('chat_message', {
                            'sender': 'helper',
                            'message': response,
                            'is_llm': True
                        }, room=session_id)
                        print(f"[DEBUG] LLM response sent to client. Message length: {len(response)}")
                        socketio.sleep(0.1)
                        socketio.emit('llm_done_thinking', {'role': 'helper'}, room=session_id)
                        print(f"[DEBUG] Thinking indicator cleared")
                    else:
                        print(f"[DEBUG] No response from LLM")
                        socketio.emit('llm_done_thinking', {'role': 'helper'}, room=session_id)
                except Exception as e:
                    print(f"[ERROR] Error getting LLM response: {e}")
                    import traceback
                    traceback.print_exc()
                    socketio.emit('llm_done_thinking', {'role': 'helper'}, room=session_id)
            
            socketio.start_background_task(send_llm_response)
