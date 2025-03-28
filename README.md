# Qwen2.5-Omni Real-time Voice Communication

基于通义千问 Qwen2.5-Omni 的实时语音对话系统，支持实时语音交互、动态语音活动检测和流式音频处理。

A real-time voice conversation system based on Qwen2.5-Omni, supporting real-time voice interaction, dynamic voice activity detection, and streaming audio processing.

> **注意**：这是一个初步的演示版本，主要实现了基础的语音对话功能。我们计划逐步添加更多 Qwen2.5-Omni 支持的多模态交互功能。最终构建一个`全模态`的交互程序。

## 1 使用方法

### GUI模式

1. 启动GUI界面：
```bash
python app.py
```

2. 在打开的窗口中：
   - 点击"开始对话"按钮启动语音对话
   - 当球体显示红色脉动效果时，说出你的问题
   - 当球体显示绿色动画时，表示AI正在回答
   - 再次点击按钮结束对话
   
<p align="center">
  <img src="https://github.com/Ninot1Quyi/Qwen2.5-Omni-multimodal-chat/blob/main/assets/GUI-1.png" width="45%">
  <img src="https://github.com/Ninot1Quyi/Qwen2.5-Omni-multimodal-chat/blob/main/assets/GUI-2.png" width="45%">
</p>

### 命令行模式

1. 使用命令行模式启动：
```bash
python app.py --console
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

## 2 开发计划

以下是计划添加的主要功能：
- [x] 音频通话功能
  - [x] 交互式音频对话
  - [x] 打断式音频通话
- [x] GUI界面
  - [x] 类Siri球形动态UI
  - [x] 可视化对话状态
- [ ] 视频通话功能
  - [ ] 实时视频流处理
  - [ ] 视觉内容理解和分析
- [ ] 多模态文本对话
  - [ ] 图文混合输入
  
- [ ] MCP (Multi-modal Conversational Perception) 功能

## 3 功能特点

- 实时语音交互：支持用户与AI助手进行实时语音对话
- 智能语音检测：使用 Silero VAD 进行高精度的语音活动检测
- 动态录音控制：根据用户说话情况自动开始和结束录音
- 流式音频处理：支持音频数据的流式处理和播放
- 平滑打断机制：允许用户在AI回答过程中自然打断
- 音频淡出效果：在对话结束或打断时提供平滑的音频过渡
- 现代化GUI界面：提供类似Siri的动态视觉反馈

## 4 环境要求

- Python 3.10（开发环境）
- [uv](https://github.com/astral-sh/uv) - 快速、现代的Python包管理器
- PyAudio 及其依赖的音频库
- PyTorch (用于语音活动检测)
- pywebview (用于GUI界面)
- 麦克风和音频输出设备

## 5 安装说明

1. 安装uv包管理器（如果尚未安装）：
```bash
# 使用pip安装
pip install uv

# 或在Windows上使用PowerShell（推荐）
(Invoke-WebRequest -Uri https://github.com/astral-sh/uv/releases/latest/download/uv-installer.ps1 -UseBasicParsing).Content | python -

# 验证安装
uv --version
```

2. 克隆项目代码：
```bash
git clone https://github.com/Ninot1Quyi/Qwen2.5-Omni-multimodal-chat.git
cd Qwen2.5-Omni-multimodal-chat
```

3. 创建并激活虚拟环境：
```bash
# 创建Python 3.10虚拟环境
uv venv --python=3.10

# 激活虚拟环境（Windows）
.venv\Scripts\activate
```

4. 安装依赖：
```bash
# 使用uv安装requirements.txt中的依赖
uv pip install -r requirements.txt
```

5. 配置API密钥：
复制`key.json.example`为`key.json`，填入你的API密钥：
```json
{
    "api_key": "your-api-key-here"
}
```

## 6 配置说明

可以在 `config.py` 中调整以下参数：

- `RATE`：音频采样率（默认16000Hz）
- `CHUNK`：音频数据块大小
- `MIN_SPEECH_DURATION`：最短语音持续时间
- `SPEECH_VOLUME_THRESHOLD`：语音音量阈值
- `MIN_POSITIVE_FRAMES`：语音检测的最小正帧数
- `MIN_NEGATIVE_FRAMES`：静音检测的最小负帧数

## 7 项目结构

```
Qwen2.5-Omni-multimodal-chat/
├── app.py                 # 主入口文件，支持GUI和命令行模式
├── webview_api.py         # pywebview API接口
├── voice_chat.py          # 语音聊天核心功能
├── audio_player.py        # 音频播放组件
├── audio_recorder.py      # 音频录制组件
├── config.py              # 配置文件
├── requirements.txt       # 依赖库列表
├── web/                   # GUI前端文件
│   ├── templates/         # HTML模板
│   │   └── index.html     # 主界面HTML
│   └── static/            # 静态资源
│       ├── css/           # 样式文件
│       │   └── style.css  # 主样式表
│       └── js/            # JavaScript文件
│           └── app.js     # 前端逻辑
```

## 8 依赖管理

使用uv管理项目依赖：

```bash
# 重建开发环境（使用requirements.txt）
uv venv --python=3.10  # 创建Python 3.10虚拟环境
.venv\Scripts\activate  # 激活环境
uv pip install -r requirements.txt  # 安装依赖

# 查看已安装的包
uv pip list

# 检查可更新的包
uv pip list --outdated

# 生成新的requirements.txt（如有依赖更新）
uv pip freeze > requirements.txt
```

## 9 注意事项

1. 确保系统有可用的麦克风设备
2. 保持网络连接稳定以确保与API的通信
3. 调整麦克风音量以获得最佳的语音识别效果
4. 在嘈杂环境中可能需要调整音量阈值参数
5. 使用uv管理依赖可以显著提升安装速度
6. 建议在虚拟环境中进行开发和构建

## 10 许可证

MIT License

## 11 贡献指南

欢迎提交Issue和Pull Request来帮助改进项目。在提交代码前，请确保：

1. 代码符合Python代码规范
2. 添加必要的注释和文档
3. 更新相关的文档说明
4. 测试代码功能正常

## 12 联系方式

如有问题或建议，请通过以下方式联系：

- 提交 Issue
- 发送邮件至：[quyimail@foxmail.com]

## 致谢

- [Qwen2.5-Omni](https://github.com/QwenLM/Qwen2.5-Omni) - 通义千问大语言模型 [相关文档](https://help.aliyun.com/zh/model-studio/user-guide/qwen-omni?spm=a2c4g.11186623.0.0.5aefb0a8nJc2z7#db6d0ff7c371y)
- [Silero VAD](https://github.com/snakers4/silero-vad) - 语音活动检测模型 
- [pywebview](https://pywebview.flowrl.com/) - Python GUI框架
