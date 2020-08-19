# 请使用Python3

import socket
from urllib import request
from urllib.error import HTTPError
import zlib
import json
import threading
import struct
import time

# 来自直播间player-loader.js
WS_OP_HEARTBEAT = 2
WS_OP_HEARTBEAT_REPLY = 3
WS_OP_MESSAGE = 5
WS_OP_USER_AUTHENTICATION = 7
WS_OP_CONNECT_SUCCESS = 8
WS_PACKAGE_HEADER_TOTAL_LENGTH = 16
WS_PACKAGE_OFFSET = 0
WS_HEADER_OFFSET = 4
WS_VERSION_OFFSET = 6
WS_OPERATION_OFFSET = 8
WS_SEQUENCE_OFFSET = 12
WS_BODY_PROTOCOL_VERSION_NORMAL = 0
WS_BODY_PROTOCOL_VERSION_DEFLATE = 2
WS_HEADER_DEFAULT_VERSION = 1
WS_HEADER_DEFAULT_OPERATION = 1
WS_HEADER_DEFAULT_SEQUENCE = 1
WS_AUTH_OK = 0
WS_AUTH_TOKEN_ERROR = -101

# Packet Header 16 Bytes (WS_PACKAGE_HEADER_TOTAL_LENGTH)
# |- WS_PACKAGE_OFFSET 0: "Packet Length 数据包长度" 4 Bytes
# |- WS_HEADER_OFFSET 4: "Header Length 数据头长度" 2 Bytes
# |- WS_VERSION_OFFSET 6: "Protocol Version 协议版本" 2 Bytes
# |- WS_OPERATION_OFFSET 8: "Operation 数据动作" 4 Bytes
# |- WS_SEQUENCE_OFFSET 12: "Sequence Id 片段ID" 4 Bytes

def packet_encode(packet):
    return struct.pack('!IHHII',
        packet['packetLen'],
        packet['headerLen'],
        packet['ver'],
        packet['op'],
        packet['seq']) + packet['body']

def packets_decode(binary): # 一个binary可能包含多条弹幕信息
    packets = []
    begin = WS_PACKAGE_OFFSET
    while begin < len(binary):
        packet = {}
        header = struct.unpack('!IHHII', binary[begin : begin + WS_PACKAGE_HEADER_TOTAL_LENGTH])
        packet['packetLen'] = header[0]
        packet['headerLen'] = header[1] # 始终等于WS_PACKAGE_HEADER_TOTAL_LENGTH
        packet['ver'] = header[2]
        packet['op'] = header[3]
        packet['seq'] = header[4]
        packet['body'] = binary[begin + packet['headerLen'] : begin + packet['packetLen']]
        packets.append(packet)
        begin += packet['packetLen']
    return packets

# 这个弹幕机原本是使用WebSocket写的
# 因为直播间的JavaScript就辣么写的，所以就像抄作业一样直接抄了一遍
# 但是，大人，时代它变回去了
# 既然我们能直接使用既简单又方便的Socket，为啥又要多此一举在中间加一层WebSocket呢？
# Py的WebSocket客户端模块还是第三方的，让我本来就不富裕的硬盘空间更加雪上加霜（话说也没多大）

# 第一次搁py里写class，想想有点小激动
class DanmukuSocket:

    def __init__(self, url, port):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.connect((url, port))

    def recvPackets(self): # 记住这个结尾的s，我测试少了一堆弹幕就是这个s坑的，甚至一度怀疑是WebSocket的锅= =
        data0 = self.s.recv(4, socket.MSG_WAITALL)
        packetLen = struct.unpack('!I', data0)[0]
        data1 = self.s.recv(packetLen - 4, socket.MSG_WAITALL)
        binary = data0 + data1
        packets = packets_decode(binary)
        ret_packets = []
        for packet in packets:
            if packet['ver'] == WS_BODY_PROTOCOL_VERSION_DEFLATE:
                for packetunzip in packets_decode(zlib.decompress(packet['body'], 47, 16384)): # 其实我并不懂这俩参数有啥用，反正B站这么写的就抄了
                    ret_packets.append(packetunzip) # 解压可能拆出多个包
            else:
                ret_packets.append(packet) # 从流中读取数据包始终只读取1个
        return ret_packets

    def sendPacket(self, text, op):
        packet = {}
        packet['packetLen'] = WS_PACKAGE_HEADER_TOTAL_LENGTH + len(text)
        packet['headerLen'] = WS_PACKAGE_HEADER_TOTAL_LENGTH
        packet['ver'] = WS_HEADER_DEFAULT_VERSION
        packet['op'] = op
        packet['seq'] = WS_HEADER_DEFAULT_SEQUENCE
        packet['body'] = text.encode('utf-8')
        self.s.sendall(packet_encode(packet))

    def userAuth(self, roomid, token):
        auth = {}
        auth['uid'] = 0
        auth['roomid'] = roomid
        auth['protover'] = 2
        auth['platform'] = 'pc_link'
        auth['key'] = token
        self.sendPacket(json.dumps(auth, separators=(',', ':')), WS_OP_USER_AUTHENTICATION)

