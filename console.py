import logging
import threading
import queue
import json
from live import Live

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox, simpledialog
except Exception:
    tk = None

import requests
from typing import Dict, Any
import paho.mqtt.client as mqtt
from jinja2 import Template
import io
from PIL import Image, ImageTk


class ConfigDialog:
    """配置对话框"""
    
    def __init__(self, parent, title, msg_type="", callback_type="", template=""):
        self.result = None
        
        # 创建对话框窗口
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("600x500")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中显示
        self.dialog.geometry("+%d+%d" % (parent.winfo_rootx() + 50, parent.winfo_rooty() + 50))
        
        self._build_dialog(msg_type, callback_type, template)
        
        # 等待对话框关闭
        self.dialog.wait_window()
    
    def _build_dialog(self, msg_type, callback_type, template):
        pad = {"padx": 10, "pady": 5}
        
        # 消息类型选择
        type_frame = ttk.Frame(self.dialog)
        type_frame.pack(fill=tk.X, **pad)
        ttk.Label(type_frame, text="消息类型:").pack(side=tk.LEFT)
        self.msg_type_var = tk.StringVar(value=msg_type)
        self.msg_type_combo = ttk.Combobox(type_frame, textvariable=self.msg_type_var, width=30)
        self.msg_type_combo['values'] = [
            'WebcastChatMessage', 'WebcastGiftMessage', 'WebcastLikeMessage', 
            'WebcastMemberMessage', 'WebcastSocialMessage', 'WebcastRoomUserSeqMessage',
            'WebcastFansclubMessage', 'WebcastControlMessage', 'WebcastEmojiChatMessage',
            'WebcastRoomStatsMessage', 'WebcastRoomMessage', 'WebcastRoomRankMessage',
            'WebcastRoomStreamAdaptationMessage'
        ]
        self.msg_type_combo.pack(side=tk.LEFT, padx=10)
        
        # 回调类型选择
        callback_frame = ttk.Frame(self.dialog)
        callback_frame.pack(fill=tk.X, **pad)
        ttk.Label(callback_frame, text="回调类型:").pack(side=tk.LEFT)
        self.callback_type_var = tk.StringVar(value=callback_type)
        callback_combo = ttk.Combobox(callback_frame, textvariable=self.callback_type_var, width=15)
        callback_combo['values'] = ['webhook', 'mqtt']
        callback_combo.pack(side=tk.LEFT, padx=10)
        
        # 模板配置区域
        template_frame = ttk.LabelFrame(self.dialog, text="Jinja2 模板配置")
        template_frame.pack(fill=tk.BOTH, expand=True, **pad)
        
        # 模板说明
        help_text = """Jinja2 模板语法说明:
- 使用 {{ 变量名 }} 来输出变量
- 使用 {% if 条件 %} ... {% endif %} 进行条件判断
- 使用 {% for 项 in 列表 %} ... {% endfor %} 进行循环
- 可用的数据变量: user, content, gift, count 等

示例模板:
{
  "message_type": "{{ method }}",
  "user_name": "{{ user.nickName }}",
  "content": "{{ content }}",
  "timestamp": "{{ now() }}"
}"""
        
        help_label = ttk.Label(template_frame, text=help_text, justify=tk.LEFT)
        help_label.pack(anchor=tk.W, padx=5, pady=5)
        
        # 模板输入框
        template_text_frame = ttk.Frame(template_frame)
        template_text_frame.pack(fill=tk.BOTH, expand=True, **pad)
        
        ttk.Label(template_text_frame, text="模板内容:").pack(anchor=tk.W)
        self.template_text = scrolledtext.ScrolledText(template_text_frame, wrap=tk.WORD, height=15)
        self.template_text.pack(fill=tk.BOTH, expand=True)
        self.template_text.insert(tk.END, template)
        
        # 按钮区域
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(fill=tk.X, **pad)
        
        ttk.Button(button_frame, text="确定", command=self._ok_clicked).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="取消", command=self._cancel_clicked).pack(side=tk.RIGHT)
    
    def _ok_clicked(self):
        msg_type = self.msg_type_var.get().strip()
        callback_type = self.callback_type_var.get().strip()
        template = self.template_text.get(1.0, tk.END).strip()
        
        if not msg_type or not callback_type or not template:
            messagebox.showwarning("提示", "请填写所有字段")
            return
        
        # 验证模板语法
        try:
            Template(template)
        except Exception as e:
            messagebox.showerror("错误", f"模板语法错误: {e}")
            return
        
        self.result = (msg_type, callback_type, template)
        self.dialog.destroy()
    
    def _cancel_clicked(self):
        self.dialog.destroy()


