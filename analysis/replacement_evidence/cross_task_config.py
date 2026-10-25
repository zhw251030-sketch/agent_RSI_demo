"""Frozen cross-task development configuration for the next replacement round.

These tasks are a cross-task development replication of the mechanism.  The
project has used these LLM-SR tasks in earlier work, so this configuration must
not be described as an unseen benchmark or a final generalization test.
"""

from __future__ import annotations

from .round_runner import ParentDefinition, TaskDefinition


CONFIG_VERSION = "replacement-cross-task-v0.1"
SPLIT_REPORT = "docs/environment/2026-10-25-replacement-cross-task-splits.json"

# The parent catalogs are fixed before any actor request.  Every parent keeps
# the constant feature and leaves exactly one feature position available for a
# possible swap_one proposal.
CROSS_TASK_DEFINITIONS = (
    TaskDefinition(
        task_id="oscillator1",
        input_names=("x", "v"),
        headers=("x", "v", "a"),
        target="a",
        parents=(
            ParentDefinition("oscillator1-p01", ("m_0_0", "m_1_0", "m_0_1", "m_1_1")),
            ParentDefinition("oscillator1-p02", ("m_0_0", "m_1_0", "m_0_1", "m_2_0")),
            ParentDefinition("oscillator1-p03", ("m_0_0", "m_1_0", "m_0_1", "m_0_2")),
        ),
    ),
    TaskDefinition(
        task_id="oscillator2",
        input_names=("t", "x", "v"),
        headers=("t", "x", "v", "a"),
        target="a",
        parents=(
            ParentDefinition("oscillator2-p01", ("m_0_0_0", "m_1_0_0", "m_0_1_0", "m_0_0_1")),
            ParentDefinition("oscillator2-p02", ("m_0_0_0", "m_1_0_0", "m_0_1_0", "m_0_0_1", "m_1_1_0")),
            ParentDefinition("oscillator2-p03", ("m_0_0_0", "m_1_0_0", "m_0_1_0", "m_0_0_1", "m_0_1_1")),
        ),
    ),
)


def task_definitions() -> tuple[TaskDefinition, ...]:
    """Return the immutable task catalog used by the cross-task runner."""

    return CROSS_TASK_DEFINITIONS
