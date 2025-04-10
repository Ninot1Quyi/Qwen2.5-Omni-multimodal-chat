# Qwen2.5-Omni Real-time Voice Communication

基于通义千问 Qwen2.5-Omni 在线API的实时语音对话系统，支持实时语音交互、动态语音活动检测和流式音频处理。

A real-time voice conversation system based on Qwen2.5-Omni Online API, supporting real-time voice interaction, dynamic voice activity detection, and streaming audio processing.

> **注意**：这是一个初步的演示版本，主要实现了基础的语音对话功能。
>
> 计划逐步添加更多 Qwen2.5-Omni 支持的多模态交互功能。最终构建一个`全模态`的交互程序。
>
> **<u>本项目开发过程中使用了大量AI</u>**

## 1 使用方法

### GUI模式

1. 启动GUI界面：
```bash
python app.py
```

2. 在打开的窗口中：
   - 点击"开始对话"按钮启动语音对话
   - 用户可以连续发言和打断发言
   - 再次点击按钮结束对话
   

<p align="center">
  <img src="https://raw.githubusercontent.com/Ninot1Quyi/Qwen2.5-Omni-multimodal-chat/main/assets/GUI-1.png" width="45%">
  <img src="https://raw.githubusercontent.com/Ninot1Quyi/Qwen2.5-Omni-multimodal-chat/main/assets/GUI-2.png" width="45%">
</p>
## 2 开发计划

**<u>接下来要开发的内容： 完成Agent的Eyes 视觉能力，让它能够看到桌面，并和用户交流</u>**

以下是计划添加的主要功能：

- [ ] Agent架构
  - [x] **Brain** 与LLM交互 
    - [ ] 

  - [x] **Ears** 听觉能力
    - [x] 交互式音频对话
    - [x] 打断式音频通话
    - [ ] 语音转文字，兼容Qwen-Omni对同一个输入Massage的模态限制，以更好支持多模态

  - [x] **Mouth **语音能力
    - [x] 交互式音频对话
    - [x] 打断式音频通话

  - [ ] **Eyes** 视觉能力
    - [ ] 通过点击“分享屏幕按钮”观察用户电脑桌面，并给出反馈
    - [ ] 通过语音交互，自动观察屏幕内容
    - [ ] 视频通话

  - [x] **Skin** GUI界面
    - [x] 音频交互动态UI
    - [x] 可视化对话状态

  - [ ] **Hands** 工作能力
    - [ ] 简单函数调用
    - [ ] 引用Qwen-VL来增强鼠标控制能力，可以做一些简单操作
    - [ ] MCP (Multi-modal Conversational Perception) 功能


## 3 功能特点

- 实时语音交互：支持用户与AI助手进行实时语音对话
- 智能语音检测：使用 Silero VAD (ONNX版本) 进行高精度的语音活动检测，无需PyTorch依赖
- 动态录音控制：根据用户说话情况自动开始和结束录音
- 流式音频处理：支持音频数据的流式处理和播放
- 平滑打断机制：允许用户在AI回答过程中自然打断
- 音频淡出效果：在对话结束或打断时提供平滑的音频过渡
- 现代化GUI界面：动态视觉反馈

## 4 环境要求

