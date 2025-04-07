"""
消息类型定义
为Agent组件之间的通信提供标准化的消息格式
"""

from datetime import datetime
from typing import List, Optional, Literal, Any
from pydantic import BaseModel, Field

# 保持与 AutoGen-Core 兼容
class BaseMessage(BaseModel):
    """基础消息类型"""
    timestamp: datetime = Field(default_factory=datetime.now)
    
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, self.__class__):
            return False
        # 忽略时间戳比较
        self_dict = self.dict()
        other_dict = other.dict()
        self_dict.pop('timestamp', None)
        other_dict.pop('timestamp', None)
        return self_dict == other_dict

class TextInputMessage(BaseMessage):
    """文本输入消息"""
    text: str

class TextOutputMessage(BaseMessage):
    """文本输出消息"""
    text: str

class AudioInputMessage(BaseMessage):
    """音频输入消息
    包含从用户录制的音频数据
    """
    audio_data: str  # base64编码的音频数据
    format: str = "wav"

class AudioChunk(BaseModel):
    """单个音频数据块"""
    data: str  # base64编码的音频数据
    transcript: Optional[str] = None  # 这一块对应的文字

class AudioOutputMessage(BaseMessage):
    """音频输出消息
    包含要播放的音频数据
    """
    audio_chunks: List[AudioChunk] = []
    transcript: str = ""  # 完整的文字记录
    is_final: bool = False  # 是否是最后一块数据

class SpeechDetectedMessage(BaseMessage):
    """检测到语音的事件消息"""
    confidence: float = 1.0  # 检测置信度

class StateChangeMessage(BaseMessage):
    """状态改变消息"""
    old_state: str
    new_state: str

class InterruptMessage(BaseMessage):
    """打断消息"""
    reason: Literal["user_speech", "manual", "timeout"] = "user_speech"
    smooth: bool = True  # 是否平滑过渡

# 控制消息
class StartListeningMessage(BaseMessage):
    """开始监听消息"""
    pass

class StopListeningMessage(BaseMessage):
    """停止监听消息"""
    pass

class StartSpeakingMessage(BaseMessage):
    """开始说话消息"""
    pass

class StopSpeakingMessage(BaseMessage):
    """停止说话消息"""
    pass

# LLM 交互消息
class ProcessAudioRequest(BaseMessage):
    """处理音频请求"""
    audio_data: str
    format: str = "wav"

class ProcessTextRequest(BaseMessage):
    """处理文本请求"""
    text: str

class LLMResponse(BaseMessage):
    """LLM 响应"""
    text: str = ""
    audio: Optional[str] = None
    is_final: bool = True
