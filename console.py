import logging
from live import Live

if __name__ == '__main__':
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)
    app = Live('https://live.douyin.com/433399428821', callback_socket=['127.0.0.1:9999'])
    app.run_forever()


