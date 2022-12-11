
# !/user/bin/env python
# -*- coding:utf-8 -*-

import socket

# 待bind的ip/port
ip_port = ('127.0.0.1', 9999)
# 建立socket
s = socket.socket()
# 绑定ip/port
s.bind(ip_port)
# 监听连接
s.listen()
print('等待用户连接中... ...')
while True:
    # 建立连接后，将accept()返回的元组赋值给conn, addr
    conn, addr = s.accept()
    if conn is not None:
        print('有一个用户已连接.\n等待对方发送信息.')
    while True:
        try:
            recv_data = conn.recv(1024)
            # 显示接收的信息
            print('对方发送的信息：', str(recv_data, encoding = 'utf-8'))
            # send_data = input('我回复>>').strip()
            # conn.send(bytes(send_data, encoding = 'utf-8'))
            # print('等待对方发送信息>>')
        except Exception as e:
            print('远程主机强迫关闭了一个现有的连接，续继等待其它的连接。')
            break
    conn.close()