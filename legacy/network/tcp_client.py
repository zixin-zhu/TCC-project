import socket


class TCPClient:
    """
    TCC-A TCP客户端

    负责：
    1. 连接TCC-B服务器
    2. 向TCC-B发送数据
    3. 接收TCC-B返回的数据
    """

    def __init__(self, host="127.0.0.1", port=9000):
        self.host = host
        self.port = port

        self.client_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )
        self.receive_buffer = ""

    def connect(self):
        """连接TCC-B"""

        self.client_socket.connect(
            (self.host, self.port)
        )

        print(
            f"TCC-A已连接TCC-B："
            f"{self.host}:{self.port}"
        )

    def send(self, message):
        """发送一条完整消息"""

        message = message + "\n"

        self.client_socket.sendall(
            message.encode("utf-8")
        )

    def receive(self):
        """
        接收一条完整消息。
        每条消息使用换行符作为结束标记。
        """
        while "\n" not in self.receive_buffer:
            data = self.client_socket.recv(1024)
            if not data:
                return None
            self.receive_buffer += data.decode("utf-8")
        # 取出第一条完整消息
        message, self.receive_buffer = (
            self.receive_buffer.split("\n", 1)
        )
        return message

    def close(self):
        """关闭连接"""

        self.client_socket.close()