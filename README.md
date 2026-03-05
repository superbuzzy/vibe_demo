# vibe_demo

OpenClaw 项目演示仓库（一个项目一个文件夹）。

这个仓库用于沉淀可运行、可复用、可继续迭代的 Demo 项目，方便快速查看与二次开发。

---

## 项目索引

| 项目 | 目录 | 类型 | 简介 | 状态 |
|---|---|---|---|---|
| Hello World | `hello/` | Python 脚本 | 最小示例：输出 `Hello, World!` | ✅ |
| ITIL 练题系统 | `itil/` | Python Web 应用 | ITIL 题库练习与统计 | ✅ |
| RAG Demo | `ragdemo/` | FastAPI + Chroma + DeepSeek | 文档上传、向量检索与问答（支持 PDF/DOCX/DOC） | ✅ |

---

## 快速运行

### 1) Hello World

```bash
python3 hello/hello.py
```

### 2) ITIL 练题系统

```bash
python3 itil/app.py
```

### 3) RAG Demo

详细说明见：`ragdemo/README.md`

基础启动（Linux/WSL）：

```bash
cd ragdemo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
./scripts/start.sh
```

前端静态页（新开终端）：

```bash
cd ragdemo
source .venv/bin/activate
./scripts/start-ui.sh
```

访问：
- API 健康检查：`http://localhost:6006/health`
- 前端页面：`http://localhost:6008`

---

## 仓库结构（当前）

```text
vibe_demo/
├─ README.md
├─ hello/
├─ itil/
└─ ragdemo/
```

---

## 说明

- 每个项目目录都应包含自己的 `README.md`。
- 严禁在仓库中提交个人/系统文件（如 memory、skills、USER.md 等）。
- 敏感配置（API Key）仅放在本地 `.env`，不得提交。

---

## License

当前未单独声明开源许可证，默认：**All rights reserved**。
如需开源，请补充 `LICENSE` 文件。