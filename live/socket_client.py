import socket


class SocketClient:

    def __init__(self, addr, port):
        self.addr = addr
        self.port = port
        self.socket = None
        self.is_open = False
        self.__connect__()

    def __connect__(self):
        try:
            self.socket = socket.socket()
            self.socket.connect((self.addr, self.port))
            self.is_open = True
        except Exception as e:
            print('connect error: ', e)
            raise e

    def send(self, msg: bytes):
        try:
            if self.is_open:
                self.socket.send(msg)
        except Exception as e:
            print('send error: ', e)
            raise e

    def read(self):
        try:
            if self.is_open:
                body = self.socket.recv(1024)
                if body:
                    self.on_message(body)
                    return body
        except Exception as e:
            print('read error: ', e)
            raise e

    def on_message(self, msg: bytes):
        print(self)
        print(str(msg, encoding='utf-8'))

    def close(self):
        if self.is_open:
            self.socket.close()
            self.is_open = False
