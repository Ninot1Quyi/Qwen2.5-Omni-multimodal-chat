"""
Agent模块初始化
定义了基于AutoGen-Core的Agent系统和组件
"""

from .state import AgentState
from .messages import (
    BaseMessage,
    TextInputMessage,
    TextOutputMessage,
    AudioInputMessage,
    AudioOutputMessage,
    AudioChunk,
    SpeechDetectedMessage,
    StateChangeMessage,
    InterruptMessage,
    StartListeningMessage,
    StopListeningMessage,
    StartSpeakingMessage,
    StopSpeakingMessage,
    ProcessAudioRequest,
    ProcessTextRequest,
    LLMResponse
)
from .brain import Brain
from .ears import Ears
from .mouth import Mouth
from .agent import AgentSystem

__all__ = [
    # 组件
    'Brain',
    'Ears',
    'Mouth',
    'AgentSystem',
    
    # 状态
    'AgentState',
    
    # 消息类型
    'BaseMessage',
    'TextInputMessage',
    'TextOutputMessage',
    'AudioInputMessage',
    'AudioOutputMessage',
    'AudioChunk',
    'SpeechDetectedMessage',
    'StateChangeMessage',
    'InterruptMessage',
    'StartListeningMessage',
    'StopListeningMessage',
    'StartSpeakingMessage',
    'StopSpeakingMessage',
    'ProcessAudioRequest',
    'ProcessTextRequest',
    'LLMResponse'
]
