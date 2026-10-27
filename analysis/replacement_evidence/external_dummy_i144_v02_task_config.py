"""Five-input SRSD Easy-Dummy task for the isolated symbolic-basis-v02 round."""

from __future__ import annotations

from .round_runner import ParentDefinition, TaskDefinition


DUMMY_I144_V02_TASK_DEFINITIONS = (
    TaskDefinition(
        task_id="srsd-feynman-i14-4-dummy-v02",
        input_names=("x0", "x1", "x2", "x3", "x4"),
        headers=("x0", "x1", "x2", "x3", "x4", "y"),
        target="y",
        parents=(ParentDefinition(
            "srsd-feynman-i14-4-dummy-v02-p01",
            ("m_0_0_0_0_0", "m_1_0_0_0_0", "m_0_1_0_0_0",
             "m_0_0_1_0_0", "m_0_0_0_1_0", "m_0_0_0_0_1"),
        ),),
    ),
)
