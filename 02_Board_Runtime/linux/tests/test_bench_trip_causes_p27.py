"""Raw PL trip reasons stay observable after stop; no threshold changes."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from commissioning.bench import BenchController,trip_evidence
from tests.test_bench_guard_p18 import IO,status,prepared,service

class TripCauseTests(unittest.TestCase):
 def test_decodes_all_eight_hardware_latched_causes_and_keeps_raw_word(self):
  word=(255<<24)|2;d=trip_evidence(word)
  self.assertEqual(d['flags_raw'],word);self.assertEqual(d['cause_mask'],255);self.assertEqual(len(d['causes']),8)
  self.assertTrue(d['cause_known']);self.assertIn('CURRENT_LIMIT',d['causes']);self.assertIn('HARDWARE_LEASE_EXPIRED',d['causes'])
 def test_legacy_zero_high_byte_is_explicitly_unknown(self):
  d=trip_evidence(2);self.assertTrue(d['tripped']);self.assertFalse(d['cause_known'])
  self.assertEqual(d['source'],'LEGACY_OR_UNKNOWN_TRIP_CAUSE')
 def test_reserved_bits_or_cause_without_trip_are_rejected(self):
  for word in (8,0x80000001,True,-1):
   with self.subTest(word=word),self.assertRaises(ValueError):trip_evidence(word)
 def test_termination_retains_observed_cause_even_when_stop_clears_old_firmware_flags(self):
  s=service();io=IO();b=BenchController(s,admission_check=lambda boot:{'fixture':True});st=status();now=1000.
  with patch('commissioning.bench.time.monotonic',return_value=now):b.request_start(prepared(),s.boot)
  b.poll(SimpleNamespace(io=io),st,now);self.assertTrue(b.snapshot()['controls_enabled'])
  io.words[0x908]=(1<<28)|2
  b.poll(SimpleNamespace(io=io),st,now+.01);result=b.snapshot()
  self.assertEqual(result['reason'],'HARDWARE_TRIP');self.assertTrue(result['output_stop_confirmed'])
  self.assertEqual(result['hardware_trip']['causes'],['CURRENT_LIMIT']);self.assertEqual(result['hardware_trip']['flags_raw'],(1<<28)|2)
  self.assertEqual(s.journal[-1][2]['hardware_trip'],result['hardware_trip'])
 def test_trip_at_plan_boundary_is_not_reported_as_successful_completion(self):
  owner=service();io=IO();bench=BenchController(owner,admission_check=lambda boot:{'fixture':True});st=status();now=1000.
  with patch('commissioning.bench.time.monotonic',return_value=now):bench.request_start(prepared(),owner.boot)
  bench.poll(SimpleNamespace(io=io),st,now);bench.active['heartbeat']=now+2.1;io.words[0x908]=(1<<28)|2
  bench.poll(SimpleNamespace(io=io),st,now+2.1)
  result=bench.snapshot();self.assertEqual(result['state'],'STOPPED');self.assertEqual(result['reason'],'HARDWARE_TRIP')
  self.assertTrue(result['output_stop_confirmed']);self.assertEqual(result['hardware_trip']['causes'],['CURRENT_LIMIT'])
 def test_trip_between_final_poll_and_stop_readback_revokes_completion(self):
  for flags,reason in [((1<<28)|2,'HARDWARE_TRIP'),(2,'HARDWARE_TRIP_OR_TIMEOUT')]:
   class RacingIO(IO):
    inject=False
    def write(self,address,value):
     super().write(address,value)
     if address==0x930 and self.inject:self.words[0x908]=flags
   owner=service();io=RacingIO();bench=BenchController(owner,admission_check=lambda boot:{'fixture':True});st=status();now=1000.
   with patch('commissioning.bench.time.monotonic',return_value=now):bench.request_start(prepared(),owner.boot)
   bench.poll(SimpleNamespace(io=io),st,now);bench.active['heartbeat']=now+2.1;io.inject=True
   bench.poll(SimpleNamespace(io=io),st,now+2.1);result=bench.snapshot()
   with self.subTest(flags=flags):
    self.assertEqual(result['state'],'STOPPED');self.assertEqual(result['reason'],reason)
    self.assertTrue(result['output_stop_confirmed']);self.assertEqual(result['hardware_trip']['flags_raw'],flags)
    self.assertEqual(owner.journal[-1][2]['state'],'STOPPED')
if __name__=='__main__':unittest.main(verbosity=2)
