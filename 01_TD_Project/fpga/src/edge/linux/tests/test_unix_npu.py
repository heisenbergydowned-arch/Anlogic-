import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from cabinet.model import Model
from test_chain import real_frame

class UnixNpuTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','Board transport uses a Linux Unix socket')
    def test_linux_socket_contract(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'npu.sock';root=Path(__file__).resolve().parents[1]
            p=subprocess.Popen([sys.executable,str(root/'npu_server.py'),'--mock','--socket',str(path),
                                '--model-id','u1','--feature-config-id','1','--calibration-id','1'],
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
            try:
                deadline=time.monotonic()+10
                while not path.exists() and time.monotonic()<deadline and p.poll() is None:time.sleep(.02)
                if not path.exists():
                    p.terminate();out,err=p.communicate(timeout=3);self.fail('Unix listener startup: '+out+err)
                result=Model({'backend':'unix','socket':str(path),'model_id':'u1','timeout_ms':1000}).infer(real_frame())
                self.assertEqual(result['backend'],'EXTERNAL_UNIX');self.assertTrue(result['test']);self.assertEqual(result['frame_id'],1)
                self.assertEqual(path.stat().st_mode&0o777,0o600)
            finally:
                if p.poll() is None:p.terminate()
                p.communicate(timeout=4)
            self.assertEqual(p.returncode,0)
            self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
