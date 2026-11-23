# DSH Memory Pipeline

[English](README_EN.md) | 简体中文

[![Release v0.1.1](https://img.shields.io/github/v/release/wangzimu2007/dsh-memory-pipeline?include_prereleases&label=release)](https://github.com/wangzimu2007/dsh-memory-pipeline/releases)

给 DeepSeek Harness (DSH) 用的分级记忆处理管线：先用小模型，严格校验，只有失败才升级。

默认路径：

Q4 → 9B → 27B → Strata → 云端

处理两类任务：

- 事实抽取：把证据分段变成结构化事实。
- 写前验收：判断候选事实应该 pass、revise、drop 还是 hold。

它不是完整记忆数据库，只负责产出经过校验的 JSON；存储和检索由你的记忆后端负责。

## 为什么分级

Q4 足够快、足够省，大多数条目不需要大模型。只有 Q4 输出没有通过硬校验时，才升级。

每一级都必须通过：

- JSON 可解析
- 字段完整
- 证据 ID 真实存在
- 事实类型合法
- 判定合法
- revise 有非空 replacement
- drop / hold 没有 replacement
- pass / revise 有证据

Q4 失败后允许自修复一次；仍失败才进入下一级。

## 显存与卸载

本地模型默认不常驻。

- 某一级失败后，先卸载该级，再进入下一级。
- 整批结束后，本次调用过的 Q4/9B/27B 全部卸载。
- 加载下一级前检查可用显存。
- 显存不够就每 10 秒轮询，最多等 30 分钟。
- 不会关闭游戏或其他模型，只会等待；超时后跳过该级。

## 从指定层级开始

```bash
python memory_pipeline.py --cases examples/cases.example.json --start q4
python memory_pipeline.py --cases examples/cases.example.json --start 9b
python memory_pipeline.py --cases examples/cases.example.json --start 27b
python memory_pipeline.py --cases examples/cases.example.json --start strata
python memory_pipeline.py --cases examples/cases.example.json --start cloud
```

指定层级之前的模型不会运行。

## 安装

1. 安装 Ollama 和对应模型。
2. 下载记忆模型的提示词与 Modelfile：
   - https://github.com/lifdjgfndgn/qwen3.5-4b-memory-v2
   - https://huggingface.co/IMLIULIAN/qwen3.5-4b-memory-v2
3. 放到 vendor/qwen3.5-4b-memory-v2-main，或修改配置里的 prompts_dir。
4. 复制 pipeline.config.example.json 为 pipeline.config.json。
5. 按本机情况修改模型名和接口地址。

提示词合同来自 Qwen3.5-4B-Memory-V2 项目，遵循 Apache-2.0；本仓库不重新分发模型权重。

## 云端层

云端层是 OpenAI 兼容适配器。

需要设置：

- MEMORY_CLOUD_BASE_URL
- MEMORY_CLOUD_MODEL
- DEEPSEEK_API_KEY 或配置里指定的 Key 环境变量

没有 Key 时，云端层会标记为 skipped。

DSH 账号路由（例如 deepseek-account/deepseek-flash）只能在已登录的 DSH 会话内使用，外部进程无法直接调用；要么使用 API Key，要么把管线做成 DSH 插件。

## 显式记忆桥接

remember_explicit.py 处理用户明确说“记住”的强记忆：

```bash
python remember_explicit.py --text "..." --scope global
```

它会把文本送进分级校验链，只有通过才生成本地正式记录。它本身不写 Hindsight；调用方可以再通过 MCP 记忆服务落库。

## 与 dsh-long-memory 的关系

dsh-long-memory 是较软的自动记忆路径：每轮对话结束后自动提炼，并在新会话注入摘要，适合日常偏好、项目约定和踩坑。

本管线是较强的显式路径：用户授权、严格 schema、分级升级、结果可审计。

建议优先级：

- 用户明确“记住”的强记忆最高
- 自动建议经确认后可以提升
- 自动建议不能覆盖显式记忆

## 文件

- memory_pipeline.py：层级路由、模型适配、校验、显存等待和卸载
- remember_explicit.py：显式记忆桥接
- pipeline.config.example.json：配置模板
- examples/cases.example.json：纯合成示例
- tests/：校验器单元测试

## 测试

```bash
python -m unittest discover -s tests
```

## 许可证

MIT，见 LICENSE。

提示词与模型权重归原项目所有，本仓库不重新分发。
