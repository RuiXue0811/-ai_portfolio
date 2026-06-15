import sys
import io
import logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 修复 logging 模块的编码问题：重建 root logger 的 handler，使用 utf-8
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
logging.basicConfig(
    level=logging.WARNING,
    format='[%(name)s] %(levelname)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

import json
import random
import os
import time
import threading
import requests
import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, UpdateMessageRequest, UpdateMessageRequestBody
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()

flask_app = Flask(__name__)

@flask_app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

conversations = {}
user_card_history = {}  # 记录每个用户已经抽过的卡片
processed_msg_ids = set()  # 消息去重，防止飞书重复推送
last_msg_time = {}  # 用户上次消息时间，防连点/重复推送
user_card_state = {}  # 抽卡交互状态：{user_id: {"card": card_dict, "rounds": int}}

# 加载卡片库
CARDS_PATH = os.path.join(os.path.dirname(__file__), "cards.json")
with open(CARDS_PATH, encoding="utf-8") as f:
    CARDS = json.load(f)

SYSTEM_PROMPT = """【当前对话场景】
这是一场职场人际关系的分析讨论。用户正在向你咨询一个涉及职场政治、人际博弈的现实问题。你的任务是帮助用户理清局面，看清各方动机，推演不同应对策略的后果。

【回复要求】
- 每次只问一个引导性问题，帮用户自己看清局面
- 回复控制在 200 字以内
- 冷静、理性，像阅历丰富的导师
- 直接开始分析，不要开场白，不要提"作为AI"

【绝对禁止】
- 不要提你是 Claude 或任何 AI 模型
- 不要说"这不是我的专长"之类的话
- 直接进入分析，不要解释你能做什么或不能做什么"""

# 检测模型是否拒绝了角色扮演（返回了开发者身份或拒绝声明）
REJECTION_KEYWORDS = ["claude", "anthropic", "development environment", "不是我的专长",
                       "软件开发", "AI开发", "编码助手", "代码开发"]

# 用户卡壳关键词：匹配到则跳过引导，直接解释卡牌
# 注意：中文子串匹配，"不太懂" 不等于 "不懂"（"太"在中间），所以需要显式列出
DONT_KNOW_PATTERNS = ["不知道", "不懂", "不太懂", "没看懂", "没太懂",
                       "不明白", "不太明白", "不是很明白",
                       "不清楚", "不太清楚",
                       "很难说", "说不准", "怎么说呢",
                       "我想不出来", "想不出来", "这怎么说",
                       "看不懂", "看不太懂"]

# 直接解释卡牌时的系统提示词
EXPLAIN_SYSTEM_PROMPT = """【当前对话场景】
这是一场职场人际关系的分析讨论。用户抽了一张情局卡，但在引导提问中卡住了，无法回答。现在需要你直接分析这张卡牌。

【回复要求】
- 直接分析局面：点明关键矛盾和各方真实动机
- 给出2-3种可行的应对策略
- 简要分析每种策略的风险和收益
- 控制在300字以内
- 不要再提问，不要问"你觉得呢"

【绝对禁止】
- 不要提你是 Claude 或任何 AI 模型
- 不要问用户任何问题
- 不要以"我来分析一下"之类的开场白开头，直接进入分析"""

WELCOME_MSG = """我是初级管理模拟器，帮你模拟真实的管理困境。

发送「抽卡」体验今日情局卡，或直接描述你遇到的局面。"""


def draw_card(user_id):
    """随机抽一张用户没抽过的卡片，抽完一轮后重置"""
    if user_id not in user_card_history:
        user_card_history[user_id] = []
    seen = user_card_history[user_id]
    remaining = [c for c in CARDS if c["id"] not in seen]
    if not remaining:
        user_card_history[user_id] = []
        remaining = CARDS
    card = random.choice(remaining)
    user_card_history[user_id].append(card["id"])
    return card


def call_api(history, system_override=None):
    """调用 AI API，带重试逻辑"""
    system = system_override if system_override else SYSTEM_PROMPT
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{ANTHROPIC_BASE_URL}/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "system": system,
                    "messages": history
                },
                timeout=30
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]
            else:
                print(f"API returned {resp.status_code}: {resp.text[:100]}", flush=True)
                last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            print(f"API attempt {attempt+1} failed: {e}", flush=True)
            last_error = str(e)
            if attempt < 2:
                time.sleep(2)
    raise Exception(f"API call failed after 3 attempts: {last_error}")


