"""The direct display publication retains source identity and expiry."""
import copy
import unittest
from unittest.mock import patch
from normal_npu.live import publish_live
import test_normal_npu_freshness as fixtures

class DirectDisplayTests(unittest.TestCase):
    setUp=fixtures.NormalNpuFreshnessTests.setUp
    write_result=fixtures.NormalNpuFreshnessTests.write_result

    def rendered(self):
        path=self.path.with_name(self.path.stem+'.display.txt')
        self.assertEqual(path.stat().st_mode & 0o077,0)
        return dict(line.split('=',1) for line in path.read_text().splitlines())

    def send(self,now,sample=True):
        self.result['model_sha256']='a'*64
        with patch('normal_npu.live.time.monotonic',return_value=now):
            publish_live(self.path,self.result,self.sample if sample else None)
        return self.rendered()

    def test_fresh_result_is_available_without_waiting_for_dashboard(self):
        before=copy.deepcopy(self.sample)
        out=self.send(1000.02)
        self.assertEqual(out['panel_nn_valid'],'1')
        self.assertEqual(out['panel_nn_deadline_ms'],'1001000')
        self.assertEqual(out['display_os_boot'],'os-boot')
        self.assertEqual(out['display_collector_context'],self.sample['boot']+'|'+','.join(map(str,self.sample['feature_words'])))
        self.assertEqual(self.sample,before)

    def test_expired_source_is_not_revalidated_by_a_new_publication(self):
        self.result['input_deadline']=1000.1
        out=self.send(1000.2)
        self.assertEqual(out['panel_nn_valid'],'0')

    def test_invalid_input_immediately_replaces_the_valid_direct_view(self):
        self.assertEqual(self.send(1000.02)['panel_nn_valid'],'1')
        self.result.update(valid=False,status='WAITING_INPUT',reason='PROCESS_SENSOR_INVALID',updated_at=1000.03)
        out=self.send(1000.04)
        self.assertEqual(out['panel_nn_valid'],'0')
        self.assertEqual(out['panel_nn_reason'],'PROCESS_SENSOR_INVALID')

    def test_loading_without_an_observation_cannot_publish_values(self):
        self.result.update(valid=False,status='LOADING')
        out=self.send(1000.02,sample=False)
        self.assertEqual(out['panel_nn_valid'],'0')
        self.assertEqual(out['display_collector_context'],'')

if __name__=='__main__':unittest.main()
