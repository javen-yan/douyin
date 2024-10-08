# encoding: utf-8
import gzip
import json
import urllib
import uuid

from utils.threadfunc import stop_thread
from .socket_client import SocketClient
from .msg_exchanger import format_msg
from google.protobuf.json_format import MessageToDict
from websocket import WebSocketApp
import websocket
import requests
import re
import logging
import threading
import time

from protobuf import message_pb2

default_format_filter = [
    "WebcastLikeMessage",
    "WebcastChatMessage",
    "WebcastMemberMessage",
    "WebcastGiftMessage"
]


class Live(WebSocketApp):

    def __init__(self, live_url, **kwargs):

        if kwargs.get('filter_method'):
            self.filter_method = kwargs.get('filter_method')
        else:
            self.filter_method = default_format_filter

        self.__callback_sockets = kwargs.get('callback_socket')

        self.live_url = live_url
        self.request = requests.Session()

        self.request.headers.update({
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,'
                      '*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/107.0.0.0 Safari/537.36'
        })

        self.is_open = False
        self.id = str(uuid.uuid4()).replace('-', '')
        self.cb_clients = {}
        self.ping_thread = None
        self.main_thread = None
        self._tid = ""
        self._room_store = {}
        self._user_store = {}
        self._live_room_id = ""
        self._live_room_title = ""
        self._push_id = ""
        self._log_id = ""
        self.__ac_nonce = ""

        self._parser_live_info()

        self.__callback_builder()

        h = {
            'Cookie': 'ttwid=' + self._tid,
        }

        super(Live, self).__init__(url=self.connect_url, header=h,
                                   on_message=self.on_message, on_error=self.on_error,
                                   on_open=self.on_open, on_close=self.on_close)

    @property
    def info(self):
        return {
            "id": self.id,
            "room_id": self._live_room_id,
            "room_title": self._live_room_title,
            "room_store": self._room_store,
            "user_store": self._user_store,
            "push_did": self._push_id
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
            format_flag = False
            if t.method in default_format_filter:
                format_flag = True
            if t.method not in self.filter_method:
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
            elif t.method == "WebcastRoomUserSeqMessage":
                message_ = message_pb2.RoomUserSeqMessage()
                message_.ParseFromString(payload)
            elif t.method == "WebcastFansClubMessage":
                message_ = message_pb2.FansClubMessage()
                message_.ParseFromString(payload)
            elif t.method == "WebcastControlMessage":
                message_ = message_pb2.ControlMessage()
                message_.ParseFromString(payload)
            if message_:
                obj1 = MessageToDict(message_, preserving_proto_field_name=True)
                if format_flag:
                    obj1 = format_msg(obj1)
                logging.debug('[onMessage] [webSocket Message事件] [房间Id：' +
                              self._live_room_id + '] [内容：' + str(json.dumps(obj1, ensure_ascii=False)) + ']')
                self.callback(bytes(json.dumps(obj1, ensure_ascii=False), encoding='utf-8'))

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
        self.is_open = False
        logging.warning('[onClose] [webSocket Close事件] [房间Id：' + self._live_room_id + ']')
        for k, v in self.cb_clients.items():
            v.close()
            del self.cb_clients[k]

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
        try:
            self.send(data, websocket.ABNF.OPCODE_BINARY)
        except Exception as e:
            logging.error('[sendAck] [发送ack失败] [房间Id：' + self._live_room_id + '] [错误信息：' + str(e) + ']')
            pass

    def ping(self):
        """
        :method: ping
        """
        while self.is_open:
            obj = message_pb2.PushFrame()
            obj.payloadtype = 'hb'
            data = obj.SerializeToString()
            try:
                self.send(data, websocket.ABNF.OPCODE_BINARY)
                logging.info(
                    '[ping] [💗发送ping心跳] [房间Id：' + self._live_room_id + '] ====> 房间🏖标题【' + self._live_room_title + '】')
                time.sleep(10)
            except Exception as e:
                logging.error('[ping] [发送ping心跳失败] [房间Id：' + self._live_room_id + '] [错误信息：' + str(e) + ']')
                pass

    def on_open(self, *args):
        """
        :method: on open
        """
        self.is_open = True
        self.ping_thread = threading.Thread(target=self.ping)
        self.ping_thread.start()
        logging.info('[onOpen] [webSocket Open事件] [房间Id：' + self._live_room_id + ']')

    def _get_ac_nonce(self):
        """
        :method: get ac nonce
        """
        response = self.request.get(self.live_url)
        self.__ac_nonce = response.cookies.get('__ac_nonce')
        return self.__ac_nonce

    def _parser_live_info(self):
        """
        :method: parser live info
        """
        self.request.headers.update({
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,'
                      '*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/107.0.0.0 Safari/537.36'
        })
        if self.__ac_nonce == "":
            logging.warning('[parserLiveInfo] [获取__ac_nonce失败] [房间Id：' + self._live_room_id + '] 重新获取')
            self.__ac_nonce = self._get_ac_nonce()
            logging.warning(
                '[parserLiveInfo] [获取__ac_nonce成功] [房间Id：' + self._live_room_id + ']' + self.__ac_nonce)
        self.request.headers.update({
            'cookie': '__ac_nonce=' + self.__ac_nonce
        })
        response = self.request.get(self.live_url)
        data = response.cookies.get_dict()
        try:
            self._tid = data['ttwid']
            self._log_id = response.headers.get('x-tt-logid')
            res = response.text
            res = re.search(r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', res)
            res = res.group(1)
            res = urllib.parse.unquote(res, encoding='utf-8', errors='replace')
            res = json.loads(res)
            self._room_store = res['app']['initialState']['roomStore']
            self._user_store = res['app']['initialState']['userStore']
            self._push_id = self._user_store['odin']['user_unique_id']
            self._live_room_id = self._room_store['roomInfo']['roomId']
            self._live_room_title = self._room_store['roomInfo']['room']['title']
        except Exception as e:
            logging.error('[解析直播间信息] [异常] [房间Id：' + self._live_room_id + ']' + str(e))
            raise e

    @property
    def connect_url(self):
        now_nano = time.time_ns()
        now_sec = int(int(round(time.time() * 1000)))
        now_nano_2 = time.time_ns()

        params = {
            'app_name': 'douyin_web',
            'version_code': '180800',
            'webcast_sdk_version': '1.3.0',
            'update_version_code': '1.3.0',
            'compress': 'gzip',
            'internal_ext': f'internal_src:dim|wss_push_room_id:{self._live_room_id}|wss_push_did:{self._push_id}'
                            f'|dim_log_id:{self._log_id}|fetch_time:{now_sec}|seq:1|wss_info:0'
                            f'-{now_sec}-0-0|wrds_kvs:WebcastRoomRankMessage'
                            f'-{now_nano}_WebcastRoomStatsMessage-{now_nano_2}',
            'cursor': f'h-1_t-{now_sec}_r-1_d-1_u-1',
            'host': 'https://live.douyin.com',
            'aid': '6383',
            'live_id': '1',
            'did_rule': '3',
            'debug': False,
            'endpoint': 'live_pc',
            'support_wrds': '1',
            'im_path': '/webcast/im/fetch/',
            'device_platform': 'web',
            'cookie_enabled': True,
            'screen_width': 1680,
            'screen_height': 1050,
            'browser_language': 'zh',
            'browser_platform': 'MacIntel',
            'browser_name': 'Mozilla',
            'browser_version': '5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
                               'Chrome/107.0.0.0 Safari/537.36',
            'browser_online': True,
            'tz_name': 'Asia/Shanghai',
            'identity': 'audience',
            'room_id': self._live_room_id,
            'heartbeatDuration': 0
        }

        return 'wss://webcast3-ws-web-lf.douyin.com/webcast/im/push/v2/?' + urllib.parse.urlencode(params)

    def __callback_builder(self):

        if self.__callback_sockets is None:
            return None

        for callback_socket in self.__callback_sockets:
            peer = callback_socket.split(':')
            if len(peer) != 2:
                continue
            try:
                host = peer[0]
                port = int(peer[1])
                client = SocketClient(host, port)
                self.cb_clients[peer] = client
            except Exception as e:
                logging.error('[回调] [异常' + 'socket:' + callback_socket + '] [房间Id：' + self._live_room_id + ']' + str(e))
                continue

    def callback(self, msg: bytes):

        if self.cb_clients is None:
            return None

        for url, client in self.cb_clients.items():
            try:
                client.send(msg)
            except Exception as e:
                logging.error('[回调] [异常' + 'socket:' + url + '] [房间Id：' + self._live_room_id + ']' + str(e))
                del self.cb_clients[url]
                continue

    def stop(self):
        self.is_open = False
        if self.main_thread is not None:
            stop_thread(self.main_thread)
        if self.ping_thread is not None:
            stop_thread(self.ping_thread)
        self.close()

    def start(self):
        self.main_thread = threading.Thread(target=self.run_forever)
        self.main_thread.start()
