"""LLM agents for the visual-information studies.

They reuse the project's base agent and client but take their view of the world
from a pre-built :class:`~studies.views.Observation`, so nothing the study
withholds can reach the model.
"""
import time
from typing import Any, Dict, Optional

from ai.agents import BaseAgent
from ai.action_parser import ActionParser
from ai.client import get_ai_client

from . import prompts
from .conditions import TrialCondition
from .views import Observation


class StudyAgent(BaseAgent):
    role = 'agent'

    def __init__(self, ai_client):
        super().__init__(ai_client, agent_id=self.role.capitalize())
        self.system_prompt = ''
        self.trial: Optional[TrialCondition] = None

    def get_system_prompt(self) -> str:
        return self.system_prompt

    def start_trial(self, trial: TrialCondition, disclose: bool = True) -> None:
        """Fresh conversation and condition-specific instructions for every trial."""
        self.hard_reset()
        self.trial = trial
        self.system_prompt = self.build_system_prompt(trial, disclose)

    def build_system_prompt(self, trial: TrialCondition, disclose: bool) -> str:
        raise NotImplementedError

    def turn_instruction(self, incoming: Optional[str], first: bool) -> str:
        raise NotImplementedError

    async def perceive_and_act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return await self.take_turn(state['observation'], state.get('incoming'), state.get('first', False),
                                    state.get('instruction'))

    async def take_turn(self, observation: Observation, incoming: Optional[str], first: bool,
                        instruction: Optional[str] = None) -> Dict[str, Any]:
        if incoming:
            self.add_to_history("user", incoming)
        content = observation.to_content(instruction or self.turn_instruction(incoming, first))
        started = time.perf_counter()
        response = await self._call_llm(content, add_to_history=False)
        latency = time.perf_counter() - started

        error = response.startswith("ERROR:")
        if error and self.conversation_history:
            self.conversation_history.pop()  # do not keep a failed call as the agent's own words
        helper = self.role == 'helper'
        parsed = ActionParser.parse_llm_response(response, study_actions=True, look_anywhere=helper,
                                                 allow_done=helper)
        if not parsed['message'] and not parsed['actions'] and not error:
            parsed['message'] = self.fallback_message(response)
        parsed.update(error=error, latency_s=latency, system_prompt=self.system_prompt)
        return parsed

    def fallback_message(self, response: str) -> Optional[str]:
        return None


class StudyWorkerAgent(StudyAgent):
    role = 'worker'

    def build_system_prompt(self, trial, disclose):
        return prompts.build_worker_prompt(trial, disclose)

    def turn_instruction(self, incoming, first):
        if first or not incoming:
            return prompts.WORKER_FIRST_TURN if first else "The Helper has not sent a new message."
        return prompts.worker_turn_instruction(incoming)


class StudyHelperAgent(StudyAgent):
    role = 'helper'

    def build_system_prompt(self, trial, disclose):
        return prompts.build_helper_prompt(trial, disclose)

    def turn_instruction(self, incoming, first):
        if first:
            return prompts.HELPER_FIRST_TURN
        if not incoming:
            return "The Worker did not send a message. Respond to them with a MESSAGE."
        return prompts.helper_turn_instruction(incoming)

    def fallback_message(self, response):
        return response.strip() or None


def create_agents(ai_client=None):
    """Build a Worker and Helper sharing one client (the configured model backend)."""
    client = ai_client or get_ai_client()
    return StudyWorkerAgent(client), StudyHelperAgent(client)
