import unittest
from unittest.mock import patch
from fetch_ios import stock

class Response:
    status=206
    def __init__(self,data,etag='fixed',content_range='bytes 0-3/100'):
        self.data=data;self.headers={'ETag':etag,'Content-Range':content_range}
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,size): return self.data

class RangeRetryTests(unittest.TestCase):
    def remote(self):
        obj=stock.RemoteZip.__new__(stock.RemoteZip)
        obj.url='https://example.invalid/pinned';obj.etag='fixed';obj.size=100;obj.downloaded=0
        return obj
    def test_short_response_retries_whole_range(self):
        obj=self.remote()
        with patch.object(stock.urllib.request,'urlopen',side_effect=[Response(b'ab'),Response(b'abcd')]) as request, patch.object(stock.time,'sleep'):
            self.assertEqual(obj.fetch(0,4),b'abcd')
        self.assertEqual(request.call_count,2);self.assertEqual(obj.downloaded,4)
    def test_changed_identity_and_invalid_ranges_not_retried(self):
        for response in [Response(b'abcd','changed'),Response(b'abcd',content_range='bytes 4-7/100'),Response(b'abcde')]:
            with patch.object(stock.urllib.request,'urlopen',return_value=response) as request:
                with self.assertRaises(ValueError): self.remote().fetch(0,4)
            self.assertEqual(request.call_count,1)
    def test_short_response_has_bounded_retries(self):
        with patch.object(stock.urllib.request,'urlopen',return_value=Response(b'a')) as request, patch.object(stock.time,'sleep'):
            with self.assertRaises(EOFError): self.remote().fetch(0,4)
        self.assertEqual(request.call_count,3)
