from __future__ import annotations

__version__ = "0.1.0"

from agentlab.adapters.fake import FakeAdapter
from agentlab.adapters.openai_compatible import OpenAICompatibleAdapter
from agentlab.reporting import (
    write_benchmark_html_report,
    write_benchmark_json_report,
    write_run_html_report,
)

__all__ = [
    "FakeAdapter",
    "OpenAICompatibleAdapter",
    "__version__",
    "write_benchmark_html_report",
    "write_benchmark_json_report",
    "write_run_html_report",
]
