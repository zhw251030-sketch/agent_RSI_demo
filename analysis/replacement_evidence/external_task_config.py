"""Frozen task definitions for the first external SRSD-Feynman round.

The selected equations are deliberately within the existing degree-three
monomial contract.  This keeps the first external round about evidence-gated
revision rather than silently changing the executable language at the same
time as the dataset.
"""

from __future__ import annotations

from .round_runner import ParentDefinition, TaskDefinition


EXTERNAL_TASK_DEFINITIONS = (
    TaskDefinition(
        task_id="srsd-feynman-i12-1",
        input_names=("x0", "x1"),
        headers=("x0", "x1", "y"),
        target="y",
        parents=(
            ParentDefinition(
                "srsd-feynman-i12-1-p01",
                ("m_0_0", "m_1_0", "m_0_1", "m_2_0"),
            ),
        ),
    ),
    TaskDefinition(
        task_id="srsd-feynman-i14-4",
        input_names=("x0", "x1"),
        headers=("x0", "x1", "y"),
        target="y",
        parents=(
            ParentDefinition(
                "srsd-feynman-i14-4-p01",
                ("m_0_0", "m_1_0", "m_0_1", "m_2_0", "m_2_1"),
            ),
        ),
    ),
    TaskDefinition(
        task_id="srsd-feynman-ii8-31",
        input_names=("x0",),
        headers=("x0", "y"),
        target="y",
        parents=(
            ParentDefinition(
                "srsd-feynman-ii8-31-p01",
                ("m_0", "m_1", "m_3"),
            ),
        ),
    ),
)


EXTERNAL_TASK_IDS = tuple(task.task_id for task in EXTERNAL_TASK_DEFINITIONS)
