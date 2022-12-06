import logging

from spider import spider

if __name__ == '__main__':
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)
    url = 'https://live.douyin.com/68854560516'
    spider.parseLiveRoomUrl(url)