def call_claude(user_id, user_message):
    if user_id not in conversations:
        conversations[user_id] = []

    msg = user_message.strip()

    # --- 抽卡指令：抽卡 / 换一张 ---
    if msg in ["抽卡", "今日卡片", "换一张"]:
        card = draw_card(user_id)
        card_text = f"🎴 {card['type']}卡·{card['title']}\n\n{card['scene']}\n\n---\n我先问你3个问题帮你理清思路，最后给你综合建议。\n**第一问：**这个局面里，你觉得对方真正想要的是什么？"
        conversations[user_id] = [
            {"role": "user", "content": "抽卡"},
            {"role": "assistant", "content": card_text}
        ]
        # 重置抽卡交互轮次
        user_card_state[user_id] = {"card": card, "rounds": 0}
        return card_text

    # --- 检查是否在抽卡交互中 ---
    card_state = user_card_state.get(user_id)
    if card_state is not None:
        card_state["rounds"] += 1
        rounds = card_state["rounds"]

        # 用户卡壳 OR 满 3 轮 → 直接解释卡牌
        is_stuck = any(kw in msg for kw in DONT_KNOW_PATTERNS)
        should_explain = is_stuck or rounds >= 3

        if should_explain:
            reason = "stuck" if is_stuck else "max_rounds"
            print(f"Card explain triggered: reason={reason}, rounds={rounds}, msg={msg[:30]}", flush=True)

            conversations[user_id].append({"role": "user", "content": user_message})
            history = conversations[user_id][-20:]

            try:
                reply = call_api(history, system_override=EXPLAIN_SYSTEM_PROMPT)
            except Exception as e:
                print(f"All API retries exhausted (explain): {e}", flush=True)
                # 兜底：用卡牌数据拼一个解释
                card = card_state["card"]
                reply = (
                    f"这张「{card['title']}」的关键在于：\n\n"
                    f"{card['scene']}\n\n"
                    f"面对这种情况，建议你：\n"
                    f"1. 先理清各方的真实诉求，不要急于表态\n"
                    f"2. 观察局势变化，等待合适的时机\n"
                    f"3. 沉默本身也是一种策略\n\n"
                    f"局势复杂时，最重要的不是做什么，而是看清什么。"
                )

            conversations[user_id].append({"role": "assistant", "content": reply})
            del user_card_state[user_id]
            return reply

    # --- 正常对话（无卡牌 或 卡牌交互中但未触发解释） ---
    conversations[user_id].append({"role": "user", "content": user_message})
    history = conversations[user_id][-20:]

    try:
        reply = call_api(history)
    except Exception as e:
        print(f"All API retries exhausted: {e}", flush=True)
        # 兜底回复，不要让用户干等
        reply = (
            "抱歉，我暂时无法连接到分析引擎。\n\n"
            "请稍后再试，或者你可以：\n"
            "• 发送「抽卡」查看今日情局卡（不需要联网）\n"
            "• 重新描述你的处境，我会再次尝试分析"
        )

    conversations[user_id].append({"role": "assistant", "content": reply})
    return reply


def send_message(client, receive_id, receive_id_type, text):
    """发送消息并返回 message_id，用于后续编辑"""
    request = CreateMessageRequest.builder() \
        .receive_id_type(receive_id_type) \
        .request_body(CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()) \
        .build()
    resp = client.im.v1.message.create(request)
    if resp.success and resp.data:
        return resp.data.message_id
    return None


def update_message(client, message_id, text):
    """编辑已发送的消息内容"""
    request = UpdateMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(UpdateMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()) \
        .build()
    client.im.v1.message.update(request)


def on_message(data) -> None:
    try:
        event = data.event
        msg = event.message

        # 消息去重：飞书可能重复推送同一消息
        msg_id = msg.message_id
        if msg_id in processed_msg_ids:
            return
        processed_msg_ids.add(msg_id)
        # 限制 set 大小，防止内存泄漏
        if len(processed_msg_ids) > 10000:
            processed_msg_ids.clear()

        if msg.message_type != "text":
            return

        sender_id = event.sender.sender_id
        user_id = sender_id.open_id
        chat_id = msg.chat_id
        chat_type = msg.chat_type

        content = json.loads(msg.content)
        text = content.get("text", "").strip()

        if not text:
            return

        print(f"Received: {text} from {user_id}", flush=True)

        # 防连点/重复推送：同一用户 2 秒内只处理第一条
        now = time.time()
        if user_id in last_msg_time and (now - last_msg_time[user_id]) < 2:
            print(f"Skipped duplicate from {user_id}", flush=True)
            return
        last_msg_time[user_id] = now

        # 创建飞书客户端
        client = lark.Client.builder() \
            .app_id(APP_ID) \
            .app_secret(APP_SECRET) \
            .build()

        receive_id = user_id if chat_type == "p2p" else chat_id
        receive_id_type = "open_id" if chat_type == "p2p" else "chat_id"

        # 第一步：立即回复"思考中..."，让用户知道 bot 在响应
        thinking_msg_id = send_message(client, receive_id, receive_id_type, "🤔 思考中...")
        if thinking_msg_id:
            print(f"Thinking msg sent: {thinking_msg_id}", flush=True)

        # 第二步：获取 AI 回复
        reply = call_claude(user_id, text)
        print(f"Reply: {reply[:50]}...", flush=True)

        # 第三步：把"思考中..."编辑成正式回复
        if thinking_msg_id:
            try:
                update_message(client, thinking_msg_id, reply)
                print("Reply updated!", flush=True)
            except Exception as e:
                print(f"Failed to update message, fallback to direct send: {e}", flush=True)
                send_message(client, receive_id, receive_id_type, reply)
        else:
            # 思考消息没发出去，直接发正式回复
            send_message(client, receive_id, receive_id_type, reply)
            print("Reply sent directly!", flush=True)
    except Exception as e:
        print(f"ERROR in on_message: {e}", flush=True)
        import traceback
        traceback.print_exc()


def main():
    ws_client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message)
            .build(),
        log_level=lark.LogLevel.INFO
    )

    # 飞书长连接在子线程运行，主线程跑Flask
    t = threading.Thread(target=ws_client.start, daemon=True)
    t.start()

    print("Web server starting on port 5000...", flush=True)
    flask_app.run(host="0.0.0.0", port=5000, debug=False)


@flask_app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    data = request.json
    session_id = data.get("session_id", "default")
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"reply": "请输入内容"})
    reply = call_claude(session_id, message)
    return jsonify({"reply": reply})


@flask_app.route("/", methods=["GET"])
def index():
    return send_from_directory('web', 'index.html')

@flask_app.route("/<path:filename>", methods=["GET"])
def serve_static(filename):
    return send_from_directory('web', filename)


if __name__ == "__main__":
    main()
