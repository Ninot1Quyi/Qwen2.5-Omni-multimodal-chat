"""
Agent主类
协调Brain、Ears和Mouth组件，处理消息路由
"""

import asyncio
from typing import Optional, Dict, Any, List, Type

import autogen_core
from autogen_core import (
    SingleThreadedAgentRuntime, DefaultInterventionHandler,
    DefaultTopicId, AgentId
)

from .brain import Brain
from .ears import Ears
from .mouth import Mouth
from .state import AgentState
from .messages import (
    AudioInputMessage,
    AudioOutputMessage,
    SpeechDetectedMessage,
    TextInputMessage,
    TextOutputMessage,
    StateChangeMessage,
    InterruptMessage,
    StartListeningMessage,
    StopListeningMessage
)


class AgentSystem:
    """拟人化Agent系统，集成认知、听觉和发声功能"""
    
    def __init__(self, description: str = "拟人化AI交互Agent系统"):
        """
        初始化Agent系统
        
        Args:
            description: 系统描述
        """
        self.description = description
        
        # 运行时相关
        self.runtime = None
        self.brain_id = None
        self.ears_id = None
        self.mouth_id = None
        
        # 状态管理
        self.state = AgentState.IDLE
    
    async def initialize(self) -> None:
        """初始化Agent系统和所有组件"""
        print("[AgentSystem] 正在初始化系统...")
        
        # 创建运行时
        self.runtime = SingleThreadedAgentRuntime(
            intervention_handlers=[DefaultInterventionHandler()],
            ignore_unhandled_exceptions=True
        )
        
        # 注册组件类型
        brain_type = await Brain.register(
            runtime=self.runtime,
            type="Brain",
            factory=lambda: Brain("Brain - 负责认知处理和LLM通信")
        )
        
        ears_type = await Ears.register(
            runtime=self.runtime,
            type="Ears",
            factory=lambda: Ears("Ears - 负责音频输入和语音检测")
        )
        
        mouth_type = await Mouth.register(
            runtime=self.runtime,
            type="Mouth",
            factory=lambda: Mouth("Mouth - 负责音频输出和语音合成")
        )
        
        # 获取组件实例
        self.brain_id = await self.runtime.get(brain_type, "default")
        self.ears_id = await self.runtime.get(ears_type, "default")
        self.mouth_id = await self.runtime.get(mouth_type, "default")
        
        # 获取底层组件实例
        brain = await self.runtime.try_get_underlying_agent_instance(self.brain_id, Brain)
        ears = await self.runtime.try_get_underlying_agent_instance(self.ears_id, Ears)
        mouth = await self.runtime.try_get_underlying_agent_instance(self.mouth_id, Mouth)
        
        # 初始化所有组件
        await brain.initialize()
        await ears.initialize()
        await mouth.initialize()
        
        print("[AgentSystem] 系统初始化完成")
    
    async def start(self) -> None:
        """启动所有组件"""
        print("[AgentSystem] 正在启动所有组件...")
        
        # 获取底层组件实例
        brain = await self.runtime.try_get_underlying_agent_instance(self.brain_id, Brain)
        ears = await self.runtime.try_get_underlying_agent_instance(self.ears_id, Ears)
        mouth = await self.runtime.try_get_underlying_agent_instance(self.mouth_id, Mouth)
        
        # 启动所有组件
        await brain.start()
        await ears.start()
        await mouth.start()
        
        # 设置初始状态
        self.state = AgentState.IDLE
        
        print("[AgentSystem] 所有组件启动完成")
    
    async def stop(self) -> None:
        """停止所有组件"""
        print("[AgentSystem] 正在停止所有组件...")
        
        # 获取底层组件实例
        brain = await self.runtime.try_get_underlying_agent_instance(self.brain_id, Brain) 
        ears = await self.runtime.try_get_underlying_agent_instance(self.ears_id, Ears)
        mouth = await self.runtime.try_get_underlying_agent_instance(self.mouth_id, Mouth)
        
        # 停止各组件
        await mouth.stop()
        await ears.stop()
        await brain.stop()
        
        print("[AgentSystem] 所有组件已停止")
    
    async def close(self) -> None:
        """关闭并清理所有组件资源"""
        print("[AgentSystem] 正在关闭所有组件资源...")
        
        # 停止所有组件
        await self.stop()
        
        # 获取底层组件实例
        brain = await self.runtime.try_get_underlying_agent_instance(self.brain_id, Brain)
        ears = await self.runtime.try_get_underlying_agent_instance(self.ears_id, Ears)
        mouth = await self.runtime.try_get_underlying_agent_instance(self.mouth_id, Mouth)
        
        # 关闭各组件资源
        await mouth.close()
        await ears.close()
        await brain.close()
        
        print("[AgentSystem] 所有组件资源已关闭")
    
    async def start_listening(self) -> None:
        """开始监听用户输入"""
        print(f"[AgentSystem][DEBUG] 尝试开始监听，当前状态: {self.state.name}")
        
        # 如果状态不是IDLE，则尝试重置状态
        if self.state != AgentState.IDLE:
            if self.state == AgentState.SPEAKING:
                print("[AgentSystem][DEBUG] 当前正在说话中，尝试打断...")
                await self.interrupt(reason="manual", smooth=True)
                # 等待状态转换
                for _ in range(10):  # 最多等待10次检查
                    await asyncio.sleep(0.2)
                    if self.state == AgentState.IDLE:
                        break
            else:
                print(f"[AgentSystem][DEBUG] 当前状态非IDLE，正在等待状态变更: {self.state.name}")
                # 等待一段时间，看状态是否变为IDLE
                for _ in range(10):  # 最多等待10次检查
                    await asyncio.sleep(0.2)
                    if self.state == AgentState.IDLE:
                        break
            
            # 最后检查状态是否为IDLE
            if self.state != AgentState.IDLE:
                print(f"[AgentSystem][WARNING] 无法开始监听，状态未变为IDLE: {self.state.name}")
                return
        
        # 现在状态确保是IDLE
        print("[AgentSystem][DEBUG] 开始监听用户输入")
        
        # 创建开始监听消息
        start_listening_msg = StartListeningMessage()
        
        # 直接使用已知的 ears_id 发送消息
        try:
            if self.ears_id:
                print(f"[AgentSystem][DEBUG] 发送开始监听指令到Ears组件: {self.ears_id}")
                
                await self.runtime.send_message(
                    start_listening_msg,
                    recipient=self.ears_id
                )
                print("[AgentSystem][DEBUG] 开始监听指令已发送")
                
                # 更新状态
                self.state = AgentState.LISTENING
                print(f"[AgentSystem][DEBUG] 系统状态已更新为: {self.state.name}")
            else:
                print("[AgentSystem][ERROR] Ears组件ID不可用，无法发送开始监听指令")
        except Exception as e:
            print(f"[AgentSystem][ERROR] 发送开始监听指令时出错: {e}")
            import traceback
            traceback.print_exc()
    
    async def interrupt(self, reason: str = "user_speech", smooth: bool = True) -> None:
        """
        中断当前活动
        
        Args:
            reason: 中断原因
            smooth: 是否平滑过渡
        """
        print(f"[AgentSystem] 中断当前活动，原因: {reason}")
        
        # 创建中断消息
        interrupt_msg = InterruptMessage(reason=reason, smooth=smooth)
        
        # 向所有组件发送中断消息
        topic_id = DefaultTopicId()
        await self.runtime.publish_message(
            interrupt_msg,
            topic_id=topic_id
        )
        
        # 更新状态
        self.state = AgentState.INTERRUPTED
    
    async def set_recording_mode(self, mode: str, seconds: int = 5) -> None:
        """
        设置录音模式
        
        Args:
            mode: 录音模式，"dynamic"或"fixed"
            seconds: 固定录音时的时长，默认5秒
        """
        ears = await self.runtime.try_get_underlying_agent_instance(self.ears_id, Ears)
        ears.set_recording_mode(mode, seconds)
        print(f"[AgentSystem] 录音模式已设置为: {mode}" + (f", 时长: {seconds}秒" if mode == "fixed" else ""))
    
    async def get_conversation_history(self) -> List[Dict[str, Any]]:
        """获取对话历史"""
        brain = await self.runtime.try_get_underlying_agent_instance(self.brain_id, Brain)
        return brain.messages
    
    async def get_available_microphones(self) -> list:
        """获取可用麦克风列表"""
        ears = await self.runtime.try_get_underlying_agent_instance(self.ears_id, Ears)
        return await ears.get_available_microphones()
    
    async def process_message(self) -> None:
        """处理一条消息"""
        print("[AgentSystem][DEBUG] 处理单条消息...")
        try:
            if self.runtime._message_queue and not self.runtime._message_queue.empty():
                print("[AgentSystem][DEBUG] 消息队列不为空，正在处理下一条消息")
            else:
                print("[AgentSystem][DEBUG] 消息队列为空")
            await self.runtime._process_next()
        except Exception as e:
            print(f"[AgentSystem][ERROR] 处理消息时出错: {e}")
            import traceback
            traceback.print_exc()
    
    async def process_messages(self, count: int = 5) -> None:
        """
        处理多条消息
        
        Args:
            count: 尝试处理的消息数量
        """
        print(f"[AgentSystem][DEBUG] 尝试处理 {count} 条消息...")
        for i in range(count):
            print(f"[AgentSystem][DEBUG] 处理第 {i+1}/{count} 条消息")
            
            try:
                if self.runtime._message_queue and not self.runtime._message_queue.empty():
                    print(f"[AgentSystem][DEBUG] 消息队列不为空，大约有 {self.runtime._message_queue.qsize()} 条待处理消息")
                else:
                    print("[AgentSystem][DEBUG] 消息队列为空")
                
                # 处理消息
                await self.runtime._process_next()
                
                # 短暂等待，允许异步操作完成
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"[AgentSystem][ERROR] 处理消息时出错: {e}")
                import traceback
                traceback.print_exc()
