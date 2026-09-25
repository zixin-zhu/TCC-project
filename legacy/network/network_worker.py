from PyQt5.QtCore import QThread, pyqtSignal

from network.tcp_client import TCPClient
from network.message_protocol import MessageProtocol
from network.tcp_server import TCPServer

class ClientNetworkWorker(QThread):
    """
    TCC-A客户端网络线程

    专门负责：
    1. 连接TCC-B
    2. 后台持续接收消息
    3. 将网络事件通知给PyQt主线程
    """

    # 连接成功信号
    connected = pyqtSignal()

    # 连接断开信号
    disconnected = pyqtSignal()

    # 收到消息信号
    message_received = pyqtSignal(dict)

    # 网络错误信号
    error = pyqtSignal(str)

    def __init__(self, host="127.0.0.1", port=9000):
        super().__init__()

        self.client = TCPClient(host, port)

        self.running = False

    def run(self):
        """
        QThread启动后自动在后台线程执行。
        """

        try:
            # 连接TCC-B
            self.client.connect()

            self.running = True

            # 通知GUI：连接成功
            self.connected.emit()

            # 持续接收
            while self.running:

                message_text = self.client.receive()

                if message_text is None:
                    break

                message = MessageProtocol.decode(
                    message_text
                )

                # 把收到的消息交给GUI
                self.message_received.emit(message)

        except Exception as e:

            self.error.emit(str(e))

        finally:

            self.running = False

            self.disconnected.emit()

    def send_message(self, message):
        """
        发送Python字典格式的TCC报文。
        """

        if not self.running:
            return

        message_text = MessageProtocol.encode(message)

        self.client.send(message_text)

    def stop(self):
        """停止网络线程"""

        self.running = False

        try:
            self.client.close()
        except Exception:
            pass

class ServerNetworkWorker(QThread):
    """
    TCC-B服务器网络线程

    负责：
    1. 启动TCP服务器
    2. 等待TCC-A连接
    3. 持续接收TCC-A报文
    """

    connected = pyqtSignal()

    disconnected = pyqtSignal()

    message_received = pyqtSignal(dict)

    error = pyqtSignal(str)

    def __init__(self, host="127.0.0.1", port=9000):
        super().__init__()

        self.server = TCPServer(host, port)

        self.running = False

    def run(self):

        try:

            # start()内部会等待Client连接
            # 但是现在是在后台线程，不会卡GUI
            self.server.start()

            self.running = True

            self.connected.emit()

            while self.running:

                message_text = self.server.receive()

                if message_text is None:
                    break

                message = MessageProtocol.decode(
                    message_text
                )

                self.message_received.emit(message)

        except Exception as e:

            self.error.emit(str(e))

        finally:

            self.running = False

            self.disconnected.emit()

    def send_message(self, message):

        if not self.running:
            return

        message_text = MessageProtocol.encode(message)

        self.server.send(message_text)

    def stop(self):

        self.running = False

        try:
            self.server.close()
        except Exception:
            pass