class ActionDispatcher:

    def __init__(self):
        self.configs: Dict[str, Dict[str, Any]] = {}  # 存储所有配置
        self._mqtt_clients: Dict[str, mqtt.Client] = {}
        self.mqtt_host = ""
        self.mqtt_port = 1883
        self.webhook_url = ""

    def set_global_mqtt(self, host: str, port: int = 1883):
        """设置全局MQTT服务器"""
        self.mqtt_host = host
        self.mqtt_port = port

    def set_global_webhook(self, url: str):
        """设置全局Webhook URL"""
        self.webhook_url = url

    def add_config(self, msg_type: str, callback_type: str, template: str):
        """添加消息类型配置"""
        self.configs[msg_type] = {
            "callback_type": callback_type,
            "template": template
        }

    def remove_config(self, msg_type: str):
        """移除配置"""
        if msg_type in self.configs:
            del self.configs[msg_type]

    def get_configs(self) -> Dict[str, Dict[str, Any]]:
        """获取所有配置"""
        return self.configs.copy()

    def _get_mqtt_client(self, host: str, port: int) -> mqtt.Client:
        key = f"{host}:{port}"
        client = self._mqtt_clients.get(key)
        if client is None:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            client.connect(host, port, 60)
            self._mqtt_clients[key] = client
        return client

    def _render_template(self, template_str: str, data: Dict[str, Any]) -> str:
        """使用Jinja2渲染模板"""
        try:
            template = Template(template_str)
            return template.render(data)
        except Exception as e:
            logging.error(f"模板渲染错误: {e}")
            return json.dumps(data, ensure_ascii=False)

    def handle(self, payload: Dict[str, Any]):
        method = payload.get("method")
        if not method:
            return

        # 检查是否有对应的配置
        config = self.configs.get(method)
        if not config:
            return

        callback_type = config["callback_type"]
        template = config["template"]
        data = payload.get("data", {})

        try:
            if callback_type == "webhook" and self.webhook_url:
                # 使用模板渲染数据
                rendered_data = self._render_template(template, data)
                # 发送到webhook
                requests.post(self.webhook_url, json=json.loads(rendered_data), timeout=3)
                
            elif callback_type == "mqtt" and self.mqtt_host:
                # 使用模板渲染数据
                rendered_data = self._render_template(template, data)
                # 发送到MQTT
                client = self._get_mqtt_client(self.mqtt_host, self.mqtt_port)
                # 从模板中提取topic，或者使用默认topic
                topic = data.get("topic", "douyin/live")
                client.publish(topic, rendered_data)
                
        except Exception as e:
            logging.error(f"处理消息 {method} 时出错: {e}")


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
        self._add_sample_configs()
        self._refresh_config_list()
        # 延迟启动消息轮询，确保UI完全初始化
        self.root.after(1000, self._poll_queue)

    def _build_ui(self):
        pad = {"padx": 6, "pady": 6}

        # 1. 直播地址区域
        live_frame = ttk.LabelFrame(self.root, text="直播地址")
        live_frame.pack(fill=tk.X, **pad)
        
        live_row = ttk.Frame(live_frame)
        live_row.pack(fill=tk.X, **pad)
        ttk.Label(live_row, text="直播地址:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar()
        ttk.Entry(live_row, textvariable=self.url_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.btn_start = ttk.Button(live_row, text="开始", command=self.start_live)
        self.btn_start.pack(side=tk.LEFT, padx=6)
        self.btn_stop = ttk.Button(live_row, text="停止", command=self.stop_live, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT)

        # 2. MQTT 地址配置
        mqtt_frame = ttk.LabelFrame(self.root, text="MQTT 地址配置")
        mqtt_frame.pack(fill=tk.X, **pad)
        
        mqtt_row = ttk.Frame(mqtt_frame)
        mqtt_row.pack(fill=tk.X, **pad)
        ttk.Label(mqtt_row, text="MQTT 服务器:").pack(side=tk.LEFT)
        self.mqtt_host = tk.StringVar()
        ttk.Entry(mqtt_row, textvariable=self.mqtt_host, width=20).pack(side=tk.LEFT, padx=6)
        ttk.Label(mqtt_row, text="端口:").pack(side=tk.LEFT)
        self.mqtt_port = tk.StringVar(value="1883")
        ttk.Entry(mqtt_row, textvariable=self.mqtt_port, width=8).pack(side=tk.LEFT, padx=6)
        ttk.Button(mqtt_row, text="测试连接", command=self._test_mqtt).pack(side=tk.LEFT, padx=6)

        # 3. Webhook 地址配置
        webhook_frame = ttk.LabelFrame(self.root, text="Webhook 地址配置")
        webhook_frame.pack(fill=tk.X, **pad)
        
        webhook_row = ttk.Frame(webhook_frame)
        webhook_row.pack(fill=tk.X, **pad)
        ttk.Label(webhook_row, text="Webhook URL:").pack(side=tk.LEFT)
        self.webhook_url = tk.StringVar()
        ttk.Entry(webhook_row, textvariable=self.webhook_url, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(webhook_row, text="测试连接", command=self._test_webhook).pack(side=tk.LEFT, padx=6)

        # 4. 消息类型配置表格
        config_frame = ttk.LabelFrame(self.root, text="消息类型配置")
        config_frame.pack(fill=tk.BOTH, expand=True, **pad)

        # 配置表格
        columns = ('消息类型', '回调类型', '参数配置 (Jinja语法)', '操作')
        self.config_tree = ttk.Treeview(config_frame, columns=columns, show='headings', height=12)
        
        for col in columns:
            self.config_tree.heading(col, text=col)
            if col == '消息类型':
                self.config_tree.column(col, width=180)
            elif col == '回调类型':
                self.config_tree.column(col, width=100)
            elif col == '参数配置 (Jinja语法)':
                self.config_tree.column(col, width=300)
            else:
                self.config_tree.column(col, width=100)
        
        # 添加滚动条
        config_scrollbar = ttk.Scrollbar(config_frame, orient=tk.VERTICAL, command=self.config_tree.yview)
        self.config_tree.configure(yscrollcommand=config_scrollbar.set)
        
        self.config_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        config_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 添加/编辑配置按钮
        config_btn_frame = ttk.Frame(config_frame)
        config_btn_frame.pack(fill=tk.X, **pad)
        ttk.Button(config_btn_frame, text="增加配置", command=self._add_config).pack(side=tk.LEFT, padx=2)
        ttk.Button(config_btn_frame, text="编辑配置", command=self._edit_config).pack(side=tk.LEFT, padx=2)
        ttk.Button(config_btn_frame, text="删除配置", command=self._delete_config).pack(side=tk.LEFT, padx=2)

        # 5. 消息显示区域和排行榜区域
        message_container = ttk.Frame(self.root)
        message_container.pack(fill=tk.BOTH, expand=True, **pad)
        
        # 消息日志区域
        log_frame = ttk.LabelFrame(message_container, text="直播间消息")
        log_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))
        
        # 消息控制按钮
        log_control = ttk.Frame(log_frame)
        log_control.pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(log_control, text="清空日志", command=self._clear_log).pack(side=tk.LEFT, padx=2)
        ttk.Button(log_control, text="暂停/继续", command=self._toggle_pause).pack(side=tk.LEFT, padx=2)
        self.pause_var = tk.BooleanVar()
        self.pause_check = ttk.Checkbutton(log_control, text="自动滚动", variable=self.pause_var)
        self.pause_check.pack(side=tk.LEFT, padx=2)
        self.pause_var.set(True)
        
        self.text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15)
        self.text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 排行榜区域
        rank_frame = ttk.LabelFrame(message_container, text="直播间排行榜")
        rank_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=(3, 0))
        rank_frame.configure(width=300)  # 固定宽度
        
        # 排行榜标题
        rank_title = ttk.Label(rank_frame, text="🏆 排行榜", font=("Arial", 12, "bold"))
        rank_title.pack(pady=5)
        
        # 排行榜列表
        self.rank_tree = ttk.Treeview(rank_frame, columns=('排名', '用户', '等级', '分数'), show='headings', height=20)
        self.rank_tree.heading('排名', text='排名')
        self.rank_tree.heading('用户', text='用户')
        self.rank_tree.heading('等级', text='等级')
        self.rank_tree.heading('分数', text='分数')
        
        self.rank_tree.column('排名', width=50, anchor='center')
        self.rank_tree.column('用户', width=150)
        self.rank_tree.column('等级', width=60, anchor='center')
        self.rank_tree.column('分数', width=70, anchor='center')
        
        # 存储头像图片的字典
        self.avatar_images = {}
        
        # 添加滚动条
        rank_scrollbar = ttk.Scrollbar(rank_frame, orient=tk.VERTICAL, command=self.rank_tree.yview)
        self.rank_tree.configure(yscrollcommand=rank_scrollbar.set)
        
        self.rank_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        rank_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

    def _test_mqtt(self):
        """测试MQTT连接"""
        host = self.mqtt_host.get().strip()
        try:
            port = int(self.mqtt_port.get().strip() or "1883")
        except Exception:
            port = 1883
        
        if not host:
            messagebox.showwarning("提示", "请填写MQTT服务器地址")
            return
            
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            client.connect(host, port, 60)
            client.disconnect()
            self.dispatcher.set_global_mqtt(host, port)
            messagebox.showinfo("成功", f"MQTT连接测试成功: {host}:{port}")
        except Exception as e:
            messagebox.showerror("错误", f"MQTT连接失败: {e}")

    def _test_webhook(self):
        """测试Webhook连接"""
        url = self.webhook_url.get().strip()
        if not url:
            messagebox.showwarning("提示", "请填写Webhook URL")
            return
            
        try:
            response = requests.get(url, timeout=5)
            self.dispatcher.set_global_webhook(url)
            messagebox.showinfo("成功", f"Webhook连接测试成功: {url}")
        except Exception as e:
            messagebox.showerror("错误", f"Webhook连接失败: {e}")

    def _add_config(self):
        """添加配置"""
        dialog = ConfigDialog(self.root, "添加配置")
        if dialog.result:
            msg_type, callback_type, template = dialog.result
            self.dispatcher.add_config(msg_type, callback_type, template)
            self._refresh_config_list()
            messagebox.showinfo("成功", f"已添加配置: {msg_type}")

    def _edit_config(self):
        """编辑配置"""
        selection = self.config_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请选择要编辑的配置")
            return
        
        item = self.config_tree.item(selection[0])
        msg_type = item['values'][0]
        
        # 从配置中获取完整的模板
        configs = self.dispatcher.get_configs()
        if msg_type in configs:
            config = configs[msg_type]
            callback_type = config['callback_type']
            template = config['template']
        else:
            messagebox.showerror("错误", "配置不存在")
            return
        
        dialog = ConfigDialog(self.root, "编辑配置", msg_type, callback_type, template)
        if dialog.result:
            new_msg_type, new_callback_type, new_template = dialog.result
            # 如果消息类型改变了，先删除旧的
            if new_msg_type != msg_type:
                self.dispatcher.remove_config(msg_type)
            self.dispatcher.add_config(new_msg_type, new_callback_type, new_template)
            self._refresh_config_list()
            messagebox.showinfo("成功", f"已更新配置: {new_msg_type}")

    def _delete_config(self):
        """删除配置"""
        selection = self.config_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请选择要删除的配置")
            return
        
        item = self.config_tree.item(selection[0])
        msg_type = item['values'][0]
        
        if messagebox.askyesno("确认", f"确定要删除配置 {msg_type} 吗？"):
            self.dispatcher.remove_config(msg_type)
            self._refresh_config_list()
            messagebox.showinfo("成功", f"已删除配置: {msg_type}")

    def _refresh_config_list(self):
        """刷新配置列表"""
        # 清空现有项目
        for item in self.config_tree.get_children():
            self.config_tree.delete(item)
        
        # 添加配置项目
        configs = self.dispatcher.get_configs()
        for msg_type, config in configs.items():
            self.config_tree.insert('', 'end', values=(
                msg_type,
                config['callback_type'],
                config['template'][:50] + "..." if len(config['template']) > 50 else config['template'],
                "编辑/删除"
            ))

    def _clear_log(self):
        """清空消息日志"""
        self.text.delete(1.0, tk.END)

    def _toggle_pause(self):
        """切换暂停/继续状态"""
        # 这里可以添加暂停逻辑，暂时只是占位
        pass

    def _handle_live_callback(self, payload: dict):
        # UI 线程外回调，放入队列
        self.msg_queue.put(payload)
        # 分发动作
        self.dispatcher.handle(payload)

    def _poll_queue(self):
        try:
            while True:
                payload = self.msg_queue.get_nowait()
                self._display_message(payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_queue)

    def _display_message(self, payload: dict):
        """格式化显示消息"""
        method = payload.get("method", "Unknown")
        data = payload.get("data", {})
        
        # 排行榜消息不显示在消息框中，而是显示在排行榜区域
        if method == "WebcastRoomRankMessage":
            self._update_rank_display(data)
            return
        
        # 根据消息类型格式化显示
        if method == "WebcastChatMessage":
            user = data.get("user", {})
            user_name = user.get("nickName", "未知用户")
            content = data.get("content", "")
            timestamp = self._get_timestamp()
            display_text = f"[{timestamp}] 💬 聊天: {user_name}: {content}\n"
            
        elif method == "WebcastGiftMessage":
            user = data.get("user", {})
            user_name = user.get("nickName", "未知用户")
            gift = data.get("gift", {})
            gift_name = gift.get("name", "未知礼物")
            combo_count = data.get("combo_count", 1)
            timestamp = self._get_timestamp()
            display_text = f"[{timestamp}] 🎁 礼物: {user_name} 送出了 {gift_name} x{combo_count}\n"
            
        elif method == "WebcastLikeMessage":

            user = data.get("user", {})
            user_name = user.get("nickName", "未知用户")
            count = data.get("count", 1)
            timestamp = self._get_timestamp()
            display_text = f"[{timestamp}] 👍 点赞: {user_name} 点了 {count} 个赞\n"
            
        elif method == "WebcastMemberMessage":
            user = data.get("user", {})
            user_name = user.get("nickName", "未知用户")
            user_id = user.get("id", "未知ID")
            gender = "男" if user.get("gender") == 1 else "女"
            timestamp = self._get_timestamp()
            display_text = f"[{timestamp}] 🚪 进场: [{user_id}][{gender}]{user_name} 进入了直播间\n"
            
        elif method == "WebcastSocialMessage":
            user = data.get("user", {})
            user_name = user.get("nickName", "未知用户")
            user_id = user.get("id", "未知ID")
            timestamp = self._get_timestamp()
            display_text = f"[{timestamp}] ❤️ 关注: [{user_id}]{user_name} 关注了主播\n"
            
        elif method == "WebcastRoomUserSeqMessage":
            current = data.get("total", 0)
            total = data.get("total_pv_for_anchor", 0)
            timestamp = self._get_timestamp()
            display_text = f"[{timestamp}] 📊 统计: 当前观看人数: {current}, 累计观看人数: {total}\n"
            
        elif method == "WebcastFansclubMessage":
            content = data.get("content", "")
            timestamp = self._get_timestamp()
            display_text = f"[{timestamp}] 🏆 粉丝团: {content}\n"
            
        elif method == "WebcastControlMessage":
            status = data.get("status", 0)
            timestamp = self._get_timestamp()
            if status == 3:
                display_text = f"[{timestamp}] ⏹️ 控制: 直播间已结束\n"
            else:
                display_text = f"[{timestamp}] ⚙️ 控制: 状态码 {status}\n"
                
        elif method == "WebcastRoomStatsMessage":
            display_long = data.get("display_long", "")
            timestamp = self._get_timestamp()
            display_text = f"[{timestamp}] 📈 统计: {display_long}\n"
            
        else:
            # 其他消息类型显示原始JSON
            timestamp = self._get_timestamp()
            display_text = f"[{timestamp}] {method}: {json.dumps(data, ensure_ascii=False)}\n"
        
        # 插入到文本框
        self.text.insert(tk.END, display_text)
        
        # 如果启用了自动滚动，则滚动到底部
        if self.pause_var.get():
            self.text.see(tk.END)

    def _get_timestamp(self):
        """获取当前时间戳"""
        import datetime
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _update_rank_display(self, data: dict):
        """更新排行榜显示"""
        try:
            ranks_list = data.get("ranksList", [])
            if not ranks_list:
                return
            
            # 只显示前10名
            ranks_list = ranks_list[:10]
            
            # 清空现有排行榜
            for item in self.rank_tree.get_children():
                self.rank_tree.delete(item)
            
            # 添加排行榜数据
            for i, rank_data in enumerate(ranks_list, 1):
                user = rank_data.get("user", {})
                user_name = user.get("nickName", "未知用户")
                score_str = rank_data.get("scoreStr", "0")
                
                # 获取用户等级
                pay_grade = user.get("payGrade", {})
                level = pay_grade.get("level", 0)
                level_text = f"Lv.{level}" if level > 0 else "Lv.0"
                
                # 获取头像URL
                avatar_thumb = user.get("avatarThumb", {})
                avatar_urls = avatar_thumb.get("urlListList", [])
                avatar_url = avatar_urls[0] if avatar_urls else ""
                
                # 添加排名图标
                if i == 1:
                    rank_icon = "🥇"
                elif i == 2:
                    rank_icon = "🥈"
                elif i == 3:
                    rank_icon = "🥉"
                else:
                    rank_icon = f"{i}"
                
                # 处理头像显示
                user_display = user_name
                if avatar_url:
                    # 异步下载头像
                    self._load_avatar_async(avatar_url, user_name, i)
                    user_display = f"🖼️ {user_name}"
                else:
                    user_display = f"👤 {user_name}"
                
                self.rank_tree.insert('', 'end', values=(
                    rank_icon,
                    user_display,
                    level_text,
                    score_str
                ))
                
        except Exception as e:
            print(f"更新排行榜显示错误: {e}")

    def _load_avatar_async(self, avatar_url: str, user_name: str, rank: int):
        """异步加载头像"""
        def load_avatar():
            try:
                response = requests.get(avatar_url, timeout=5)
                if response.status_code == 200:
                    # 创建图片对象
                    img = Image.open(io.BytesIO(response.content))
                    # 调整图片大小为30x30
                    img = img.resize((30, 30), Image.Resampling.LANCZOS)
                    # 转换为PhotoImage
                    photo = ImageTk.PhotoImage(img)
                    
                    # 存储图片引用
                    self.avatar_images[f"{user_name}_{rank}"] = photo
                    
                    # 更新UI（需要在主线程中执行）
                    self.root.after(0, lambda: self._update_avatar_display(user_name, rank, photo))
                    
            except Exception as e:
                print(f"加载头像失败 {user_name}: {e}")
        
        # 在后台线程中下载头像
        import threading
        thread = threading.Thread(target=load_avatar, daemon=True)
        thread.start()

    def _update_avatar_display(self, user_name: str, rank: int, photo):
        """更新头像显示"""
        try:
            # 查找对应的排行榜项目并更新
            for item in self.rank_tree.get_children():
                values = self.rank_tree.item(item, 'values')
                if len(values) >= 2 and user_name in values[1]:
                    # 更新显示文本，添加头像
                    new_values = list(values)
                    new_values[1] = f"🖼️ {user_name}"
                    self.rank_tree.item(item, values=new_values)
                    break
        except Exception as e:
            print(f"更新头像显示错误: {e}")

    def _add_sample_configs(self):
        """添加示例配置"""
        # 聊天消息配置示例
        chat_template = """{
  "message_type": "{{ method }}",
  "user_name": "{{ user.nickName }}",
  "user_id": "{{ user.id }}",
  "content": "{{ content }}",
  "timestamp": "{{ now() }}"
}"""
        self.dispatcher.add_config("WebcastChatMessage", "webhook", chat_template)
        
        # 礼物消息配置示例
        gift_template = """{
  "message_type": "{{ method }}",
  "user_name": "{{ user.nickName }}",
  "gift_name": "{{ gift.name }}",
  "gift_count": "{{ combo_count }}",
  "timestamp": "{{ now() }}"
}"""
        self.dispatcher.add_config("WebcastGiftMessage", "mqtt", gift_template)

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