def heartbeat(danmakuSocket):
    while True:
        danmakuSocket.sendPacket('', WS_OP_HEARTBEAT)
        time.sleep(30.0)

room = input('请输入房间号：')
header = [
    ('User-Agent' , 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.120 Safari/537.36'),
    ('Accept' , '*/*')
]
handler = request.HTTPHandler()
opener = request.build_opener(handler)
opener.addheaders = header
request.install_opener(opener)

print('正在分析情报...')

# 获取roomid
roominfo = request.urlopen('https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom?room_id=' + room).read().decode('utf-8')
roominfo = json.loads(roominfo)
roomid = roominfo['data']['room_info']['room_id']
uid = roominfo['data']['room_info']['uid'] # 确认弹幕发送者是否为主播

print('目前可公开的情报：\n 目标识别码：%d\n 目标对外公开名称：%s - %s' % (roomid, roominfo['data']['room_info']['title'], roominfo['data']['anchor_info']['base_info']['uname']))

conf = request.urlopen('https://api.live.bilibili.com/room/v1/Danmu/getConf?room_id=%d&platform=pc_link' % roomid).read().decode('utf-8') # pc_link是官方弹幕姬的platform，好像这个参数怎么填都行不影响的
conf = json.loads(conf)

danmakuUrl = conf['data']['host_server_list'][0]['host']
danmakuPort = conf['data']['host_server_list'][0]['port']
danmakuToken = conf['data']['token']

print('连接至四次元量子通信隧道...')

danmakuSocket = DanmukuSocket(danmakuUrl, danmakuPort)
print('已成功建立隧道连接')
print('开始数据降维定向...')
danmakuSocket.userAuth(roomid, danmakuToken)
while True:
    packets = danmakuSocket.recvPackets() # 暂时懒得解决阻塞问题，Ctrl+C全靠心跳包或新弹幕来中断
    for packet in packets:
        if packet['op'] == WS_OP_CONNECT_SUCCESS: # 因为是USERAUTH之后才会回应的包，也许应该叫认证成功？
            ret = json.loads(packet['body'])
            if (ret['code'] == WS_AUTH_OK):
                print('定向成功，开始获取弹幕数据')
                thread = threading.Thread(target=heartbeat, args=[danmakuSocket])
                thread.setDaemon(True)
                thread.start()
            else:
                print('定向失败！')
                exit()
        elif packet['op'] == WS_OP_HEARTBEAT_REPLY: # 心跳包回应，同时返回人气值（直播间是setTimeout线性插值的所以变化快，实际上都是30秒一更新）
            print('当前房间人气：' + str(struct.unpack('!I',packet['body'])[0]))
        elif packet['op'] == WS_OP_MESSAGE:
            danmaku = json.loads(packet['body'])
            if danmaku['cmd'] == 'DANMU_MSG': # 弹幕
                # info[0][2] 弹幕大小
                # info[0][3] 弹幕颜色
                # info[1] 弹幕
                # info[2][0] 用户UID
                # info[2][1] 用户名
                # info[2][2] 房管
                # info[2][3] 老爷
                # info[2][4] 年费老爷
                # info[3] 无勋章此数组为空
                # info[3][0] 粉丝勋章等级
                # info[3][1] 粉丝勋章名称
                # info[3][2] 粉丝勋章所属主播
                # info[3][3] 勋章主播房间号
                # info[4][0] UL
                # info[7] 1总督 2提督 3舰长
                admin = ''
                guard = ''
                vip = ''
                medal = ''
                ul = '[UL %d]' % danmaku['info'][4][0]
                uname = danmaku['info'][2][1]
                danmu = danmaku['info'][1]
                if danmaku['info'][2][0] == uid:
                    admin = '[主播]'
                elif danmaku['info'][2][2] == 1:
                    admin = '[房管]'
                if danmaku['info'][7] == 1:
                    guard = '[总督]'
                elif danmaku['info'][7] == 2:
                    guard = '[提督]'
                elif danmaku['info'][7] == 3:
                    guard = '[舰长]'
                if danmaku['info'][2][3] == 1:
                    if danmaku['info'][2][4] == 1:
                        vip = '[年费老爷]'
                    else:
                        vip = '[老爷]'
                if len(danmaku['info'][3]) > 0:
                    medal = '[%s %d]' % (danmaku['info'][3][1], danmaku['info'][3][0])
                print(guard + vip + admin + medal + ul + uname + '：' + danmu)
            elif danmaku['cmd'] == 'SEND_GIFT': # 送礼（开始连击会有combo_send和batch_combo_send字段）
                uname = danmaku['data']['uname']
                giftname = danmaku['data']['giftName']
                giftaction = danmaku['data']['action']
                giftnum = danmaku['data']['num']
                giftcost = danmaku['data']['total_coin']
                gifttype = ''
                if danmaku['data']['coin_type'] == 'silver':
                    gifttype = '银瓜子'
                else:
                    gifttype = '金瓜子'
                danmu = '%s %s%s x%d (%d%s)' % (uname, giftaction, giftname, giftnum, giftcost, gifttype)
                print(danmu)
            elif danmaku['cmd'] == 'COMBO_SEND': # 送礼连击（不会取代SEND_GIFT事件）
                pass
            elif danmaku['cmd'] == 'COMBO_END': # 连击结束
                pass
            elif danmaku['cmd'] == 'GUARD_BUY': # 上舰，依然能用
                uname = danmaku['data']['username']
                guard = danmaku['data']['gift_name']
                print('欢迎' + uname + '上舰成为' + guard)
            elif danmaku['cmd'] == 'GUARD_MSG': # 也是上舰消息
                pass
                # print(danmaku['msg']) # :?XXXXXX:? 在本房间开通了舰长
            elif danmaku['cmd'] == 'USER_TOAST_MSG': # 同样是上舰信息，但是提示了是续费还是新上舰
                pass
                # print(danmaku['data']['toast_msg']) # <%XXXXXX%>续费了主播的舰长
            elif danmaku['cmd'] == 'GUARD_LOTTERY_START': # 似乎是上舰抽奖
                pass
                # print(danmaku['data']['lottery']['thank_text']) # 恭喜<%XXXXXX%>上任舰长
            elif danmaku['cmd'] == 'ROOM_REAL_TIME_MESSAGE_UPDATE': # 粉丝数更新
                pass
            elif danmaku['cmd'] == 'WELCOME': # 房管老爷进入直播间
                prefix = ''
                uname = ' [' + danmaku['data']['uname'] + '] '
                if danmaku['data']['is_admin']:
                    prefix = '房管'
                elif danmaku['data']['vip'] == 1:
                    if danmaku['data']['svip'] == 1:
                        prefix = '年费老爷'
                    else:
                        prefix = '老爷'
                print(prefix + uname + '进入直播间')
            elif danmaku['cmd'] == 'WELCOME_GUARD': # 欢迎舰长进入直播间
                guard = ''
                uname = ' [' + danmaku['data']['username'] + '] '
                if danmaku['data']['guard_level'] == 1:
                    guard = '总督'
                elif danmaku['data']['guard_level'] == 2:
                    guard = '提督'
                elif danmaku['data']['guard_level'] == 3:
                    guard = '舰长'
                print('欢迎' + guard + uname + '进入直播间')
            elif danmaku['cmd'] == 'ENTRY_EFFECT': # 也是欢迎舰长的进入房间的好像，但原本的还能用
                pass
                # print(danmaku['data']['copy_writing']) # 欢迎舰 长 <%XXXXXX%> 进入直播间
            elif danmaku['cmd'] == 'NOTICE_MSG': # 其他房间消息（谁谁谁打赏一个小电视快来抽奖balabalabalabala）
                pass
            elif danmaku['cmd'] == 'ROOM_RANK': # 房间啥啥榜排名
                print('房间排名已到达：' + danmaku['data']['rank_desc'])
            elif danmaku['cmd'] == 'ACTIVITY_BANNER_UPDATE_V2': # 房间啥啥榜排名，没有用文字写是哪个榜单，但提供的背景png里有说
                pass
            elif danmaku['cmd'] == 'SUPER_CHAT_MESSAGE': # VTB区专用醒目留言（并不是YTB的SuperChat笑），还有颜色啥的字段，懒得写了
                admin = ''
                guard = ''
                vip = ''
                medal = ''
                ul = '[UL %d]' % danmaku['data']['user_info']['user_level']
                uname = danmaku['data']['user_info']['uname']
                danmu = danmaku['data']['message']
                # if danmaku['data']['trans_mark'] == 1:
                    # danmu = danmu + ' (' + danmaku['data']['message_trans'] + ')' # 如果发送时选择了中译日这里会有翻译
                if danmaku['data']['uid'] == uid:
                    admin = '[主播]'
                elif danmaku['data']['user_info']['manager'] == 1:
                    admin = '[房管]'
                if danmaku['data']['user_info']['guard_level'] == 1:
                    guard = '[总督]'
                elif danmaku['data']['user_info']['guard_level'] == 2:
                    guard = '[提督]'
                elif danmaku['data']['user_info']['guard_level'] == 3:
                    guard = '[舰长]'
                if danmaku['data']['user_info']['is_vip'] == 1:
                    if danmaku['data']['user_info']['is_svip'] == 1:
                        vip = '[年费老爷]'
                    else:
                        vip = '[老爷]'
                price = 'RMB￥%d' % danmaku['data']['price']
                # sctime = '%d分钟' % (round(danmaku['data']['time'] / 60.0)) # 因为有延迟，秒数总是对不上，所以四舍五入至分（总不能延迟半分钟才出来）
                sctime = '%d分钟' % ((danmaku['data']['end_time'] - danmaku['data']['start_time']) / 60.0) # 现在不会有秒数对不上的问题了
                print('=============醒目留言=============')
                print(' 来自 ' + guard + vip + admin + medal + ul + uname + ' 的醒目留言（' + price + '，' + sctime + '）')
                if danmaku['data']['trans_mark'] == 1:
                    print(' ' + danmaku['data']['message_trans'])
                print(' ' + danmu)
                print('==================================')
            elif danmaku['cmd'] == 'SUPER_CHAT_MESSAGE_JPN': # 日区专用SUPERCHAT，会把所有SUPER_CHAT内容翻译成日语，不论是否选择中译日（但是好像有会重复发送的bug？应该可以根据id更新已经显示的SC）
                # admin = ''
                # guard = ''
                # vip = ''
                # medal = ''
                # ul = '[UL %d]' % danmaku['data']['user_info']['user_level']
                # uname = danmaku['data']['user_info']['uname']
                # danmu = danmaku['data']['message']
                # danmu_jpn = danmaku['data']['message_jpn']
                # if danmaku['data']['uid'] == uid:
                #     admin = '[主播]'
                # elif danmaku['data']['user_info']['manager'] == 1:
                #     admin = '[房管]'
                # if danmaku['data']['user_info']['guard_level'] == 1:
                #     guard = '[总督]'
                # elif danmaku['data']['user_info']['guard_level'] == 2:
                #     guard = '[提督]'
                # elif danmaku['data']['user_info']['guard_level'] == 3:
                #     guard = '[舰长]'
                # if danmaku['data']['user_info']['is_vip'] == 1:
                #     if danmaku['data']['user_info']['is_svip'] == 1:
                #         vip = '[年费老爷]'
                #     else:
                #         vip = '[老爷]'
                # price = '%d円' % (danmaku['data']['price'] * 15.7257) # 获取下实时汇率比较好……
                # # sctime = '%d分' % (round(danmaku['data']['time'] / 60.0))
                # sctime = '%d分' % ((danmaku['data']['end_time'] - danmaku['data']['start_time']) / 60.0) # 现在不会有秒数对不上的问题了
                # print('=============SUPER CHAT=============')
                # print(' 来自 ' + guard + vip + admin + medal + ul + uname + ' 的SUPER CHAT（' + price + '，' + sctime + '）')
                # print(' ' + danmu_jpn)
                # print(' ' + danmu)
                # print('====================================')
                pass
            elif danmaku['cmd'] == 'SUPER_CHAT_MESSAGE_DELETE': # 翻JS代码找到的，看起来是删除已显示的SC的
                pass
            elif danmaku['cmd'] == 'SUPER_CHAT_ENTRANCE': # 不晓得干啥的
                pass
            elif danmaku['cmd'] == 'ROOM_SILENT_ON': # 禁言开启
                # {'cmd': 'ROOM_SILENT_ON', 'data': {'type': 'level', 'level': 1, 'second': -1}}
                pass
            elif danmaku['cmd'] == 'ROOM_SLIENT_OFF': # 禁言关闭
                pass
            elif danmaku['cmd'] == 'WISH_BOTTLE': # 主播许愿瓶
                pass
            elif danmaku['cmd'] == 'WARNING': # 超管警告
            # (function(t) {
            #     return U(this, void 0, void 0, a.a.mark(function e() {
            #         return a.a.wrap(function(e) {
            #             for (; ; )
            #                 switch (e.prev = e.next) {
            #                 case 0:
            #                     u.store.getters.baseInfoUser.isAnchor ? (n = t.msg,
            #                     Object(f.b)({
            #                         title: "友情提示",
            #                         width: 300,
            #                         button: {
            #                             confirm: "知道了",
            #                             cancel: !1
            #                         },
            #                         content: n,
            #                         hideMask: !0
            #                     })) : D(t.msg);
            #                 case 2:
            #                 case "end":
            #                     return e.stop()
            #                 }
            #             var n
            #         }, e, this)
            #     }))
            # }
            # )(t).catch(d.noop);
                print('!!!!!!!!!!超管警告!!!!!!!!!!')
                print(danmaku['msg'])
                print('!!!!!!!!!!超管警告!!!!!!!!!!')
            elif danmaku['cmd'] == 'CUT_OFF': # 超管切断直播
            # (function(t) {
            #     return m(this, void 0, void 0, a.a.mark(function t() {
            #         var e, r, i;
            #         return a.a.wrap(function(t) {
            #             for (; ; )
            #                 switch (t.prev = t.next) {
            #                 case 0:
            #                     return e = u.store.getters.baseInfoUser.isAnchor,
            #                     t.next = 3,
            #                     Object(v.b)();
            #                 case 3:
            #                     if (p(),
            #                     !e) {
            #                         t.next = 13;
            #                         break
            #                     }
            #                     return t.next = 7,
            #                     n.e(9).then(n.bind(null, 2147));
            #                 case 7:
            #                     return r = t.sent,
            #                     i = r.loadCutOffMsg,
            #                     t.next = 11,
            #                     i();
            #                 case 11:
            #                     t.next = 14;
            #                     break;
            #                 case 13:
            #                     Object(f.b)({
            #                         title: "系统通知",
            #                         content: "当前直播间被直播管理员切断直播。",
            #                         width: 300,
            #                         button: {
            #                             confirm: "悲痛欲绝 " + l.randomEmoji.sad(),
            #                             cancel: !1
            #                         }
            #                     });
            #                 case 14:
            #                 case "end":
            #                     return t.stop()
            #                 }
            #         }, t, this)
            #     }))
            # }
            # )().catch(d.noop);
                print('直播推流已被超管切断。')
            elif danmaku['cmd'] == 'ROOM_LOCK': # 直播间被锁定
                print('直播间已被系统关闭并锁定，请联系客服。')
            elif danmaku['cmd'] == 'INTERACT_WORD': # 每十分钟全站重置所有用户的进入提示，这十分钟内同一用户重复进出同一直播间是不会重复提示的，重置时即使用户未离开直播间，重置后在直播间页面刷新也会出现新的提示
                print(f'{danmaku["data"]["uname"]} 进入了直播间')
            else: # 更新用
                print(danmaku)
                pass
        else: # 更新用
            print(packet)
