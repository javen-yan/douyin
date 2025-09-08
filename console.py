import logging
import threading
import queue
import json
from live import Live

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox
except Exception:
    tk = None

import requests
from typing import Dict, Any
import paho.mqtt.client as mqtt


class ActionDispatcher:

    def __init__(self):
        self.webhook_map: Dict[str, str] = {}
        self.mqtt_map: Dict[str, Dict[str, Any]] = {}
        self._mqtt_clients: Dict[str, mqtt.Client] = {}

    def set_webhook(self, msg_type: str, url: str):
        self.webhook_map[msg_type] = url

    def set_mqtt(self, msg_type: str, host: str, topic: str, port: int = 1883):
        self.mqtt_map[msg_type] = {"host": host, "port": port, "topic": topic}

    def _get_mqtt_client(self, host: str, port: int) -> mqtt.Client:
        key = f"{host}:{port}"
        client = self._mqtt_clients.get(key)
        if client is None:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            client.connect(host, port, 60)
            self._mqtt_clients[key] = client
        return client

    def handle(self, payload: Dict[str, Any]):
        method = payload.get("method")
        if not method:
            return

        # webhook
        webhook_url = self.webhook_map.get(method)
        if webhook_url:
            try:
                requests.post(webhook_url, json=payload, timeout=3)
            except Exception:
                pass

        # mqtt
        mqtt_cfg = self.mqtt_map.get(method)
        if mqtt_cfg:
            try:
                client = self._get_mqtt_client(mqtt_cfg["host"], mqtt_cfg["port"])
                client.publish(mqtt_cfg["topic"], json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass


class LiveDesktopApp:

    def __init__(self):
        if tk is None:
            raise RuntimeError("Tkinter is not available in this environment")
        self.root = tk.Tk()
        self.root.title("Douyin Live Desktop")

        self.live: Live | None = None
        self.msg_queue: "queue.Queue[dict]" = queue.Queue()
        self.dispatcher = ActionDispatcher()

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        pad = {"padx": 6, "pady": 6}

        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, **pad)
        ttk.Label(top, text="直播地址:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.url_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.btn_start = ttk.Button(top, text="开始", command=self.start_live)
        self.btn_start.pack(side=tk.LEFT, padx=6)
        self.btn_stop = ttk.Button(top, text="停止", command=self.stop_live, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT)

        # actions config
        cfg = ttk.LabelFrame(self.root, text="消息动作配置（按消息类型）")
        cfg.pack(fill=tk.X, **pad)

        # webhook config
        webhook_row = ttk.Frame(cfg)
        webhook_row.pack(fill=tk.X, **pad)
        ttk.Label(webhook_row, text="消息类型").pack(side=tk.LEFT)
        self.webhook_type = tk.StringVar()
        ttk.Entry(webhook_row, textvariable=self.webhook_type, width=24).pack(side=tk.LEFT, padx=6)
        ttk.Label(webhook_row, text="Webhook URL").pack(side=tk.LEFT)
        self.webhook_url = tk.StringVar()
        ttk.Entry(webhook_row, textvariable=self.webhook_url, width=40).pack(side=tk.LEFT, padx=6)
        ttk.Button(webhook_row, text="设置Webhook", command=self._set_webhook).pack(side=tk.LEFT)

        # mqtt config
        mqtt_row = ttk.Frame(cfg)
        mqtt_row.pack(fill=tk.X, **pad)
        ttk.Label(mqtt_row, text="消息类型").pack(side=tk.LEFT)
        self.mqtt_type = tk.StringVar()
        ttk.Entry(mqtt_row, textvariable=self.mqtt_type, width=24).pack(side=tk.LEFT, padx=6)
        ttk.Label(mqtt_row, text="MQTT Host").pack(side=tk.LEFT)
        self.mqtt_host = tk.StringVar()
        ttk.Entry(mqtt_row, textvariable=self.mqtt_host, width=18).pack(side=tk.LEFT, padx=4)
        ttk.Label(mqtt_row, text="Port").pack(side=tk.LEFT)
        self.mqtt_port = tk.StringVar(value="1883")
        ttk.Entry(mqtt_row, textvariable=self.mqtt_port, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Label(mqtt_row, text="Topic").pack(side=tk.LEFT)
        self.mqtt_topic = tk.StringVar()
        ttk.Entry(mqtt_row, textvariable=self.mqtt_topic, width=24).pack(side=tk.LEFT, padx=4)
        ttk.Button(mqtt_row, text="设置MQTT", command=self._set_mqtt).pack(side=tk.LEFT)

        # message log
        log_frame = ttk.LabelFrame(self.root, text="消息日志")
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=20)
        self.text.pack(fill=tk.BOTH, expand=True)

    def _set_webhook(self):
        msg_type = self.webhook_type.get().strip()
        url = self.webhook_url.get().strip()
        if not msg_type or not url:
            messagebox.showwarning("提示", "请填写消息类型和Webhook URL")
            return
        self.dispatcher.set_webhook(msg_type, url)
        messagebox.showinfo("成功", f"Webhook已设置: {msg_type} -> {url}")

    def _set_mqtt(self):
        msg_type = self.mqtt_type.get().strip()
        host = self.mqtt_host.get().strip()
        topic = self.mqtt_topic.get().strip()
        if not msg_type or not host or not topic:
            messagebox.showwarning("提示", "请填写消息类型、MQTT Host 和 Topic")
            return
        try:
            port = int(self.mqtt_port.get().strip() or "1883")
        except Exception:
            port = 1883
        self.dispatcher.set_mqtt(msg_type, host, topic, port)
        messagebox.showinfo("成功", f"MQTT已设置: {msg_type} -> {host}:{port} {topic}")

    def _handle_live_callback(self, payload: dict):
        # UI 线程外回调，放入队列
        self.msg_queue.put(payload)
        # 分发动作
        self.dispatcher.handle(payload)

    def _poll_queue(self):
        try:
            while True:
                payload = self.msg_queue.get_nowait()
                line = json.dumps(payload, ensure_ascii=False)
                self.text.insert(tk.END, line + "\n")
                self.text.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_queue)

    def start_live(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请填写直播地址")
            return
        try:
            self.live = Live(url, callback_handler=self._handle_live_callback)
            t = threading.Thread(target=self.live.run_forever, daemon=True)
            t.start()
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("错误", f"启动失败: {e}")

    def stop_live(self):
        if self.live is not None:
            try:
                self.live.stop()
            except Exception:
                pass
            self.live = None
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)

    def run(self):
        self.root.mainloop()

if __name__ == '__main__':
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    if tk is None:
        raise RuntimeError("Tkinter不可用，无法启动桌面应用")
    ui = LiveDesktopApp()
    ui.run()


