from agentlab.models import ModelResponse


class FakeAdapter:
    model_name = "fake-deterministic"

    def __init__(self, script: list[ModelResponse]) -> None:
        self._script = list(script)
        self.calls = 0

    def complete(self, prompt: str, step: int) -> ModelResponse:
        if self.calls >= len(self._script):
            raise RuntimeError("FakeAdapter script exhausted")
        response = self._script[self.calls]
        self.calls += 1
        return response
