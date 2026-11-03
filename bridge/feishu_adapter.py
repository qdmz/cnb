#!/usr/bin/env python3
"""
feishu_adapter: 飞书通道适配器（chat-bridge v3 多通道架构）

参考 https://github.com/caichengle666/omp-feishu-lark 的核心思路：
飞书 bot 用 WebSocket 长连接主动向外连飞书服务器收消息，无需公网 IP/入站端口，
非常适合沙盒环境。

工作流：
  收：飞书 WebSocket (im.message.receive_v1)
      → POST {BRIDGE_URL}/api/channel/incoming {channel:"feishu", channel_ctx, text}
  发：轮询 {BRIDGE_URL}/api/agent/outbox?channel=feishu&after=<cursor>
      → 经飞书 API 发到对应 chat → 推进游标

配置（环境变量）：
  FEISHU_APP_ID      飞书开放平台应用的 App ID
  FEISHU_APP_SECRET  飞书开放平台应用的 App Secret
  BRIDGE_URL         bridge.py 地址，如 http://127.0.0.1:8090
  BRIDGE_TOKEN       与 bridge.py 相同的 bearer token
  FEISHU_DOMAIN      默认 https://open.feishu.cn（Lark 用 https://open.larksuite.com）

飞书应用需开通权限：im:message（接收消息）、im:message:send_as_bot（发消息），
事件订阅选"使用长连接接收事件"。

依赖：pip install lark-oapi（建议 venv）
"""

import json
import logging
import os
import sys
import threading
import time
import urllib.request

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [feishu] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

APP_ID = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8090").rstrip("/")
BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "")
DOMAIN = os.environ.get("FEISHU_DOMAIN", "https://open.feishu.cn")

CHANNEL = "feishu"
CURSOR_FILE = "/home/hatch/.config/chat-bridge/feishu-cursor"
POLL_INTERVAL = 3

_seen_msg_ids = set()


def bridge_api(method, path, body=None):
    req = urllib.request.Request(
        BRIDGE_URL + path,
        data=json.dumps(body).encode() if body else None,
        method=method,
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def load_cursor():
    try:
        return int(open(CURSOR_FILE).read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def save_cursor(n):
    with open(CURSOR_FILE, "w") as f:
        f.write(str(n))


def extract_text(msg):
    """从飞书消息事件提纯文本（只处理 text 类型）"""
    try:
        if (msg.message_type or "") != "text":
            return None
        content = json.loads(msg.content or "{}")
        text = (content.get("text") or "").strip()
        # 去掉 @bot 的 mention 残留
        return text or None
    except Exception:
        return None


MEDIA_DIR = "/home/hatch/workspace/chat-bridge/feishu-media"
os.makedirs(MEDIA_DIR, exist_ok=True)


def feishu_download_media(api_client, message_id, file_key, msg_type):
    """下载飞书图片/文件到本地，返回本地路径"""
    try:
        from lark_oapi.api.im.v1 import GetMessageResourceRequest
        req = GetMessageResourceRequest.builder() \
            .message_id(message_id).file_key(file_key).type(msg_type).build()
        resp = api_client.im.v1.message_resource.get(req)
        if not resp.success():
            log.warning("下载媒体失败: %s %s", resp.code, resp.msg)
            return None
        data = resp.file.read() if hasattr(resp, "file") else None
        if not data:
            return None
        ext = "jpg" if msg_type == "image" else "bin"
        path = os.path.join(MEDIA_DIR, f"{message_id}.{ext}")
        with open(path, "wb") as f:
            f.write(data)
        log.info("媒体已下载: %s (%d bytes)", path, len(data))
        return path
    except Exception as e:
        log.warning("下载媒体异常: %s", e)
        return None


def extract_media(msg):
    """提取图片/文件消息的 file_key"""
    try:
        mt = msg.message_type or ""
        if mt not in ("image", "file"):
            return None, None
        content = json.loads(msg.content or "{}")
        file_key = content.get("image_key") or content.get("file_key") or ""
        return (mt, file_key) if file_key else (None, None)
    except Exception:
        return None, None


def on_feishu_message(event, api_client=None):
    """im.message.receive_v1 回调（lark-oapi 收到的是 P2ImMessageReceiveV1 对象）"""
    log.info("收到飞书事件回调，开始处理")
    try:
        data = event.event
        msg = data.message
        msg_id = msg.message_id or ""
        if msg_id in _seen_msg_ids:
            return
        _seen_msg_ids.add(msg_id)
        if len(_seen_msg_ids) > 1000:
            _seen_msg_ids.clear()

        # 只处理发给 bot 的私聊，或群里 @bot 的消息
        # （私聊 chat_type=p2p；群聊需 mention 才处理）
        if (msg.chat_type or "") != "p2p" and not (msg.mentions or []):
            return

        text = extract_text(msg)
        media_path = None
        # 图片/文件消息：下载到本地
        mt, file_key = extract_media(msg)
        if mt and file_key and api_client:
            media_path = feishu_download_media(api_client, msg_id, file_key, mt)
            if not text:
                text = f"[{ '图片' if mt == 'image' else '文件' }]"
        if not text:
            return

        open_id = ""
        sender = data.sender
        if sender is not None and sender.sender_id is not None:
            open_id = sender.sender_id.open_id or ""
        ctx = {
            "chat_id": msg.chat_id or "",
            "open_id": open_id,
            "msg_id": msg_id,
        }
        body = {"channel": CHANNEL, "channel_ctx": ctx, "text": text}
        if media_path:
            body["media_path"] = media_path
            body["media_type"] = mt
        r = bridge_api("POST", "/api/channel/incoming", body)
        log.info("收到飞书消息 id=%s 已入桥: %s", r.get("id"), text[:40])
    except Exception as e:
        log.exception("处理飞书消息失败: %s", e)


def feishu_send_text(client, chat_id, text):
    """经飞书 API 发文本消息（超长截断）"""
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest, CreateMessageRequestBody)
    # 飞书文本消息上限约 150KB，这里保守截断
    body = CreateMessageRequestBody.builder() \
        .receive_id(chat_id).msg_type("text") \
        .content(json.dumps({"text": text[:30000]},
                            ensure_ascii=False)).build()
    req = CreateMessageRequest.builder() \
        .receive_id_type("chat_id").request_body(body).build()
    resp = client.im.v1.message.create(req)
    if not resp.success():
        log.warning("飞书发送失败: %s %s", resp.code, resp.msg)
        return False
    return True


def feishu_send_image(client, chat_id, image_path):
    """上传图片并发送"""
    try:
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest, CreateMessageRequestBody,
            CreateImageRequest, CreateImageRequestBody)
        with open(image_path, "rb") as f:
            # 上传图片（SDK 要求传文件对象 IO，不能传 bytes；上传必须在文件关闭前完成）
            up_body = CreateImageRequestBody.builder() \
                .image_type("message").image(f).build()
            up_req = CreateImageRequest.builder().request_body(up_body).build()
            up_resp = client.im.v1.image.create(up_req)
        if not up_resp.success():
            log.warning("飞书图片上传失败: %s %s", up_resp.code, up_resp.msg)
            return False
        image_key = up_resp.data.image_key
        # 发送图片消息
        body = CreateMessageRequestBody.builder() \
            .receive_id(chat_id).msg_type("image") \
            .content(json.dumps({"image_key": image_key})).build()
        req = CreateMessageRequest.builder() \
            .receive_id_type("chat_id").request_body(body).build()
        resp = client.im.v1.message.create(req)
        return resp.success()
    except Exception as e:
        log.warning("飞书图片发送异常: %s", e)
        return False


