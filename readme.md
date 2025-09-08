# Douyin 直播抓取

## 桌面应用

1. 安装依赖

```
pip install -r requirements.txt
```

2. 启动桌面应用

```
python console.py
```

3. 功能

- 直播地址输入，开始/停止
- 消息滚动日志（原始JSON）
- 针对不同消息类型配置 Webhook 或 MQTT 发布

## API

### 创建直播间


> POST /api/v1/worker

#### 参数
| 参数       | 类型 | 说明 | 示例                |
|----------| --- | --- |-------------------|
| live_url | string | 直播间地址 | https://xxxxx/123 |
|socket_addr| string | socket地址 | 127.0.0.1:9999    |


#### 返回值

| 参数       | 类型 | 说明 | 示例                |
|----------| --- | --- |-------------------|
| code | int | 状态码 | 0 |
| msg| string | 信息 | success    |
|data|object|数据|{}|

#### 示例

```json
{
    "code": 0,
    "data": {
        "id": "aee2409d52114dbfb2181fc5b38db796"
    },
    "msg": "create worker success"
}
```


### 获取直播间信息

> GET /api/v1/worker

#### 参数
| 参数  | 类型 | 说明   | 示例   |
|-----| --- |------|------|
| id  | string | 任务ID | xxxx |


#### 示例

```json
{
    "code": 0,
    "data": {
        "id": "46093cca1ba34b6baa26af125c0dc619",
        "push_did": "7175783639312877067",
        "room_id": "7175756973630376759",
        "room_title": "山海经：开局一个小龙，长大全靠吞噬！弱肉强食的世界！#游戏"
    },
    "msg": "get worker success"
}
```



### 释放房间任务

> DELETE /api/v1/worker

#### 参数
| 参数  | 类型 | 说明   | 示例   |
|-----| --- |------|------|
| id  | string | 任务ID | xxxx |


#### 示例

```json
{
    "code": 0,
    "msg": "delete worker success"
}
```