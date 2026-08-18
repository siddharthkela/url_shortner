"""Named node builders, one per SDLC stage, over the generic factory in
factory.py. Each is `build_agent_node` with `stage=` pre-filled — this keeps
scenario code (e.g. `stages.build_design_node(...)`) self-documenting
without duplicating the underlying mechanics seven times.
"""
from functools import partial

from orchestrator.stages.factory import build_agent_node

build_requirements_node = partial(build_agent_node, stage="requirements")
build_codebase_analysis_node = partial(build_agent_node, stage="codebase_analysis")
build_design_node = partial(build_agent_node, stage="design")
build_implementation_node = partial(build_agent_node, stage="implementation")
build_test_node = partial(build_agent_node, stage="test")
build_docs_node = partial(build_agent_node, stage="docs")
build_release_node = partial(build_agent_node, stage="release")

__all__ = [
    "build_agent_node",
    "build_requirements_node",
    "build_codebase_analysis_node",
    "build_design_node",
    "build_implementation_node",
    "build_test_node",
    "build_docs_node",
    "build_release_node",
]
