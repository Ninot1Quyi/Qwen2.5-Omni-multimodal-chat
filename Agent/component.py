"""
基础组件类
为所有Agent组件提供通用功能
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .agent import Agent

class Component(ABC):
    """Agent组件的基类"""
    
    def __init__(self, agent: 'Agent', name: str):
        """
        初始化组件
        
        Args:
            agent: 所属的Agent引用
            name: 组件名称
        """
        self.agent = agent
        self.name = name
        self._is_running = False
    
    @property
    def is_running(self) -> bool:
        """组件是否正在运行"""
        return self._is_running
    
    @abstractmethod
    async def initialize(self) -> None:
        """初始化组件资源"""
        pass
    
    @abstractmethod
    async def start(self) -> None:
        """启动组件"""
        self._is_running = True
    
    @abstractmethod
    async def stop(self) -> None:
        """停止组件"""
        self._is_running = False
    
    @abstractmethod
    async def close(self) -> None:
        """关闭并清理组件资源"""
        pass
    
    async def send_message_to_agent(self, message: Any) -> None:
        """
        向Agent发送消息
        
        Args:
            message: 要发送的消息对象
        """
        await self.agent.runtime.send_message(
            message,
            sender=self.agent.id,
            recipient=self.agent.id
        )
    
    async def log(self, message: str, level: str = "info") -> None:
        """
        记录日志
        
        Args:
            message: 日志消息
            level: 日志级别，默认为info
        """
        print(f"[{self.name}][{level}] {message}")
