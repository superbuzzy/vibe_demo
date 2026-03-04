# vibe_demo

这是一个用于存放 **OpenClaw Demo 项目** 的仓库。

你可以把它理解为一个「实验场」：
- 记录和展示我通过 OpenClaw 生成的小项目
- 保留每个 Demo 的可运行代码与说明
- 方便后续持续追加、复用和分享

---

## 项目目标

- 作为 OpenClaw 的实践样例集合
- 提供可直接运行的最小示例（MVP）
- 为后续扩展（功能增强、自动化流程、脚本模板）打基础

---

## Demo 索引表（模板）

> 每新增一个 Demo，按下表追加一行，方便快速检索。

| Demo 名称 | 目录/文件 | 类型 | 一句话说明 | 运行命令 | 状态 |
|---|---|---|---|---|---|
| Hello World（Python） | `hello/hello.py` | Python 脚本 | 输出 `Hello, World!` 的最小示例 | `python3 hello/hello.py` | ✅ 已完成 |
| ITIL 练题系统 | `itil/` | Python Web 应用 | ITIL 题库练习与统计（含题库与模板静态资源） | `python3 itil/app.py` | ✅ 已导入 |

---

## 当前 Demo

### 1) Hello World（Python）

位置：`hello/hello.py`

功能：
- 在终端输出 `Hello, World!`

运行方式：

```bash
python3 hello/hello.py
```

预期输出：

```text
Hello, World!
```

### 2) ITIL 练题系统

位置：`itil/`

功能：
- 提供 ITIL 题库练习相关应用（含页面模板与静态资源）
- 包含题库/统计数据库文件，支持本地练习与结果统计

运行方式（基础）：

```bash
python3 itil/app.py
```

---

## 仓库结构

```text
vibe_demo/
├─ README.md
├─ hello/
│  └─ hello.py
└─ itil/
   ├─ app.py
   ├─ templates/
   ├─ static/
   ├─ exam_stats.db
   └─ itil_questions_store.db
```

---

## 环境要求

- Python 3.8+（推荐 3.10 及以上）
- Linux / macOS / Windows 均可（在 WSL 中同样可运行）

可选检查：

```bash
python3 --version
```

---

## 后续规划（Planned）

后续会继续上传更多 OpenClaw 生成或协作完成的 Demo，例如：
- 基础脚本自动化
- 文件处理与文本生成
- API 调用示例
- 小型工具化项目（CLI / Web 小工具）

每个 Demo 会尽量包含：
- 功能说明
- 运行步骤
- 输入与输出示例

---

## 贡献方式

如果你想一起扩展示例：

1. Fork 本仓库
2. 新建分支（如 `feature/new-demo`）
3. 提交变更并发起 Pull Request

也欢迎提交 Issue 提建议：
- 想看的 Demo 类型
- 具体使用场景
- 期望的脚本模板

---

## License

可按需改为 MIT / Apache-2.0 等开源协议。
当前默认：**All rights reserved**（未显式授权前）。
