"""
Agent状态定义
"""

from enum import Enum, auto

class AgentState(Enum):
    """Agent状态枚举类"""
    IDLE = auto()        # 空闲状态
    LISTENING = auto()   # 正在监听用户输入
    THINKING = auto()    # 正在思考/处理
    SPEAKING = auto()    # 正在输出/说话
    INTERRUPTED = auto() # 已被打断
