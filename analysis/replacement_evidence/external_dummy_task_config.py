"""SRSD-Feynman Easy-Dummy tasks reserved for the next independent round."""

from __future__ import annotations

from .round_runner import ParentDefinition, TaskDefinition


DUMMY_TASK_DEFINITIONS = (
    TaskDefinition(
        task_id="srsd-feynman-i12-1-dummy",
        input_names=("x0", "x1", "x2"),
        headers=("x0", "x1", "x2", "y"),
        target="y",
        parents=(
            ParentDefinition(
                "srsd-feynman-i12-1-dummy-p01",
                ("m_0_0_0", "m_1_0_0", "m_0_1_0", "m_0_0_1"),
            ),
        ),
    ),
    TaskDefinition(
        task_id="srsd-feynman-ii8-31-dummy",
        input_names=("x0", "x1", "x2"),
        headers=("x0", "x1", "x2", "y"),
        target="y",
        parents=(
            ParentDefinition(
                "srsd-feynman-ii8-31-dummy-p01",
                ("m_0_0_0", "m_0_1_0", "m_0_0_1"),
            ),
        ),
    ),
)
