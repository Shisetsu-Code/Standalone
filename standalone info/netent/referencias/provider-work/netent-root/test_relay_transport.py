import importlib.util
import socket
import threading
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('netent_relay', Path(__file__).with_name('relay_transport.py'))
relay = importlib.util.module_from_spec(SPEC)
if SPEC.loader and Path(SPEC.origin).exists():
    SPEC.loader.exec_module(relay)


class TransportTests(unittest.TestCase):
    def test_general_provider_authorities(self):
        validate = getattr(relay, 'validate_target', lambda value: None)
        self.assertEqual(validate('showcase.evo-games.com:443'), ('showcase.evo-games.com', 443))
        self.assertEqual(validate('example.com:443'), ('example.com', 443))
        for target in ['127.0.0.1:443', 'showcase.evo-games.com:0',
                       'u@showcase.evo-games.com:443',
                       'showcase.evo-games.com:443/path', 'SHOWCASE.EVO-GAMES.COM:443\r\nX:x']:
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate(target)

    def test_nonpublic_dns_is_rejected(self):
        resolve = getattr(relay, 'public_addresses', None)
        self.assertIsNotNone(resolve, 'DNS validation is missing')
        def dns(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]
        with self.assertRaises(ValueError):
            resolve('showcase.evo-games.com', 443, resolver=dns)

    def test_tunnel_preserves_bytes_both_directions(self):
        pump = getattr(relay, 'pump', None)
        self.assertIsNotNone(pump, 'Duplex byte relay is missing')
        client, left = socket.socketpair(); right, upstream = socket.socketpair()
        counts = {}
        worker = threading.Thread(target=lambda: counts.update(pump(left, right, idle_seconds=2)))
        worker.start()
        try:
            client.settimeout(3); upstream.settimeout(3)
            outbound = b'\x00\xfftls-client\r\n'; inbound = b'\xff\x00tls-server\r\n'
            client.sendall(outbound); self.assertEqual(upstream.recv(100), outbound)
            upstream.sendall(inbound); self.assertEqual(client.recv(100), inbound)
            client.shutdown(socket.SHUT_WR); upstream.shutdown(socket.SHUT_WR)
            worker.join(4)
            self.assertFalse(worker.is_alive())
            self.assertEqual(counts, {'sent': len(outbound), 'received': len(inbound)})
        finally:
            for sock in [client, left, right, upstream]: sock.close()


if __name__ == '__main__': unittest.main()