- Python 3.10（开发环境）
- PyAudio 及其依赖的音频库
- onnxruntime - 用于语音活动检测
- pywebview (用于GUI界面)
- 麦克风和音频输出设备
- 推荐：[uv](https://github.com/astral-sh/uv) - 快速、现代的Python包管理器

## 5 安装说明

### 5.1 方法一：直接下载可执行文件

访问[Releases页面](https://github.com/Ninot1Quyi/Qwen2.5-Omni-multimodal-chat/releases)下载最新的Windows可执行文件。

下载后解压，在`key.json`中填入你的通义千问API密钥 **[API key获取方式](https://help.aliyun.com/zh/model-studio/getting-started/first-api-call-to-qwen?spm=a2c4g.11186623.help-menu-2400256.d_0_1_0.5a06b0a8iZbkAV)**：

双击"QwenOmniVoiceAssistant.exe"即可运行。

### 5.2 方法二：从源码构建

#### 安装步骤

1. **创建Python环境**：

```bash
# 安装Python 3.10（如已安装请跳过）
# https://www.python.org/downloads/release/python-31011/

# 克隆项目代码
git clone https://github.com/Ninot1Quyi/Qwen2.5-Omni-multimodal-chat.git
cd Qwen2.5-Omni-multimodal-chat

# 创建虚拟环境并激活
python -m venv .venv
# Windows
.venv\Scripts\activate  
# Linux/macOS
# source .venv/bin/activate
```

2. **安装依赖**：

```bash
# 安装项目依赖
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

3. **配置API密钥**：
复制`key.json.example`为`key.json`，填入你的通义千问API密钥 **[API key获取方式](https://help.aliyun.com/zh/model-studio/getting-started/first-api-call-to-qwen?spm=a2c4g.11186623.help-menu-2400256.d_0_1_0.5a06b0a8iZbkAV)**：
```json
{
    "api_key": "your-api-key-here",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
}
```

4. **运行应用**：

```bash
# 启动图形界面版本
python app.py

# 或启动命令行版本
python app.py --console
```

5. **打包应用**：

项目根目录命令行输入：

```
.\build-scripts\windows\build.bat
```

**或双击启动打包脚本`build.bat`，打包文件存放=在`dist`文件夹下**

### 5.3 常见问题

- **麦克风未检测到**：请检查系统麦克风权限设置，确保应用有权限访问麦克风
- **运行时缺少依赖**：确保已正确安装所有依赖，如遇问题可尝试`pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/`
- **API密钥无效**：确保已在key.json中填入正确的通义千问API密钥

### 5.4 高级用户说明

如需使用更高级的包管理工具如uv，可以参考以下步骤：

```bash
 安装uv包管理器
pip install uv

# 使用uv创建环境
uv venv --python=3.10

# 使用uv安装依赖
uv pip install -r requirements.txt
```

## 6 配置说明

可以在 `config.py` 中调整以下参数：

- `DEBUG`：调试模式开关，启用时会保存录音文件
- `AUDIO_FORMAT`：音频格式（默认pyaudio.paInt16）
- `CHANNELS`：音频通道数（默认1）
- `RATE`：音频采样率（默认16000Hz，兼容Silero VAD）
- `CHUNK`：音频数据块大小（默认512，相当于32毫秒帧大小）
- `RECORD_SECONDS`：默认录音秒数
- `MIN_SPEECH_DURATION`：最短语音持续时间（秒）
- `SPEECH_VOLUME_THRESHOLD`：语音音量阈值
- `NORMAL_VOLUME_THRESHOLD`：正常音量阈值
- `MIN_POSITIVE_FRAMES`：语音检测的最小正帧数
- `MIN_NEGATIVE_FRAMES`：静音检测的最小负帧数
- `PLAYER_RATE`：音频播放器采样率（默认24000Hz，匹配模型输出）
- `FADE_OUT_DURATION`：音频淡出持续时间（秒）
- `MAX_FINISH_DURATION`：打断时最大允许的完成时间（秒）

## 7 项目结构

```
Qwen2.5-Omni-multimodal-chat/
├── app.py             # 主程序入口
├── Agent.py           # 核心代理类（语音对话管理）
├── ears.py            # 音频输入处理（麦克风和VAD）
├── mouth.py           # 音频输出处理（语音合成和播放）
├── webview_api.py     # WebView API接口
├── utils.py           # 通用工具函数
├── config.py          # 配置文件
├── key.json.example   # API密钥配置示例
├── pyproject.toml     # Python项目配置
├── requirements.txt   # 主要依赖列表
├── uv.lock           # UV包管理器锁文件
├── LICENSE           # MIT许可证
├── README.md         # 项目说明文档
│
├── assets/           # 资源文件
│
├── models/           # 模型文件
│   └── silero_vad.onnx  # 语音活动检测模型
│
├── recordings/       # 录音文件目录（运行时生成）
│
├── build-scripts/    # 构建脚本
│   └── windows/      # Windows平台构建
│       ├── build.py        # 构建Python脚本
│       ├── build.bat       # 构建批处理文件
│       ├── direct_spec.txt # PyInstaller规范文件
│       └── README.md       # 构建说明
│
├── web/             # GUI前端文件
│   ├── templates/    # HTML模板
│   │   └── index.html  # 主界面HTML
│   └── static/       # 静态资源
│       ├── css/      # 样式文件
│       │   └── style.css  # 主样式表
│       └── js/       # JavaScript文件
│           └── app.js  # 前端逻辑
│
├── build/           # 构建中间文件（自动生成）
└── dist/            # 分发包（自动生成）
```

## 8 注意事项

1. 确保系统有可用的麦克风设备
2. 保持网络连接稳定以确保与API的通信
3. 调整麦克风音量以获得最佳的语音识别效果
4. 在嘈杂环境中可能需要调整音量阈值参数
5. 使用uv管理依赖可以显著提升安装速度
6. 建议在虚拟环境中进行开发和构建

## 9 许可证

本项目采用 MIT 许可证，这意味着您可以自由地使用、修改、分发本软件，无论是用于个人还是商业目的。详情请参见项目根目录下的 [LICENSE](./LICENSE) 文件。

## 10 贡献指南

欢迎提交Issue和Pull Request来帮助改进项目。在提交代码前，请确保：

1. 代码符合Python代码规范
2. 添加必要的注释和文档
3. 更新相关的文档说明
4. 测试代码功能正常

## 11 联系方式

如有问题或建议，请通过以下方式联系：

- 提交 Issue
- 发送邮件至：[quyimail@foxmail.com]

## 致谢

- [Qwen2.5-Omni](https://github.com/QwenLM/Qwen2.5-Omni) - 通义千问全模特模型 [相关文档](https://help.aliyun.com/zh/model-studio/user-guide/qwen-omni?spm=a2c4g.11186623.0.0.5aefb0a8nJc2z7#db6d0ff7c371y)
- [Silero VAD](https://github.com/snakers4/silero-vad) - 语音活动检测模型 
- [pywebview](https://pywebview.flowrl.com/) - Python GUI框架
- [Cursor](https://www.cursor.com/cn) - AI代码编辑器
