# 模型与 TTS 接入调研和维护说明

核对日期：2026-10-16。范围仅为模型连接、声音复刻与播放链路，沿用既有项目结构。

## 接口规范与可复现参考

| 服务 | 接入规范 | 本项目处理 |
| --- | --- | --- |
| DeepSeek 官方 OpenAI 协议 | Base URL 为 `https://api.deepseek.com`，调用 `/chat/completions`，Bearer 密钥；用 `/models` 读取账号可见 ID。 | 使用已有 OpenAI SDK 的独立适配器处理流式文本、工具参数拼接与完整结束；不自动重试付费请求。 |
| DeepSeek 官方 Anthropic 协议 | Base URL 为 `https://api.deepseek.com/anthropic`，调用 `/v1/messages`，`x-api-key`。 | 保留 Messages 适配，不只替换 URL。 |
| 百炼聊天模型 | 使用 `/compatible-mode/v1` 下的 Chat Completions，与声音接口不同。 | Qwen 聊天模型明确关闭可选思考；其他模型不盲发 Qwen 专用参数。 |
| 百炼 Qwen-Audio-TTS | `voice-enrollment/create_voice` 创建，返回 `voice_id`；合成使用 `/api-ws/v1/inference` 和 `run-task/continue-task/finish-task`。 | 支持 Qwen-Audio 3.1 Flash、3.0 Flash、3.0 Plus；创建、列表、模型和音色分别校验。 |
| 旧 Qwen-TTS-VC-Realtime | `qwen-voice-enrollment/create` 返回 `voice`；合成为另一套 realtime 协议。 | 保留旧音色列表与兼容代码；界面新建要求选择新版模型，不能把旧 ID 换个模型名继续使用。 |
| 小米 MiMo 克隆 | 每次请求包含参考音频，当前为非流式分段合成。 | 保留可用路线和串行队列；本地编码缓存不能消除上游生成与样本上传耗时。 |

上述规范分别依据 [DeepSeek 官方首次调用](https://api-docs.deepseek.com/)、[Messages 接口](https://api-docs.deepseek.com/guides/anthropic_api/)、[百炼聊天 API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)、[声音复刻 API](https://help.aliyun.com/zh/model-studio/voice-clone-design-http-api) 和 [实时合成指南](https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide)。目录预设不是账户授权凭证，实际模型名以当前官方文档与账号结果为准。

可运行的参考包括阿里官方 [声音复刻并合成示例](https://github.com/aliyun/alibabacloud-bailian-speech-demo/tree/master/samples/speech-synthesizer/synthesize_speech_from_text_with_qwen_audio_tts_by_cloned_voice) 和 [朗读大模型流式输出示例](https://github.com/aliyun/alibabacloud-bailian-speech-demo/tree/master/samples/speech-synthesizer/synthesize_speech_from_llm_by_streaming_mode)。本次阅读了官方 Python 复刻示例源码，采用其中“创建与合成必须使用同一模型、持久复用 ID、音频块与完成事件分别处理”的约定。示例包含演示性配置、打印和文件写入，未直接复制其运行方式或执行未经检查的下载代码。

DeepSeek 的 [官方思考与工具示例](https://api-docs.deepseek.com/guides/thinking_mode/) 明确要求：思考开启且带工具时，后续请求须回传相应 `reasoning_content`。项目此前重建工具消息时丢弃了该字段，存在 HTTP 400 风险。当前陪伴模式明确使用非思考请求，工具回传仅携带实际文本、函数参数和结果；不把推理内容当最终答复，不声称支持完整的深思考工具历史重放。

## 本轮修复的具体问题

1. DeepSeek 默认思考会延迟首字，有限输出预算也可能只生成推理。现在两个官方协议都明确关闭思考，独立适配器按工具 ID 回传实际结果，拒绝没有完成事件的断流。
2. 模型连接测试原来把空文字也当成功。现在必须有实际可显示文本，才返回连接成功。
3. 百炼 `task-started` 只表示任务启动，后续仍可能拒绝模型、音色或正文。无文字检查现在明确返回 `synthesis_verified=false`，完整可用性必须以短句试听为准。
4. 百炼界面提供三个新版模型的选择项。切换模型清空旧 ID，避免跨模型调用；旧配置可以查看，但不能直接点新建。
5. 创建音色的 HTTP 错误原来丢失业务分类。现在先读取有限错误响应，再生成认证、权限、限流、参考音频/URL、模型等脱敏提示。明确拒绝记录为失败，可人工修正后重试；超时和不明结果仍保持待核实，不自动重复创建。

## 实测与边界

本轮使用已有账号做了最小验证：DeepSeek 官方非思考请求成功；修复后的适配器完成一次真实模型工具调用及结果回传。百炼 Qwen-Audio 3.1 使用官方预置音色完成了“你好”的流式协议验证。该测试用于隔离验证模型和传输，未把预置音色保存为用户音色，也不等于已完成自定义声音复刻。

真实首包、总耗时和声音质量受到网络、模型负载、录音与文本影响，单次验证不构成性能保证。自定义克隆必须经过本地样本上传、取得 ID、审核/状态检查、合成试听、移走原 MP3 后再复用 ID 的独立验收。只有收到用户对额外创建的授权后，才进行会产生新音色的真实测试。

## 使用与维护

停止旧后端，更新环境和前端后重新启动。LLM 选择 DeepSeek 官方预设，读取模型列表、保存并测试；TTS 选择百炼，选择新版模型、保存对应密钥和许可，再创建或选择该模型下的音色。更换模型时不要保留其他模型的 ID。

当前建议将百炼 Flash 流式方案作为低延迟主路线，小米保留为可用备选；音色相似度必须以同一录音的实际试听判断，没有同样本盲评就不能宣称某家质量最好。详细录音流程见 [TTS 文档](tts.md)。
