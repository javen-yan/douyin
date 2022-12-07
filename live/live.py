# encoding: utf-8
import gzip
import json
import urllib

from google.protobuf.json_format import MessageToDict
from websocket import WebSocketApp
import websocket
import requests
import re
import logging

try:
    import thread
except ImportError:
    import _thread as thread
import time

from protobuf import message_pb2


class Live(WebSocketApp):

    def __init__(self, live_url, callback_ws=None, filter_method=None):
        if callback_ws is None:
            callback_ws = []

        if filter_method is None:
            filter_method = [
                "WebcastLikeMessage",
                "WebcastChatMessage",
                "WebcastMemberMessage",
                "WebcastSocialMessage",
                "WebcastGiftMessage"
            ]

        self.filter_method = filter_method
        self.callback_ws = callback_ws
        self.live_url = live_url
        self.request = requests.Session()

        self._tid = ""
        self._room_store = {}
        self._live_room_id = ""
        self._live_room_title = ""

        self._parser_live_info()

        h = {
            'Cookie': 'ttwid=' + self._tid,
        }

        super(Live, self).__init__(url=self.connect_url, header=h,
                                   on_message=self.on_message, on_error=self.on_error,
                                   on_open=self.on_open, on_close=self.on_close)

    @property
    def info(self):
        return {
            "room_id": self._live_room_id,
            "room_title": self._live_room_title,
            "room_store": self._room_store
        }

    def on_message(self, *args):
        """
        :method: on message
        :param args: [0] = class WebSocketApp
        :param args: [1] = data bytes
        """

        message = args[1]

        o = message_pb2.PushFrame()
        o.ParseFromString(message)
        payload = gzip.decompress(o.palyload)
        r = message_pb2.Response()
        r.ParseFromString(payload)

        if r.needAck:
            self.send_ack(o.logid, r.internalExt)

        for t in r.messages:
            payload = t.payload
            message_ = ''
            if t.method not in self.filter_method:
                logging.warning('[缺失捕获] [房间Id：' + self._live_room_id + ']' + 'method : ' + t.method)
                continue
            if t.method == "WebcastLikeMessage":
                message_ = message_pb2.LikeMessage()
                message_.ParseFromString(payload)
            elif t.method == "WebcastChatMessage":
                message_ = message_pb2.ChatMessage()
                message_.ParseFromString(payload)
            elif t.method == "WebcastMemberMessage":
                message_ = message_pb2.MemberMessage()
                message_.ParseFromString(payload)
            elif t.method == "WebcastSocialMessage":
                message_ = message_pb2.SocialMessage()
                message_.ParseFromString(payload)
            elif t.method == "WebcastGiftMessage":
                message_ = message_pb2.GiftMessage()
                message_.ParseFromString(payload)
            if message_:
                obj1 = MessageToDict(message_, preserving_proto_field_name=True)
                print(json.dumps(obj1, ensure_ascii=False))

    def on_error(self, *args):
        """
        :method: on error
        :param args: [0] = class WebSocketApp
        :param args: [1] = error
        """
        logging.error('[onError] [webSocket Error事件] [房间Id：' + self._live_room_id + ']')

    def on_close(self, *args):
        """
        :method: on close
        :param args: [0] = class WebSocketApp
        :param args: [1] = close code
        """
        logging.warning('[onClose] [webSocket Close事件] [房间Id：' + self._live_room_id + ']')

    def send_ack(self, logid, internal_ext):
        """
        :method: send ack
        :param logid: logid
        :param internal_ext: internal_ext
        """
        obj = message_pb2.PushFrame()
        obj.payloadtype = 'ack'
        obj.logid = logid
        sdata = bytes(internal_ext, encoding="utf8")
        obj.payloadtype = sdata
        data = obj.SerializeToString()
        self.send(data, websocket.ABNF.OPCODE_BINARY)

    def ping(self):
        """
        :method: ping
        """
        while True:
            obj = message_pb2.PushFrame()
            obj.payloadtype = 'hb'
            data = obj.SerializeToString()
            self.send(data, websocket.ABNF.OPCODE_BINARY)
            logging.info('[ping] [💗发送ping心跳] [房间Id：' + self._live_room_id + '] ====> 房间🏖标题【' + self._live_room_title + '】')
            time.sleep(10)

    def on_open(self):
        """
        :method: on open
        """
        thread.start_new_thread(self.ping, ())
        logging.info('[onOpen] [webSocket Open事件] [房间Id：' + self._live_room_id + ']')

    def _parser_live_info(self):
        """
        :method: parser live info
        """
        self.request.headers.update({
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,'
                      '*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/107.0.0.0 Safari/537.36',
            'cookie': '__ac_nonce=0638733a400869171be51'
        })
        response = self.request.get(self.live_url)
        data = response.cookies.get_dict()
        self._tid = data['ttwid']
        res = response.text
        res = re.search(r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', res)
        res = res.group(1)
        res = urllib.parse.unquote(res, encoding='utf-8', errors='replace')
        res = json.loads(res)
        self._room_store = res['app']['initialState']['roomStore']
        self._live_room_id = self._room_store['roomInfo']['roomId']
        self._live_room_title = self._room_store['roomInfo']['room']['title']

    @property
    def connect_url(self):
        return 'wss://webcast3-ws-web-lf.douyin.com/webcast/im/push/v2/?app_name=douyin_web&version_code=180800' \
               '&webcast_sdk_version=1.3.0&update_version_code=1.3.0&compress=gzip&internal_ext=internal_src:dim' \
               '|wss_push_room_id:' + self._live_room_id + '|wss_push_did:7139391558914393612|dim_log_id' \
                                                           ':2022113016104801020810207318AA8748|fetch_time:1669795848095|seq:1|wss_info:0-1669795848095-0-0' \
                                                           '|wrds_kvs:WebcastRoomStatsMessage-1669795848048115671_WebcastRoomRankMessage-1669795848064411370' \
                                                           '&cursor=t-1669795848095_r-1_d-1_u-1_h-1&host=https://live.douyin.com&aid=6383&live_id=1&did_rule=3' \
                                                           '&debug=false&endpoint=live_pc&support_wrds=1&im_path=/webcast/im/fetch/&device_platform=web' \
                                                           '&cookie_enabled=true&screen_width=1440&screen_height=900&browser_language=zh&browser_platform' \
                                                           '=MacIntel&browser_name=Mozilla&browser_version=5.0%20(' \
                                                           'Macintosh;%20Intel%20Mac%20OS%20X%2010_15_7)%20AppleWebKit/537.36' \
                                                           '%20(KHTML,%20like%20Gecko)%20Chrome/107.0.0.0%20Safari/537.36&browser_online=true&tz_name=Asia' \
                                                           '/Shanghai&identity=audience&room_id=' + self._live_room_id + \
               '&heartbeatDuration=0 '


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    live = Live('https://live.douyin.com/561770113380')
    live.run_forever()
