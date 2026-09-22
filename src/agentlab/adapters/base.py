from typing import Protocol

from agentlab.models import ModelResponse


class ModelAdapter(Protocol):
    model_name: str

    def complete(self, prompt: str, step: int) -> ModelResponse: ...
