import socket
import unittest

from network.tcp_server import TCPServer


class NetworkReconnectTest(unittest.TestCase):
    def test_server_socket_allows_immediate_address_reuse(self):
        server = TCPServer("127.0.0.1", 0)

        try:
            reuse_address = server.server_socket.getsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
            )
            self.assertNotEqual(reuse_address, 0)
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
