"""Host file-mapping contract check; never opens a real UIO/devmem device."""
import ctypes
import errno
import os
from pathlib import Path
import struct
import tempfile
import unittest

class NativeTests(unittest.TestCase):
    def test_aligned_word_access_and_exclusive_owner(self):
        path=os.environ.get('EDGE_TEST_MMIO_LIB')
        if not path:self.skipTest('Set EDGE_TEST_MMIO_LIB to a compiled host test library')
        lib=ctypes.CDLL(path,use_errno=True)
        lib.edge_open.argtypes=[ctypes.c_char_p,ctypes.c_uint64];lib.edge_open.restype=ctypes.c_void_p
        lib.edge_read.argtypes=[ctypes.c_void_p,ctypes.c_uint32];lib.edge_read.restype=ctypes.c_uint32
        lib.edge_write.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32];lib.edge_write.restype=None
        lib.edge_close.argtypes=[ctypes.c_void_p];lib.edge_close.restype=None
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'page';file.write_bytes(bytes(65536));handle=lib.edge_open(os.fsencode(file),0)
            self.assertTrue(handle)
            try:
                self.assertFalse(lib.edge_open(os.fsencode(file),0));self.assertIn(ctypes.get_errno(),[errno.EWOULDBLOCK,errno.EAGAIN])
                for offset,value in [(0,0x45444731),(4,0x10000),(0xfffc,0xfedcba98)]:
                    lib.edge_write(handle,offset,value);self.assertEqual(lib.edge_read(handle,offset),value)
                self.assertEqual(struct.unpack_from('<I',file.read_bytes(),0xfffc)[0],0xfedcba98)
                ctypes.set_errno(0);self.assertEqual(lib.edge_read(handle,3),0);self.assertEqual(ctypes.get_errno(),errno.EINVAL)
            finally:lib.edge_close(handle)
            handle=lib.edge_open(os.fsencode(file),0);self.assertTrue(handle);lib.edge_close(handle)

if __name__=='__main__':unittest.main()
