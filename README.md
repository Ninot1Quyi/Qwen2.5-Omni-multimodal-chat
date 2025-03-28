# Qwen-Omni Real-time Voice Communication

基于通义千问 Qwen-Omni 的实时语音对话系统，支持实时语音交互、动态语音活动检测和流式音频处理。

A real-time voice conversation system based on Tongyi Qianwen Qwen-Omni, supporting real-time voice interaction, dynamic voice activity detection, and streaming audio processing.

> **注意**：这是一个初步的演示版本，主要实现了基础的语音对话功能。我们计划逐步添加更多 Qwen-Omni 支持的多模态交互功能。最终构建一个`全模态`的交互程序。

## 开发计划

以下是计划添加的主要功能：
- [x] 音频通话功能
  - [x] 交互式音频对话
  - [x] 打断式音频通话
- [ ] GUI界面
- [ ] 视频通话功能
  - [ ] 实时视频流处理
  - [ ] 视觉内容理解和分析
- [ ] 多模态文本对话
  - [ ] 图文混合输入
  
- [ ] MCP (Multi-modal Conversational Perception) 功能

## 功能特点

- 实时语音交互：支持用户与AI助手进行实时语音对话
- 智能语音检测：使用 Silero VAD 进行高精度的语音活动检测
- 动态录音控制：根据用户说话情况自动开始和结束录音
- 流式音频处理：支持音频数据的流式处理和播放
- 平滑打断机制：允许用户在AI回答过程中自然打断
- 音频淡出效果：在对话结束或打断时提供平滑的音频过渡

## 环境要求

- Python 3.10 或更高版本
- PyAudio 及其依赖的音频库
- PyTorch (用于语音活动检测)
- 麦克风和音频输出设备

## 安装说明

1. 克隆项目代码：
```bash
git clone https://github.com/Ninot1Quyi/Qwen-Omni-multimodal-chat.git
cd Qwen-Omni-multimodal-chat
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置API密钥：
在 `key.json` 中设置你的 Qwen-Omni API密钥：
```python
API_KEY = 'your-api-key-here'
```

## 使用方法

1. 启动程序：
```bash
python main.py
```

2. 选择录音模式：
   - 动态模式：根据语音活动自动控制录音开始和结束
   - 固定时长模式：录制指定时长的音频

3. 开始对话：
   - 等待提示后开始说话
   - 系统会自动检测语音并进行录音
   - 停止说话后系统会自动结束录音
   - AI助手会通过语音回答你的问题

4. 交互功能：
   - 在AI回答过程中可以直接说话打断
   - 系统会平滑处理打断并开始新的对话

## 配置说明

可以在 `config.py` 中调整以下参数：

- `RATE`：音频采样率（默认16000Hz）
- `CHUNK`：音频数据块大小
- `MIN_SPEECH_DURATION`：最短语音持续时间
- `SPEECH_VOLUME_THRESHOLD`：语音音量阈值
- `MIN_POSITIVE_FRAMES`：语音检测的最小正帧数
- `MIN_NEGATIVE_FRAMES`：静音检测的最小负帧数

## 注意事项

1. 确保系统有可用的麦克风设备
2. 保持网络连接稳定以确保与API的通信
3. 调整麦克风音量以获得最佳的语音识别效果
4. 在嘈杂环境中可能需要调整音量阈值参数

## 许可证

MIT License

## 贡献指南

欢迎提交Issue和Pull Request来帮助改进项目。在提交代码前，请确保：

1. 代码符合Python代码规范
2. 添加必要的注释和文档
3. 更新相关的文档说明
4. 测试代码功能正常

## 联系方式

如有问题或建议，请通过以下方式联系：

- 提交 Issue
- 发送邮件至：[quyimail@foxmail.com]

## 致谢

- [Qwen-Omni](https://github.com/QwenLM/Qwen2.5-Omni) - 通义千问大语言模型 [相关文档](https://help.aliyun.com/zh/model-studio/user-guide/qwen-omni?spm=a2c4g.11186623.0.0.5aefb0a8nJc2z7#db6d0ff7c371y)
- [Silero VAD](https://github.com/snakers4/silero-vad) - 语音活动检测模型 
