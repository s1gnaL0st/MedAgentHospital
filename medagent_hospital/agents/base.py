"""Base abstraction for all agents in the hospital simulacrum."""

from __future__ import annotations

import abc

from medagent_hospital.llm.base import LLMBackend
from medagent_hospital.simulacrum.models import Action, ConsultationContext


class Agent(abc.ABC):
    name: str
    role: str

    def __init__(self, name: str, llm: LLMBackend) -> None:
        self.name = name
        self.llm = llm

    @abc.abstractmethod
    def run(self, context: ConsultationContext) -> Action:
        """Observe the current hospital context and return the next action."""
