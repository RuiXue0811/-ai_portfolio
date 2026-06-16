# 初级管理模拟器

> 一款基于 AI 对话的职场人际关系训练工具。通过「情局卡」系统，帮助用户识别人际局面中的潜在风险、解读他人动机，并提供不撕破脸的防身应对策略。



---

## 产品截图

聊天界面支持「抽卡」模式和自由问诊两种交互方式，左侧可查看历史对话与已完成的卡牌。

---

## 核心功能

### 情局卡系统（120 张）

| 卡组 | 核心能力 | 数量 |
|------|---------|------|
| 识局卡 | 识别试探与苗头 | 30 张 |
| 读人卡 | 判断对方动机与立场 | 30 张 |
| 防身卡 | 不撕破脸地保护自己 | 30 张 |
| 应对卡 | 具体行动建议与话术 | 30 张 |

**抽卡交互流程**：
1. 发送「抽卡」→ AI 展示情局卡场景
2. AI 通过苏格拉底式提问（最多 3 轮）引导用户自己分析
3. 用户回答不出来时，AI 直接给出策略分析
4. 满 3 轮自动收尾，给出综合建议

### 自由问诊

直接描述你遇到的职场/人际困境，AI 帮你识局、读人、推演应对策略。

---

## 技术架构

```
用户（飞书 / Web 浏览器）
        ↓
Flask 后端（bot.py，port 5000）
        ↓
Claude Haiku API
        ↓
cards.json（120 张情局卡数据）
```

- **后端**：Python + Flask，同时支持飞书 WebSocket 长连接和 Web 界面
- **前端**：纯 HTML/CSS/JS，无框架依赖，支持移动端
- **对话管理**：保留最近 20 条历史，卡牌交互有独立状态机
- **稳定性**：API 3 次自动重试 + 兜底回复，消息去重双保险

---

## 本地运行

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/mgmt-simulator.git
cd mgmt-simulator

# 2. 安装依赖
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key 和飞书凭据

# 4. 启动
python bot.py
# 浏览器打开 http://localhost:5000
```

**注意**：若只使用 Web 界面（不接飞书机器人），`FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 可以留空。

---

## 服务器部署

详见 [docs/腾讯云部署指南.md](docs/腾讯云部署指南.md)，使用 systemd 管理进程，支持开机自启与崩溃重启。

---

## 产品文档

- [PRD 产品需求文档](docs/人情世故助手-PRD.md) — 产品定位、功能设计、商业模式
- [AI Prompt 设计文档](docs/人情世故助手-AI-Prompt设计.md) — 苏格拉底式引导 + 军师式分析的 Prompt 架构
- [调试记录](docs/DEBUG_RECORD.md) — 开发过程中遇到的 8 个问题及修复方案

---

## 项目背景

这是我在学习 AI 运营落地过程中独立完成的 side project，从产品设计（PRD）到 Prompt 工程、后端开发、服务器部署全链路自己做。核心挑战：

- **内容设计**：120 张情局卡的场景撰写与清晰度审查
- **对话工程**：苏格拉底式引导 + 卡壳检测 + 轮次上限的状态机设计
- **稳定性**：Windows 编码问题、飞书消息去重、API 重试逻辑的调试排查
