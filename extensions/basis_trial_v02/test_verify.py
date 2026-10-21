import copy
import tempfile
import unittest
from pathlib import Path
from .verify import request_packet, common_request, verify_conversion
from .sdk_controller import execution_conversion
from .run import design
from extensions.symbolic_basis_v01.executor import write


class BindingAuditTests(unittest.TestCase):
    def request(self):
        return dict(model='M',messages=[dict(role='system',content='fixed'),
            dict(role='user',content='{"state":1,"repair_policy":"A"}')])

    def test_only_policy_is_excluded(self):
        a=self.request(); b=copy.deepcopy(a)
        b['messages'][-1]['content']='{"state":1,"repair_policy":"B"}'
        self.assertEqual(common_request(a),common_request(b))
        b['messages'][0]['content']='changed'
        self.assertNotEqual(common_request(a),common_request(b))

    def test_extra_context_rejected(self):
        a=self.request();a['messages'].append(dict(role='assistant',content='leaked child'))
        with self.assertRaises(ValueError):request_packet(a)

    def test_duplicate_packet_key_rejected(self):
        a=self.request();a['messages'][-1]['content']='{"x":1,"x":2}'
        with self.assertRaises(ValueError):request_packet(a)

    def fixture(self,folder):
        parent=design()['parents']['A'];business=dict(feature_ids=parent['payload']['feature_ids'])
        converted=execution_conversion(business,parent['spec'])
        session=dict(execution_payload=converted['execution_payload'],conversion_receipt=converted['receipt'],compiled=converted['compiled'])
        write(folder/'execution-payload.json',converted['execution_payload'])
        write(folder/'host-conversion.json',converted['receipt'])
        write(folder/'compiled.json',converted['compiled'])
        return business,parent['spec'],session

    def test_all_conversion_bindings_match(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);business,spec,session=self.fixture(folder)
            self.assertEqual(verify_conversion(folder,session,business,spec),session['execution_payload'])

    def test_model_prose_cannot_replace_host_marker(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);business,spec,session=self.fixture(folder)
            session['execution_payload']['explanation']='model says so'
            with self.assertRaises(ValueError):verify_conversion(folder,session,business,spec)

    def test_different_feature_ids_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);business,spec,session=self.fixture(folder)
            business['feature_ids']=design()['parents']['B']['payload']['feature_ids']
            with self.assertRaises(ValueError):verify_conversion(folder,session,business,spec)

    def test_forged_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);business,spec,session=self.fixture(folder)
            receipt=copy.deepcopy(session['conversion_receipt']);receipt['model_explanation_used']=True
            (folder/'host-conversion.json').unlink();write(folder/'host-conversion.json',receipt)
            with self.assertRaises(ValueError):verify_conversion(folder,session,business,spec)


if __name__=='__main__':unittest.main()
