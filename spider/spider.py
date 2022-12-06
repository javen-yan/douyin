import _thread
import gzip
import json
import logging
import re
import time
import requests
import websocket
import urllib
from google.protobuf import json_format
from google.protobuf.json_format import MessageToDict
from protobuf import message_pb2

liveRoomId = None
ttwid = None
roomStore = None
liveRoomTitle = None


def onMessage(ws: websocket.WebSocketApp, message: bytes):

    o = message_pb2.PushFrame()
    o.ParseFromString(message)

    print(o.logid)

    payload = gzip.decompress(o.palyload)
    r = message_pb2.Response()
    r.ParseFromString(payload)
    # print(r)
    e = r
    messagelist = e.messages
    for t in messagelist:
        o = t.payload
        message_ = ''
        if t.method == "WebcastLikeMessage":
            message_ = message_pb2.LikeMessage()
            message_.ParseFromString(o)
        elif t.method == "WebcastChatMessage":
            message_ = message_pb2.ChatMessage()
            message_.ParseFromString(o)
        elif t.method == "WebcastMemberMessage":
            message_ = message_pb2.MemberMessage()
            message_.ParseFromString(o)
        elif t.method == "WebcastSocialMessage":
            message_ = message_pb2.SocialMessage()
            message_.ParseFromString(o)
        elif t.method == "WebcastGiftMessage":
            message_ = message_pb2.GiftMessage()
            message_.ParseFromString(o)
        else:
            print(t.method)
        if message_:
            obj1 = MessageToDict(message_, preserving_proto_field_name=True)
            print(json.dumps(obj1, ensure_ascii=False))


def sendAck(ws, logid, internalExt):
    obj = message_pb2.PushFrame()
    obj.payloadtype = 'ack'
    obj.logid = logId
    sdata = bytes(internalExt, encoding="utf8")
    obj.payloadtype = sdata
    data = obj.SerializeToString()
    ws.send(data, websocket.ABNF.OPCODE_BINARY)
    # logging.info('[sendAck] [🌟发送Ack] [房间Id：' + liveRoomId + '] ====> 房间🏖标题【' + liveRoomTitle +'】')


def onError(ws, error):
    print("error", error)
    logging.error('[onError] [webSocket Error事件] [房间Id：' + liveRoomId + ']')


def onClose(ws, a, b):
    logging.info('[onClose] [webSocket Close事件] [房间Id：' + liveRoomId + ']')


def onOpen(ws):
    _thread.start_new_thread(ping, (ws,))
    logging.info('[onOpen] [webSocket Open事件] [房间Id：' + liveRoomId + ']')


# 发送ping心跳包
def ping(ws):
    while True:
        obj = message_pb2.PushFrame()
        obj.payloadtype = 'hb'
        data = obj.SerializeToString()
        ws.send(data, websocket.ABNF.OPCODE_BINARY)
        logging.info('[ping] [💗发送ping心跳] [房间Id：' + liveRoomId +
                     '] ====> 房间🏖标题【' + liveRoomTitle + '】')
        time.sleep(10)


def wssServerStart(roomId):
    global liveRoomId
    liveRoomId = roomId
    websocket.enableTrace(False)
    webSocketUrl = 'wss://webcast3-ws-web-lf.douyin.com/webcast/im/push/v2/?app_name=douyin_web&version_code=180800&webcast_sdk_version=1.3.0&update_version_code=1.3.0&compress=gzip&internal_ext=internal_src:dim|wss_push_room_id:' + liveRoomId + \
        '|wss_push_did:7139391558914393612|dim_log_id:2022113016104801020810207318AA8748|fetch_time:1669795848095|seq:1|wss_info:0-1669795848095-0-0|wrds_kvs:WebcastRoomStatsMessage-1669795848048115671_WebcastRoomRankMessage-1669795848064411370&cursor=t-1669795848095_r-1_d-1_u-1_h-1&host=https://live.douyin.com&aid=6383&live_id=1&did_rule=3&debug=false&endpoint=live_pc&support_wrds=1&im_path=/webcast/im/fetch/&device_platform=web&cookie_enabled=true&screen_width=1440&screen_height=900&browser_language=zh&browser_platform=MacIntel&browser_name=Mozilla&browser_version=5.0%20(Macintosh;%20Intel%20Mac%20OS%20X%2010_15_7)%20AppleWebKit/537.36%20(KHTML,%20like%20Gecko)%20Chrome/107.0.0.0%20Safari/537.36&browser_online=true&tz_name=Asia/Shanghai&identity=audience&room_id=' + liveRoomId + '&heartbeatDuration=0'
    h = {
        'Cookie': 'ttwid=' + ttwid,
    }
    # 创建一个长连接
    ws = websocket.WebSocketApp(
        webSocketUrl, on_message=onMessage, on_error=onError, on_close=onClose,
        on_open=onOpen,
        header=h
    )
    ws.run_forever()


def parseLiveRoomUrl(url):
    h = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36',
        'cookie': '__ac_nonce=0638733a400869171be51',
    }
    res = requests.get(url=url, headers=h)
    global ttwid, roomStore, liveRoomId, liveRoomTitle
    data = res.cookies.get_dict()
    ttwid = data['ttwid']
    res = res.text
    res = re.search(
        r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', res)
    res = res.group(1)
    res = urllib.parse.unquote(res, encoding='utf-8', errors='replace')
    res = json.loads(res)
    roomStore = res['app']['initialState']['roomStore']
    liveRoomId = roomStore['roomInfo']['roomId']
    liveRoomTitle = roomStore['roomInfo']['room']['title']
    wssServerStart(liveRoomId)
