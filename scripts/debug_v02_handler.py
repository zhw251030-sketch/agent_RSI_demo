import json
from extensions.symbolic_basis_v02.sdk_adapter import BasisSubmissionHandler, parse_tool_response
from extensions.symbolic_basis_v02.contract import make_spec

ids = ["m_0_0_0_0_0", "m_1_0_0_0_0", "m_0_1_0_0_0", "m_0_0_1_0_0", "m_0_0_0_1_0", "m_0_0_0_0_1"]
spec = make_spec(5, 6)
raw = {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "tool_calls": [{
    "id": "x", "type": "function", "function": {"name": "submit_basis", "arguments": json.dumps({"feature_ids": ids})}
}]}}]}
handler = BasisSubmissionHandler(spec, lambda compiled: {"status": "accepted"})
print(parse_tool_response(raw))
print(handler.prepare_response(raw))
print(handler.accept_action({"feature_ids": ids}))
