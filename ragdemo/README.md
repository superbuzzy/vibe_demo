# RAG Demo（DeepSeek + Chroma + FastAPI）

一个面向中文文档问答的 RAG 示例项目：
- 支持上传 `PDF / DOCX / DOC`
- 自动切分并写入 Chroma 向量库
- 支持 `semantic / bm25 / hybrid` 三种检索模式
- 基于 DeepSeek 生成答案并返回引用片段

---

## 1. 项目结构

```text
ragdemo/
├── app/
│   ├── main.py          # FastAPI 入口（上传、问答、健康检查）
│   ├── ingest.py        # 文档加载/切分（含 doc 转换兜底）
│   ├── rag.py           # 检索与生成逻辑（semantic/bm25/hybrid）
│   ├── vectorstore.py   # Embedding 与 Chroma 封装
│   ├── config.py        # 环境变量与路径配置
│   ├── schemas.py       # API 请求/响应模型
│   ├── prompts.py       # 系统提示词
│   └── static/index.html
├── scripts/
│   ├── start.sh         # 启动后端（6006）
│   └── start-ui.sh      # 启动静态前端（6008）
├── data/                # 运行时目录（默认不提交）
├── requirements.txt
├── Dockerfile
├── compose.yaml
└── .env.example
```

---

## 2. 功能说明

### 2.1 文档上传与索引
- 接口：`POST /upload`
- 支持多文件上传
- 自动过滤不支持后缀
- 使用 `.ingested.json` 记录文件签名，避免重复向量化
- 后台 watcher 定期扫描 `data/uploads`，自动增量索引

### 2.2 检索模式
- `semantic`：纯向量语义检索
- `bm25`：关键词检索
- `hybrid`：语义 + BM25 交错去重融合（默认）

### 2.3 问答
- 接口：`POST /query`
- 输入：问题（可选 `top_k`）
- 输出：答案 + 引用来源（文件名、页码、片段）

---

## 3. 快速启动（本地）

> 以下命令以 Linux/macOS shell 为例（WSL 同理）。

### 3.1 安装依赖

```bash
cd ragdemo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3.2 配置环境变量

```bash
cp .env.example .env
```

至少需要设置：

```env
DEEPSEEK_API_KEY=your_real_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

### 3.3 启动后端（6006）

```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

### 3.4 启动前端静态页面（6008）

新开一个终端：

```bash
source .venv/bin/activate
chmod +x scripts/start-ui.sh
./scripts/start-ui.sh
```

浏览器访问：
- 前端：<http://localhost:6008>
- 后端健康检查：<http://localhost:6006/health>

---

## 4. API 使用示例

### 4.1 上传文档

```bash
curl -X POST http://localhost:6006/upload \
  -F "files=@/path/to/a.pdf" \
  -F "files=@/path/to/b.docx"
```

返回示例：

```json
{
  "files": ["xxx_a.pdf", "xxx_b.docx"],
  "docs_loaded": 12,
  "chunks_indexed": 86,
  "skipped": []
}
```

### 4.2 发起问答

```bash
curl -X POST http://localhost:6006/query \
  -H "Content-Type: application/json" \
  -d '{"question":"故障抢修到场后的安全措施有哪些？","top_k":4}'
```

返回示例：

```json
{
  "answer": "...",
  "sources": [
    {
      "source": "某业务指导书.doc",
      "page": 3,
      "snippet": "..."
    }
  ]
}
```

---

## 5. 核心配置项

配置文件：`.env`（可参考 `.env.example`）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 空 |
| `DEEPSEEK_BASE_URL` | DeepSeek Base URL | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 模型名 | `deepseek-chat` |
| `DEEPSEEK_TEMPERATURE` | 生成温度 | `0.2` |
| `EMBEDDING_MODEL_NAME` | 向量模型 | `BAAI/bge-small-zh-v1.5` |
| `EMBEDDING_DEVICE` | 向量设备 | `cpu` |
| `RETRIEVAL_MODE` | 检索模式 | `hybrid` |
| `BM25_TOP_K` | BM25 召回条数 | `4` |
| `TOP_K` | 语义检索条数 | `4` |
| `CHUNK_SIZE` | 文本切分大小 | `800` |
| `CHUNK_OVERLAP` | 切分重叠 | `150` |
| `APP_TITLE` | 服务名 | `RAG Demo` |
| `UPLOAD_WATCH_INTERVAL` | 上传目录扫描间隔(秒) | `5` |

---

## 6. Docker 运行（可选）

### 6.1 构建镜像

```bash
docker build -t ragdemo-api:0.1 .
```

### 6.2 启动服务

```bash
docker compose up -d
```

> 注意：`compose.yaml` 里当前挂载路径是 `/home/ubuntu/demo/ragdemo/data`，请按你的机器路径修改。

---

## 7. 常见问题

### Q1: 上传 `.doc` 失败
- 项目会优先调用 LibreOffice 把 `.doc` 转 `.docx`
- 若无 LibreOffice，会尝试 `antiword`
- 请安装其一：

```bash
sudo apt-get update
sudo apt-get install -y libreoffice
# 或
sudo apt-get install -y antiword
```

### Q2: 返回“未配置可用的大模型”
- 检查 `DEEPSEEK_API_KEY` 是否正确加载
- 确认启动服务前已 `source .env` 或脚本已自动加载 `.env`

### Q3: 检索结果不稳定
- 调整 `CHUNK_SIZE / CHUNK_OVERLAP`
- 尝试 `RETRIEVAL_MODE=hybrid`
- 调整 `TOP_K` 与 `BM25_TOP_K`

---

## 8. 安全与提交建议

- 不要把真实 API Key 提交到仓库
- 运行时数据目录建议忽略：
  - `data/uploads/`
  - `data/chroma/`
- 生产环境请增加鉴权、限流、审计日志

---

## 9. License

当前仓库未声明开源许可证；如需开源，请补充 `LICENSE` 文件。
