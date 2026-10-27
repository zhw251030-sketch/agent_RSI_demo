"""Additional SRSD-Feynman Easy tasks for an independent external round."""

from __future__ import annotations

from .round_runner import ParentDefinition, TaskDefinition


REPLICATION_TASK_DEFINITIONS = (
    TaskDefinition(
        task_id="srsd-feynman-i12-5",
        input_names=("x0", "x1"),
        headers=("x0", "x1", "y"),
        target="y",
        parents=(ParentDefinition(
            "srsd-feynman-i12-5-p01",
            ("m_0_0", "m_1_0", "m_0_1", "m_2_0"),
        ),),
    ),
    TaskDefinition(
        task_id="srsd-feynman-i14-3",
        input_names=("x0", "x1"),
        headers=("x0", "x1", "y"),
        target="y",
        parents=(ParentDefinition(
            "srsd-feynman-i14-3-p01",
            ("m_0_0", "m_1_0", "m_0_1", "m_2_0"),
        ),),
    ),
)
