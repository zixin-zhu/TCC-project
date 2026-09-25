import socket


class TCPServer:
    """
    TCC-B TCP服务器

    负责：
    1. 监听指定IP和端口
    2. 等待TCC-A连接
    3. 接收TCC-A发送的数据
    """

    def __init__(self, host="127.0.0.1", port=9000):
        self.host = host
        self.port = port

        # 创建TCP Socket
        self.server_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        self.client_socket = None
        self.client_address = None
        self.receive_buffer = ""

    def start(self):
        """启动TCP服务器"""
        # 绑定IP和端口
        self.server_socket.bind(
            (self.host, self.port)
        )
        # 开始监听
        self.server_socket.listen(1)
        print(
            f"TCC-B服务器启动成功，"
            f"正在监听 {self.host}:{self.port}"
        )
        print("等待TCC-A连接……")
        # 等待客户端连接
        self.client_socket, self.client_address = (
            self.server_socket.accept()
        )
        print(
            f"TCC-A连接成功："
            f"{self.client_address}"
        )

    def receive(self):
        """
        接收TCC-A发送的一条完整消息。
        """
        if self.client_socket is None:
            return None
        while "\n" not in self.receive_buffer:
            data = self.client_socket.recv(1024)
            if not data:
                return None
            self.receive_buffer += data.decode("utf-8")
        message, self.receive_buffer = (
            self.receive_buffer.split("\n", 1)
        )
        return message

    def send(self, message):
        """向TCC-A发送一条完整消息"""
        if self.client_socket is not None:
            message = message + "\n"
            self.client_socket.sendall(
                message.encode("utf-8")
            )

    def close(self):
        """关闭连接"""
        if self.client_socket is not None:
            self.client_socket.close()
        self.server_socket.close()