def outbox_loop(client):
    """轮询 bridge 取本渠道回复，发回飞书"""
    cursor = load_cursor()
    while True:
        try:
            r = bridge_api(
                "GET", f"/api/agent/outbox?channel={CHANNEL}&after={cursor}")
            for m in r.get("messages", []):
                ctx = m.get("channel_ctx") or {}
                chat_id = ctx.get("chat_id", "")
                if not chat_id:
                    log.warning("回复 id=%s 无 chat_id，跳过", m["id"])
                else:
                    # 如果回复带图片，先发图片再发文字
                    media_path = (m.get("channel_ctx") or {}).get("media_path", "")
                    if media_path and os.path.exists(media_path):
                        feishu_send_image(client, chat_id, media_path)
                    if m.get("text"):
                        feishu_send_text(client, chat_id, m["text"])
                    log.info("已发回飞书 id=%s chat=%s",
                             m["id"], chat_id[:12])
                cursor = max(cursor, m["id"])
            save_cursor(cursor)
        except Exception as e:
            log.warning("outbox 轮询失败: %s", e)
        time.sleep(POLL_INTERVAL)


def main():
    if not APP_ID or not APP_SECRET:
        log.error("必须设置 FEISHU_APP_ID / FEISHU_APP_SECRET")
        sys.exit(1)
    if not BRIDGE_TOKEN:
        log.error("必须设置 BRIDGE_TOKEN")
        sys.exit(1)

    import lark_oapi as lark
    from lark_oapi.ws import Client as WsClient
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

    # 沙盒必须走 egress 代理：SDK 默认 ws 直连（proxy=None），这里 patch 让它走代理
    import lark_oapi.ws.client as _ws_client_mod
    _proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") \
        or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
    if _proxy_url:
        _ws_client_mod._ws_connect_kwargs = lambda: {"proxy": _proxy_url}
        log.info("WebSocket 将经代理连接")

    # API client（发消息用）
    api_client = lark.Client.builder() \
        .app_id(APP_ID).app_secret(APP_SECRET).domain(DOMAIN) \
        .log_level(lark.LogLevel.WARNING).build()

    # 事件分发（lark-oapi 1.7.3：用 builder 注册，回调用的是 P2ImMessageReceiveV1）
    # 用闭包把 api_client 传给 handler（用于下载图片/文件）
    def _on_msg(event):
        return on_feishu_message(event, api_client)
    handler = EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(_on_msg) \
        .build()

    # outbox 发送线程
    t = threading.Thread(target=outbox_loop, args=(api_client,),
                         daemon=True)
    t.start()

    # WebSocket 长连接（阻塞）
    log.info("启动飞书 WebSocket 长连接…")
    ws = WsClient(APP_ID, APP_SECRET, event_handler=handler,
                  domain=DOMAIN,
                  log_level=lark.LogLevel.WARNING)
    ws.start()


if __name__ == "__main__":
    main()
