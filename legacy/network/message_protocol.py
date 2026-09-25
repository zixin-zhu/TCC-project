import json


class MessageProtocol:
    """
    TCC站间通信报文协议

    负责：
    1. 创建标准消息
    2. 将消息编码为JSON字符串
    3. 将JSON字符串解析回Python对象
    """

    TRACK_STATUS = "TRACK_STATUS"
    SIGNAL_STATUS = "SIGNAL_STATUS"
    DIRECTION_REQUEST = "DIRECTION_REQUEST"
    DIRECTION_APPROVE = "DIRECTION_APPROVE"
    DIRECTION_DENY = "DIRECTION_DENY"
    DIRECTION_CONFIRM = "DIRECTION_CONFIRM"
    BALISE_MESSAGE = "BALISE_MESSAGE"
    ACK = "ACK"

    @staticmethod
    def create_message(message_type, source, data):
        """
        创建统一格式的TCC通信消息
        """

        return {
            "type": message_type,
            "source": source,
            "data": data
        }

    @staticmethod
    def encode(message):
        """
        Python字典 → JSON字符串
        """

        return json.dumps(
            message,
            ensure_ascii=False
        )

    @staticmethod
    def decode(message_text):
        """
        JSON字符串 → Python字典
        """

        return json.loads(message_text)