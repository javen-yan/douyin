# encoding: utf-8
import codecs
import gzip
import hashlib
import json
import random
import re
import string
import subprocess
import threading
import time
import urllib
import urllib.parse
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import requests
import websocket
import logging
from py_mini_racer import MiniRacer
from google.protobuf.json_format import MessageToDict
from websocket import WebSocketApp

from utils.threadfunc import stop_thread
from .socket_client import SocketClient
from .msg_exchanger import format_msg
from protobuf.douyin import (
    PushFrame, Response, Message, ChatMessage, GiftMessage, LikeMessage, 
    MemberMessage, SocialMessage, RoomUserSeqMessage, FansclubMessage, 
    ControlMessage, EmojiChatMessage, RoomStatsMessage, RoomMessage, 
    RoomRankMessage, RoomStreamAdaptationMessage
)

default_format_filter = [
    "WebcastLikeMessage",
    "WebcastChatMessage",
    "WebcastMemberMessage",
    "WebcastGiftMessage"
]


@contextmanager
def patched_popen_encoding(encoding='utf-8'):
    original_popen_init = subprocess.Popen.__init__

    def new_popen_init(self, *args, **kwargs):
        kwargs['encoding'] = encoding
        original_popen_init(self, *args, **kwargs)

    with patch.object(subprocess.Popen, '__init__', new_popen_init):
        yield


def generateSignature(wss, script_file='sign.js'):
    """
        出现gbk编码问题则修改 python模块subprocess.py的源码中Popen类的__init__函数参数encoding值为 "utf-8"
    """
    params = ("live_id,aid,version_code,webcast_sdk_version,"
              "room_id,sub_room_id,sub_channel_id,did_rule,"
              "user_unique_id,device_platform,device_type,ac,"
              "identity").split(',')
    wss_params = urllib.parse.urlparse(wss).query.split('&')
    wss_maps = {i.split('=')[0]: i.split("=")[-1] for i in wss_params}
    tpl_params = [f"{i}={wss_maps.get(i, '')}" for i in params]
    param = ','.join(tpl_params)
    md5 = hashlib.md5()
    md5.update(param.encode())
    md5_param = md5.hexdigest()

    with codecs.open(script_file, 'r', encoding='utf8') as f:
        script = f.read()

    ctx = MiniRacer()
    ctx.eval(script)

    try:
        signature = ctx.call("get_sign", md5_param)
        return signature
    except Exception as e:
        print(e)


def generateMsToken(length=107):
    """
    产生请求头部cookie中的msToken字段，其实为随机的107位字符
    :param length:字符位数
    :return:msToken
    """
    random_str = ''
    base_str = string.ascii_letters + string.digits + '=_'
    _len = len(base_str) - 1
    for _ in range(length):
        random_str += base_str[random.randint(0, _len)]
    return random_str


