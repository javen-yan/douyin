import logging
from live import Live

if __name__ == '__main__':
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)
    app = Live('https://live.douyin.com/839944803868')
    app.run_forever()


