# ITIL 练题系统

## 项目简介
一个基于 Flask 的 ITIL 4 Foundation 练题 Web 应用，支持：
- 随机抽题练习（默认 40 题）
- 提交后即时评分与答案对照
- 错题/正确题统计
- AI 题目解释（异步预生成 + 结果页展示）
- 历史统计页（按题号/正确数/错误数等排序）

## 主要能力
1. **题库管理**：使用 SQLite 存储题库（默认 203 题）
2. **考试流程**：抽题 → 作答 → 提交 → 评分 → 解析
3. **AI 解释**：对题目生成白话解释；答错时重点解释误选原因
4. **统计分析**：累计每道题的正确/错误/未作答次数

## 目录结构

```text
itil/
├─ app.py
├─ itil_questions_store.db
├─ exam_stats.db
├─ static/
│  └─ style.css
├─ templates/
│  ├─ quiz.html
│  ├─ result.html
│  └─ stats.html
├─ ITIL 4 Foundation中文考试模拟题（203题）.pdf
└─ README.md
```

## 环境要求
- Python 3.10+
- Flask

可选安装（若未安装 Flask）：

```bash
pip install flask
```

## 启动方式

在仓库根目录执行：

```bash
python3 itil/app.py
```

默认监听：
- Host: `127.0.0.1`
- Port: `5000`

访问：<http://127.0.0.1:5000>

## 页面与接口
- `/`：答题页面
- `/submit`：提交试卷并返回结果页
- `/stats`：统计页面
- `/api/exam/<exam_id>/ai-status`：AI 解析生成进度查询

## 配置项（环境变量）
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `DEEPSEEK_TIMEOUT_SECONDS`
- `AI_PREFETCH_WORKERS`
- `EXAM_CACHE_TTL_SECONDS`

## 注意事项
1. 当前项目内含本地数据库与题库 PDF，仓库体积较大属正常。
2. 建议把 API Key 放在环境变量中，不要写死在代码里。
3. 题库重建逻辑在代码中保留但默认关闭；运行阶段不自动重建题库。