class Live(WebSocketApp):

    def __init__(self, live_url, **kwargs):
        if 'live.douyin.com' in live_url:
            self.live_id = live_url.split('/')[-1]
        else:
            self.live_id = live_url

        if kwargs.get('filter_method'):
            self.filter_method = kwargs.get('filter_method')
        else:
            self.filter_method = default_format_filter

        self.__callback_sockets = kwargs.get('callback_socket')

        self.live_url = f"https://live.douyin.com/{self.live_id}" if not live_url.startswith('http') else live_url
        self.request = requests.Session()

        self.request.headers.update({
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,'
                      '*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36'
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
        self.__ttwid = None
        self.__room_id = None

        self._parser_live_info()

        self.__callback_builder()

        h = {
            'Cookie': 'ttwid=' + self._tid,
        }

        super(Live, self).__init__(url=self.connect_url, header=h,
                                   on_message=self.on_message, on_error=self.on_error,
                                   on_open=self.on_open, on_close=self.on_close)

    @property
    def ttwid(self):
        """
        产生请求头部cookie中的ttwid字段，访问抖音网页版直播间首页可以获取到响应cookie中的ttwid
        :return: ttwid
        """
        if self.__ttwid:
            return self.__ttwid
        headers = {
            "User-Agent": self.request.headers.get('User-Agent'),
        }
        try:
            response = requests.get("https://live.douyin.com/", headers=headers)
            response.raise_for_status()
        except Exception as err:
            print("【X】Request the live url error: ", err)
        else:
            self.__ttwid = response.cookies.get('ttwid')
            return self.__ttwid

    @property
    def room_id(self):
        """
        根据直播间的地址获取到真正的直播间roomId，有时会有错误，可以重试请求解决
        :return:room_id
        """
        if self.__room_id:
            return self.__room_id
        url = f"https://live.douyin.com/{self.live_id}"
        headers = {
            "User-Agent": self.request.headers.get('User-Agent'),
            "cookie": f"ttwid={self.ttwid}&msToken={generateMsToken()}; __ac_nonce=0123407cc00a9e438deb4",
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
        except Exception as err:
            print("【X】Request the live room url error: ", err)
        else:
            match = re.search(r'roomId\\":\\"(\d+)\\"', response.text)
            if match is None or len(match.groups()) < 1:
                print("【X】No match found for roomId")
            else:
                self.__room_id = match.group(1)
            return self.__room_id

    def get_room_status(self):
        """
        获取直播间开播状态:
        room_status: 2 直播已结束
        room_status: 0 直播进行中
        """
        url = ('https://live.douyin.com/webcast/room/web/enter/?aid=6383'
               '&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN&enter_from=web_live'
               '&cookie_enabled=true&screen_width=1536&screen_height=864&browser_language=zh-CN&browser_platform=Win32'
               '&browser_name=Edge&browser_version=133.0.0.0'
               f'&web_rid={self.live_id}'
               f'&room_id_str={self.room_id}'
               '&enter_source=&is_need_double_stream=false&insert_task_id=&live_reason='
               '&msToken=&a_bogus=')
        resp = requests.get(url, headers={
            'User-Agent': self.request.headers.get('User-Agent'),
            'Cookie': f'ttwid={self.ttwid};'
        })
        data = resp.json().get('data')
        if data:
            room_status = data.get('room_status')
            user = data.get('user')
            user_id = user.get('id_str')
            nickname = user.get('nickname')
            print(
                f"【{nickname}】[{user_id}]直播间：{['正在直播', '已结束'][bool(room_status)]}.")

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

        # 根据proto结构体解析对象
        package = PushFrame().parse(message)
        response = Response().parse(gzip.decompress(package.payload))

        # 返回直播间服务器链接存活确认消息，便于持续获取数据
        if response.need_ack:
            ack = PushFrame(log_id=package.log_id,
                            payload_type='ack',
                            payload=response.internal_ext.encode('utf-8')
                            ).SerializeToString()
            self.send(ack, websocket.ABNF.OPCODE_BINARY)

        # 根据消息类别解析消息体
        for msg in response.messages_list:
            method = msg.method
            print(f"====== 【{method}】 ====")
            try:
                if method == 'WebcastChatMessage':
                    self._parseChatMsg(msg.payload)
                elif method == 'WebcastGiftMessage':
                    self._parseGiftMsg(msg.payload)
                elif method == 'WebcastLikeMessage':
                    self._parseLikeMsg(msg.payload)
                elif method == 'WebcastMemberMessage':
                    self._parseMemberMsg(msg.payload)
                elif method == 'WebcastSocialMessage':
                    self._parseSocialMsg(msg.payload)
                elif method == 'WebcastRoomUserSeqMessage':
                    self._parseRoomUserSeqMsg(msg.payload)
                elif method == 'WebcastFansclubMessage':
                    self._parseFansclubMsg(msg.payload)
                elif method == 'WebcastControlMessage':
                    self._parseControlMsg(msg.payload)
                elif method == 'WebcastEmojiChatMessage':
                    self._parseEmojiChatMsg(msg.payload)
                elif method == 'WebcastRoomStatsMessage':
                    self._parseRoomStatsMsg(msg.payload)
                elif method == 'WebcastRoomMessage':
                    self._parseRoomMsg(msg.payload)
                elif method == 'WebcastRoomRankMessage':
                    self._parseRankMsg(msg.payload)
                elif method == 'WebcastRoomStreamAdaptationMessage':
                    self._parseRoomStreamAdaptationMsg(msg.payload)
                
                # 保持原有的回调机制
                if method in self.filter_method:
                    try:
                        # 尝试解析为字典格式用于回调
                        message_obj = self._parse_message_to_dict(method, msg.payload)
                        if message_obj:
                            obj1 = MessageToDict(message_obj, preserving_proto_field_name=True)
                            if method in default_format_filter:
                                obj1 = format_msg(obj1)
                            self.callback(bytes(json.dumps(obj1, ensure_ascii=False), encoding='utf-8'))
                    except Exception as e:
                        pass
            except Exception:
                pass

    def _parse_message_to_dict(self, method, payload):
        """解析消息为字典格式，用于回调"""
        try:
            if method == "WebcastLikeMessage":
                return LikeMessage().parse(payload)
            elif method == "WebcaxstChatMessage":
                return ChatMessage().parse(payload)
            elif method == "WebcastMemberMessage":
                return MemberMessage().parse(payload)
            elif method == "WebcastSocialMessage":
                return SocialMessage().parse(payload)
            elif method == "WebcastGiftMessage":
                return GiftMessage().parse(payload)
            elif method == "WebcastRoomUserSeqMessage":
                return RoomUserSeqMessage().parse(payload)
            elif method == "WebcastFansclubMessage":
                return FansclubMessage().parse(payload)
            elif method == "WebcastControlMessage":
                return ControlMessage().parse(payload)
            elif method == "WebcastEmojiChatMessage":
                return EmojiChatMessage().parse(payload)
            elif method == "WebcastRoomStatsMessage":
                return RoomStatsMessage().parse(payload)
            elif method == "WebcastRoomMessage":
                return RoomMessage().parse(payload)
            elif method == "WebcastRoomRankMessage":
                return RoomRankMessage().parse(payload)
            elif method == "WebcastRoomStreamAdaptationMessage":
                return RoomStreamAdaptationMessage().parse(payload)
        except Exception:
            pass
        return None

    def _parseChatMsg(self, payload):
        """聊天消息"""
        message = ChatMessage().parse(payload)
        user_name = message.user.nick_name
        user_id = message.user.id
        content = message.content
        print(f"【聊天msg】[{user_id}]{user_name}: {content}")

    def _parseGiftMsg(self, payload):
        """礼物消息"""
        message = GiftMessage().parse(payload)
        user_name = message.user.nick_name
        gift_name = message.gift.name
        gift_cnt = message.combo_count
        print(f"【礼物msg】{user_name} 送出了 {gift_name}x{gift_cnt}")

    def _parseLikeMsg(self, payload):
        '''点赞消息'''
        message = LikeMessage().parse(payload)
        user_name = message.user.nick_name
        count = message.count
        print(f"【点赞msg】{user_name} 点了{count}个赞")

    def _parseMemberMsg(self, payload):
        '''进入直播间消息'''
        message = MemberMessage().parse(payload)
        user_name = message.user.nick_name
        user_id = message.user.id
        gender = ["女", "男"][message.user.gender]
        print(f"【进场msg】[{user_id}][{gender}]{user_name} 进入了直播间")

    def _parseSocialMsg(self, payload):
        '''关注消息'''
        message = SocialMessage().parse(payload)
        user_name = message.user.nick_name
        user_id = message.user.id
        print(f"【关注msg】[{user_id}]{user_name} 关注了主播")

    def _parseRoomUserSeqMsg(self, payload):
        '''直播间统计'''
        message = RoomUserSeqMessage().parse(payload)
        current = message.total
        total = message.total_pv_for_anchor
        print(f"【统计msg】当前观看人数: {current}, 累计观看人数: {total}")

    def _parseFansclubMsg(self, payload):
        '''粉丝团消息'''
        message = FansclubMessage().parse(payload)
        content = message.content
        print(f"【粉丝团msg】 {content}")

    def _parseEmojiChatMsg(self, payload):
        '''聊天表情包消息'''
        message = EmojiChatMessage().parse(payload)
        emoji_id = message.emoji_id
        user = message.user
        common = message.common
        default_content = message.default_content
        print(
            f"【聊天表情包id】 {emoji_id},user：{user},common:{common},default_content:{default_content}")

    def _parseRoomMsg(self, payload):
        message = RoomMessage().parse(payload)
        common = message.common
        room_id = common.room_id
        print(f"【直播间msg】直播间id:{room_id}")

    def _parseRoomStatsMsg(self, payload):
        message = RoomStatsMessage().parse(payload)
        display_long = message.display_long
        print(f"【直播间统计msg】{display_long}")

    def _parseRankMsg(self, payload):
        message = RoomRankMessage().parse(payload)
        ranks_list = message.ranks_list
        print(f"【直播间排行榜msg】{ranks_list}")

    def _parseControlMsg(self, payload):
        '''直播间状态消息'''
        message = ControlMessage().parse(payload)

        if message.status == 3:
            print("直播间已结束")
            self.stop()

    def _parseRoomStreamAdaptationMsg(self, payload):
        message = RoomStreamAdaptationMessage().parse(payload)
        adaptationType = message.adaptation_type
        print(f'直播间adaptation: {adaptationType}')

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
        self.get_room_status()
        print("WebSocket connection closed.")
        for k, v in self.cb_clients.items():
            v.close()
            del self.cb_clients[k]

    def send_ack(self, logid, internal_ext):
        """
        :method: send ack
        :param logid: logid
        :param internal_ext: internal_ext
        """
        ack = PushFrame(log_id=logid,
                        payload_type='ack',
                        payload=internal_ext.encode('utf-8')
                        ).SerializeToString()
        try:
            self.send(ack, websocket.ABNF.OPCODE_BINARY)
        except Exception as e:
            logging.error('[sendAck] [发送ack失败] [房间Id：' + self._live_room_id + '] [错误信息：' + str(e) + ']')
            pass

    def ping(self):
        while self.is_open:
            try:
                heartbeat = PushFrame(payload_type='hb').SerializeToString()
                self.send(heartbeat, websocket.ABNF.OPCODE_PING)
                print("【√】发送心跳包")
            except Exception as e:
                print("【X】心跳包检测错误: ", e)
                break
            else:
                time.sleep(5)

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
        # 获取 ttwid
        self._tid = self.ttwid
        
        # 获取 room_id
        self._live_room_id = self.room_id
        
        # 尝试获取其他信息
        try:
            response = self.request.get(self.live_url)
            data = response.cookies.get_dict()
            self._log_id = response.headers.get('x-tt-logid')
            res = response.text
            res = re.search(r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', res)
            if res:
                res = res.group(1)
                res = urllib.parse.unquote(res, encoding='utf-8', errors='replace')
                res = json.loads(res)
                self._room_store = res['app']['initialState']['roomStore']
                self._user_store = res['app']['initialState']['userStore']
                self._push_id = self._user_store['odin']['user_unique_id']
                self._live_room_title = self._room_store['roomInfo']['room']['title']
        except Exception as e:
            logging.error('[解析直播间信息] [异常] [房间Id：' + str(self._live_room_id) + ']' + str(e))
            # 如果解析失败，使用默认值
            self._live_room_title = f"直播间 {self.live_id}"
            self._push_id = "7319483754668557238"

    @property
    def connect_url(self):
        wss = ("wss://webcast100-ws-web-lq.douyin.com/webcast/im/push/v2/?app_name=douyin_web"
               "&version_code=180800&webcast_sdk_version=1.0.14-beta.0"
               "&update_version_code=1.0.14-beta.0&compress=gzip&device_platform=web&cookie_enabled=true"
               "&screen_width=1536&screen_height=864&browser_language=zh-CN&browser_platform=Win32"
               "&browser_name=Mozilla"
               "&browser_version=5.0%20(Windows%20NT%2010.0;%20Win64;%20x64)%20AppleWebKit/537.36%20(KHTML,"
               "%20like%20Gecko)%20Chrome/126.0.0.0%20Safari/537.36"
               "&browser_online=true&tz_name=Asia/Shanghai"
               "&cursor=d-1_u-1_fh-7392091211001140287_t-1721106114633_r-1"
               f"&internal_ext=internal_src:dim|wss_push_room_id:{self.room_id}|wss_push_did:7319483754668557238"
               f"|first_req_ms:1721106114541|fetch_time:1721106114633|seq:1|wss_info:0-1721106114633-0-0|"
               f"wrds_v:7392094459690748497"
               f"&host=https://live.douyin.com&aid=6383&live_id=1&did_rule=3&endpoint=live_pc&support_wrds=1"
               f"&user_unique_id=7319483754668557238&im_path=/webcast/im/fetch/&identity=audience"
               f"&need_persist_msg_count=15&insert_task_id=&live_reason=&room_id={self.room_id}&heartbeatDuration=0")

        signature = generateSignature(wss)
        wss += f"&signature={signature}"
        
        return wss

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
