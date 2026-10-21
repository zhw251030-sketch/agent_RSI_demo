import copy
import unittest
from .verify import request_packet, common_request, read

class RequestAuditTests(unittest.TestCase):
    def request(self):
        return dict(model='M',max_output_tokens=5,tools=[],tool_choice=None,messages=[
            {'role':'system','content':'fixed'}, {'role':'user','content':'{"state":1,"repair_policy":"A"}'}])
    def test_only_policy_excluded(self):
        a=self.request();b=copy.deepcopy(a)
        b['messages'][1]['content']='{"state":1,"repair_policy":"B"}'
        self.assertEqual(common_request(a),common_request(b))
        b['messages'][0]['content']='changed'
        self.assertNotEqual(common_request(a),common_request(b))
    def test_extra_context_rejected(self):
        a=self.request();a['messages'].append({'role':'assistant','content':'leaked previous child'})
        with self.assertRaises(ValueError):request_packet(a)
    def test_duplicate_packet_key_rejected(self):
        a=self.request();a['messages'][1]['content']='{"x":1,"x":2}'
        with self.assertRaises(ValueError):request_packet(a)
    def test_actual_packet_extracted(self):
        self.assertEqual(request_packet(self.request()),{'state':1,'repair_policy':'A'})

    def test_host_packet_is_not_limited_by_model_response_cap(self):
        import json
        a=self.request();large={'history':'x'*81000}
        a['messages'][-1]['content']=json.dumps(large)
        self.assertEqual(request_packet(a),large)

if __name__=='__main__':unittest.main()
