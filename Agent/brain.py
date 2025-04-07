"""
Brain组件
负责认知处理、决策和与LLM的通信
"""

import asyncio
import base64
from datetime import datetime
from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional

import autogen_core
from autogen_core import RoutedAgent, message_handler, MessageContext, AgentId

from .messages import (
    AudioInputMessage,
    AudioOutputMessage,
    TextInputMessage,
    TextOutputMessage,
    AudioChunk,
    ProcessAudioRequest,
    ProcessTextRequest,
    LLMResponse,
    StateChangeMessage,
    InterruptMessage
)
from .state import AgentState


class Brain(RoutedAgent):
    """负责认知处理、决策和与LLM的通信"""
    
    def __init__(self, description: str = "Brain Agent - 负责认知处理和LLM通信"):
        """初始化Brain组件"""
        super().__init__(description)
        self.client = None
        self.messages = []
        self.api_key = None
        self.base_url = None
        self.current_response = None
        self.current_session_id = 0
        self.agent_state = AgentState.IDLE
    
    @classmethod
    def _handles_types(cls):
        """重写以确保正确处理消息类型"""
        # 先使用父类方法获取所有类型
        types = super()._handles_types()
        
        # 显式添加AudioInputMessage类型处理
        from .messages import AudioInputMessage, TextInputMessage, StateChangeMessage, InterruptMessage
        
        # 确保消息类型已注册
        message_types = [t[0] for t in types]
        
        if AudioInputMessage not in message_types:
            types.append((AudioInputMessage, cls.handle_audio_input))
            print(f"[Brain][DEBUG] 注册AudioInputMessage处理器")
        if TextInputMessage not in message_types:
            types.append((TextInputMessage, cls.handle_text_input))
            print(f"[Brain][DEBUG] 注册TextInputMessage处理器")
        if StateChangeMessage not in message_types:
            types.append((StateChangeMessage, cls.handle_state_change))
            print(f"[Brain][DEBUG] 注册StateChangeMessage处理器")
        if InterruptMessage not in message_types:
            types.append((InterruptMessage, cls.handle_interrupt))
            print(f"[Brain][DEBUG] 注册InterruptMessage处理器")
            
        # 打印所有已注册的处理器
        registered_types = []
        for t in types:
            if t[0] != autogen_core._type_helpers.AnyType:
                try:
                    registered_types.append(t[0].__name__ if hasattr(t[0], '__name__') else str(t[0]))
                except:
                    registered_types.append(str(t[0]))
        print(f"[Brain][DEBUG] 所有已注册的处理器: {registered_types}")
            
        # 排除AnyType
        return [t for t in types if t[0] != autogen_core._type_helpers.AnyType]
    
    async def initialize(self) -> None:
        """初始化OpenAI客户端和消息历史"""
        from config import API_KEY, BASE_URL
        import json
        
        # 加载配置文件
        try:
            with open('key.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            # 优先使用配置文件中的值
            self.api_key = config.get("api_key", API_KEY)
            self.base_url = config.get("base_url", BASE_URL)
            self.model_name = config.get("model", "qwen-omni-turbo")
            
            print(f"[Brain][INFO] 从配置文件加载API配置")
            print(f"[Brain][DEBUG] API基础URL: {self.base_url}")
            print(f"[Brain][DEBUG] 模型名称: {self.model_name}")
        except Exception as e:
            print(f"[Brain][WARNING] 加载配置文件失败: {e}，使用默认配置")
            self.api_key = API_KEY
            self.base_url = BASE_URL
            self.model_name = "qwen-omni-turbo"
        
        if not self.api_key:
            raise ValueError("API密钥未设置")
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        
        self.messages = []
        self.current_session_id = 0
        print(f"[Brain][info] Brain初始化完成，组件ID: {self.id}")
        print(f"[Brain][DEBUG] 已注册的消息处理器类型: {list(self._handlers.keys()) if hasattr(self, '_handlers') else '[无]'}")
    
    async def start(self) -> None:
        """启动Brain组件"""
        print(f"[Brain][info] Brain启动完成，组件ID: {self.id}")
        
        # 打印消息处理器类型名称
        handler_types = []
        if hasattr(self, '_handlers'):
            for handler_type in self._handlers.keys():
                try:
                    handler_types.append(handler_type.__name__ if hasattr(handler_type, '__name__') else str(handler_type))
                except:
                    handler_types.append(str(handler_type))
        print(f"[Brain][DEBUG] 消息处理器类型: {handler_types}")
        
        # 不使用订阅方式，而是让Ears组件直接发送消息给Brain
        print("[Brain][DEBUG] Brain组件已准备好接收音频消息")
        
        # 添加一个定时检查任务，每秒输出一次状态信息
        async def check_status():
            while True:
                print(f"[Brain][DEBUG] 当前状态: {self.agent_state.name}, 消息处理器: {list(self._handlers.keys()) if hasattr(self, '_handlers') else '[]'}")
                await asyncio.sleep(5.0)  # 每5秒检查一次
        
        # 启动状态检查任务
        asyncio.create_task(check_status())
    
    async def stop(self) -> None:
        """停止Brain组件"""
        print("[Brain][info] Brain已停止")
    
    async def close(self) -> None:
        """关闭并清理Brain资源"""
        self.client = None
        print("[Brain][info] Brain已关闭")
    
    @message_handler
    async def handle_audio_input(self, message: AudioInputMessage, ctx: MessageContext) -> None:
        """
        处理音频输入消息
        
        Args:
            message: 包含音频数据的消息
            ctx: 消息上下文
        """
        print("\n" + "=" * 50)
        print(f"[Brain][DEBUG] ===== 收到音频输入消息 =====")
        print(f"[Brain][DEBUG] 消息类型: {type(message).__name__}")
        print(f"[Brain][DEBUG] 音频大小: {len(message.audio_data)} bytes")
        print(f"[Brain][DEBUG] 音频格式: {message.format}")
        print(f"[Brain][DEBUG] 消息来源: {ctx.sender if hasattr(ctx, 'sender') else '未知'}")
        print(f"[Brain][DEBUG] 当前状态: {self.agent_state.name}")
        print(f"[Brain][DEBUG] 消息上下文属性: {dir(ctx)}")
        print("=" * 50 + "\n")
        
        # 创建处理请求
        print("[Brain][DEBUG] 创建音频处理请求...")
        try:
            process_request = ProcessAudioRequest(
                audio_data=message.audio_data,
                format=message.format
            )
            print("[Brain][DEBUG] 处理请求已创建，准备更新状态...")
        except Exception as e:
            print(f"[Brain][ERROR] 创建处理请求时出错: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # 更新状态为思考中
        try:
            old_state = self.agent_state
            self.agent_state = AgentState.THINKING
            await self.notify_state_change(old_state, self.agent_state, ctx)
            print("[Brain][DEBUG] 状态已更新为THINKING，开始处理音频...")
        except Exception as e:
            print(f"[Brain][ERROR] 更新状态时出错: {e}")
            import traceback
            traceback.print_exc()
        
        # 处理音频请求
        try:
            await self._process_audio_request(process_request, ctx)
            print("[Brain][DEBUG] 音频处理已完成")
        except Exception as e:
            print(f"[Brain][ERROR] 处理音频时出错: {e}")
            import traceback
            traceback.print_exc()
            
            # 恢复状态为空闲
            self.agent_state = AgentState.IDLE
            await self.notify_state_change(AgentState.THINKING, self.agent_state, ctx)
    
    @message_handler
    async def handle_text_input(self, message: TextInputMessage, ctx: MessageContext) -> str:
        """
        处理文本输入消息
        
        Args:
            message: 包含文本的消息
            ctx: 消息上下文
            
        Returns:
            确认消息
        """
        print("\n" + "=" * 50)
        print(f"[Brain][DEBUG] ===== 收到文本输入消息 =====")
        print(f"[Brain][DEBUG] 消息类型: {type(message).__name__}")
        print(f"[Brain][DEBUG] 消息内容: {message.text}")
        print(f"[Brain][DEBUG] 消息来源: {ctx.sender if hasattr(ctx, 'sender') else '未知'}")
        print(f"[Brain][DEBUG] 当前状态: {self.agent_state.name}")
        print(f"[Brain][DEBUG] 消息上下文属性: {dir(ctx)}")
        print("=" * 50 + "\n")
        
        # 如果是测试消息，直接返回确认
        if message.text == "测试消息":
            print("[Brain][DEBUG] 收到测试消息，直接返回确认")
            return "OK"
        
        # 对于非测试消息，正常处理
        print(f"[Brain][info] 处理文本输入: {message.text}")
        
        # 创建处理请求
        process_request = ProcessTextRequest(
            text=message.text
        )
        
        # 更新状态为思考中
        self.agent_state = AgentState.THINKING
        await self.notify_state_change(AgentState.IDLE, self.agent_state, ctx)
        
        # 处理文本请求
        await self._process_text_request(process_request, ctx)
        
        return "Processed"
    
    @message_handler
    async def handle_state_change(self, message: StateChangeMessage, ctx: MessageContext) -> None:
        """
        处理状态变更消息
        
        Args:
            message: 状态变更消息
            ctx: 消息上下文
        """
        old_state = getattr(AgentState, message.old_state, None)
        new_state = getattr(AgentState, message.new_state, None)
        
        if old_state is not None and new_state is not None:
            print(f"[Brain][info] 状态变更通知: {old_state.name} -> {new_state.name}")
            self.agent_state = new_state
    
    @message_handler
    async def handle_interrupt(self, message: InterruptMessage, ctx: MessageContext) -> None:
        """
        处理打断请求
        
        Args:
            message: 打断消息
            ctx: 消息上下文
        """
        print("[Brain][info] 已处理打断请求，增加会话ID使当前响应过期")
        self.current_session_id += 1  # 增加会话ID使当前响应过期
        
        # 设置为被打断状态
        if self.agent_state != AgentState.INTERRUPTED:
            old_state = self.agent_state
            self.agent_state = AgentState.INTERRUPTED
            await self.notify_state_change(old_state, self.agent_state, ctx)
    

    async def _process_audio_request(self, request: ProcessAudioRequest, ctx: MessageContext) -> None:
        """处理音频请求"""
        try:
            print("[Brain][DEBUG-AUDIO] ===== 开始处理音频请求 =====")
            print(f"[Brain][DEBUG-AUDIO] 请求类型: {type(request).__name__}")
            print(f"[Brain][DEBUG-AUDIO] 音频格式: {request.format}")
            
            # 直接使用音频数据，不需要转录
            audio_b64 = request.audio_data
            print(f"[Brain][DEBUG-AUDIO] 使用音频的base64数据，长度: {len(audio_b64)}")
            
            # 创建用户消息，直接包含音频数据
            user_message = {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": f"data:audio/wav;base64,{audio_b64}",
                            "format": "wav",
                        },
                    }
                ],
            }
            
            # 添加到对话历史
            self.messages.append(user_message)
            
            # 获取LLM回复
            print("[Brain][DEBUG-AUDIO] 向LLM发送请求...")
            
            # 调用LLM获取回复
            response = await self._get_llm_response()
            print(f"[Brain][DEBUG-AUDIO] 收到LLM回复，长度: {len(response)}")
            
            # 保存到对话历史
            self.messages.append({
                "role": "assistant",
                "content": response
            })
            
            # 更新状态为说话中
            old_state = self.agent_state
            self.agent_state = AgentState.SPEAKING
            await self.notify_state_change(old_state, self.agent_state, ctx)
            
            # 通过runtime发送消息
            print("[Brain][DEBUG-AUDIO] 向Mouth组件发送响应...")
            
            # 创建音频输出消息
            audio_chunks = []
            
            # 检查是否有音频数据
            if hasattr(self, 'last_audio_data') and self.last_audio_data:
                print(f"[Brain][DEBUG-AUDIO] 使用收集到的音频数据，共 {len(self.last_audio_data)} 个片段")
                
                # 将音频数据转换为AudioChunk对象
                for audio_item in self.last_audio_data:
                    if 'data' in audio_item:
                        audio_chunk = AudioChunk(
                            data=audio_item['data'],
                            transcript=audio_item.get('transcript', '')
                        )
                        audio_chunks.append(audio_chunk)
            else:
                print("[Brain][DEBUG-AUDIO] 没有收集到音频数据，创建空音频块")
                # 创建一个空的音频块，只是为了触发Mouth组件
                audio_chunk = AudioChunk(
                    data="",  # 空数据
                    transcript=response
                )
                audio_chunks.append(audio_chunk)
            
            # 创建音频输出消息
            audio_output = AudioOutputMessage(
                audio_chunks=audio_chunks,
                transcript=response,
                is_final=True
            )
            
            # 使用与Ears完全相同的方式发送消息
            try:
                # 查找Mouth组件
                mouth_id = None
                
                # 通过类型查找Mouth组件
                try:
                    mouth_id = await self.runtime.get("Mouth")
                    print(f"[Brain][DEBUG-AUDIO] 通过类型找到Mouth组件: {mouth_id}")
                except Exception as e:
                    print(f"[Brain][DEBUG-AUDIO] 通过类型获取Mouth组件失败: {e}")
                    
                    # 如果通过类型获取失败，尝试遍历实例化的Agent
                    if hasattr(self.runtime, '_instantiated_agents'):
                        print("[Brain][DEBUG-AUDIO] 尝试遍历已实例化的Agent")
                        for agent_id, agent in self.runtime._instantiated_agents.items():
                            if agent.__class__.__name__ == "Mouth":
                                mouth_id = agent_id
                                print(f"[Brain][DEBUG-AUDIO] 找到Mouth组件: {mouth_id}")
                                break
                
                if not mouth_id:
                    # 如果还是找不到，使用固定的AgentId
                    from autogen_core import AgentId
                    mouth_id = AgentId("Mouth", "default")
                    print(f"[Brain][DEBUG-AUDIO] 使用默认Mouth ID: {mouth_id}")
                
                # 发送消息
                print(f"[Brain][DEBUG-AUDIO] 开始发送消息到: {mouth_id}")
                print(f"[Brain][DEBUG-AUDIO] 消息类型: {type(audio_output).__name__}")
                
                # 使用与Ears完全相同的方式发送消息
                print("[Brain][DEBUG-AUDIO] 使用非阻塞方式发送音频消息...")
                
                # 创建异步任务发送消息
                async def send_audio_message():
                    try:
                        # 直接发送消息，不设置超时
                        await self.runtime.send_message(
                            audio_output,
                            recipient=mouth_id,
                            sender=self.id
                        )
                        print("[Brain][DEBUG-AUDIO] 音频消息已成功发送到Mouth")
                    except Exception as e:
                        print(f"[Brain][ERROR-AUDIO] 发送音频消息时出错: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 启动异步任务但不等待它完成
                asyncio.create_task(send_audio_message())
                print("[Brain][DEBUG-AUDIO] 已启动异步发送任务")
                print("[Brain][DEBUG-AUDIO] 音频消息已发送到Mouth")
                
                # 等待一些时间让Mouth处理消息
                print("[Brain][DEBUG-AUDIO] 等待Mouth处理消息...")
                await asyncio.sleep(2.0)
                print("[Brain][DEBUG-AUDIO] 等待结束")
                
            except Exception as e:
                print(f"[Brain][ERROR-AUDIO] 发送消息过程中出错: {e}")
                import traceback
                traceback.print_exc()
            
        except Exception as e:
            print(f"[Brain][ERROR-AUDIO] 处理音频请求过程中出错: {e}")
            import traceback
            traceback.print_exc()
            
            # 更新状态为空闲
            old_state = self.agent_state
            self.agent_state = AgentState.IDLE
            await self.notify_state_change(old_state, self.agent_state, ctx)
    
    async def _process_text_request(self, request: ProcessTextRequest, ctx: MessageContext) -> None:
        """
        处理文本请求
        
        Args:
            request: 文本处理请求
            ctx: 消息上下文
        """
        # 创建用户消息
        user_message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": request.text
                }
            ],
        }
        
        # 添加到对话历史
        self.messages.append(user_message)
        
        # 创建新的会话ID
        self.current_session_id += 1
        
        # 生成响应
        await self._generate_response(ctx)
    
    async def _generate_response(self, ctx: MessageContext) -> None:
        """
        生成响应并通过runtime发送
        
        Args:
            ctx: 消息上下文
        """
        try:
            print("[Brain][info] 开始生成响应...")
            session_id = self.current_session_id
            
            # 准备响应数据
            response_data = {
                "ai_text": "",
                "has_audio": False,
                "current_transcript": "",
                "interrupted": False
            }
            
            # 更新状态为说话中（将在收到第一个音频块时进行）
            self.agent_state = AgentState.SPEAKING
            
            # 缓冲初始音频块，以减少感知延迟
            initial_chunks_needed = 1  # 需要缓冲的初始块数量
            first_chunks_buffer = []   # 初始块缓冲区
            chunks_counter = 0         # 当前接收到的块计数
            current_transcript = ""    # 当前累积的转录
            
            # 存储所有音频数据
            all_audio_data = []
            
            # 发送API请求并流式处理响应
            async with self.client.chat.completions.create(
                model="qwen-omni-turbo",
                messages=self.messages,
                modalities=["text", "audio"],
                stream=True
            ) as stream:
                
                # 处理流式响应
                async for chunk in stream:
                    # 检查会话ID是否已过期（被打断）
                    if session_id != self.current_session_id:
                        print("[Brain][info] 会话ID已过期，取消响应生成")
                        response_data["interrupted"] = True
                        break
                    
                    # 获取delta内容
                    delta = chunk.choices[0].delta
                    
                    # 处理文本内容
                    if delta.content:
                        text_content = delta.content
                        response_data["ai_text"] += text_content
                    
                    # 处理音频内容
                    if hasattr(delta, "audio") and delta.audio:
                        response_data["has_audio"] = True
                        all_audio_data.append(delta.audio)
                        
                        # 如果是第一个音频块，更新状态为说话中
                        if not response_data["current_transcript"] and self.agent_state != AgentState.SPEAKING:
                            old_state = self.agent_state
                            self.agent_state = AgentState.SPEAKING
                            await self.notify_state_change(old_state, self.agent_state, ctx)
                        
                        # 更新当前转录
                        if delta.audio.get("transcript"):
                            current_transcript = delta.audio["transcript"]
                            response_data["current_transcript"] = current_transcript
                        
                        # 再次检查是否被打断
                        if self.agent_state == AgentState.INTERRUPTED:
                            print("[Brain][info] 处理音频数据时检测到打断状态，停止处理")
                            break
                        
                        # 获取音频数据
                        audio_data = delta.audio["data"]
                        
                        # 创建音频块
                        audio_chunk = AudioChunk(
                            data=audio_data,
                            transcript=delta.audio.get("transcript", "")
                        )
                        
                        # 根据策略处理音频块
                        if chunks_counter < initial_chunks_needed:
                            # 累积初始块
                            first_chunks_buffer.append(audio_chunk)
                            chunks_counter += 1
                            
                            # 达到所需初始块数量后，发送累积的块
                            if chunks_counter >= initial_chunks_needed:
                                print(f"[Brain][info] 初始缓冲完成，发送前{chunks_counter}个音频块")
                                
                                # 构造音频输出消息并发送
                                audio_output = AudioOutputMessage(
                                    audio_chunks=first_chunks_buffer,
                                    transcript=current_transcript,
                                    is_final=False
                                )
                                
                                # 通过runtime发送消息
                                if hasattr(ctx, 'runtime') and hasattr(ctx, 'topic_id') and ctx.runtime and ctx.topic_id:
                                    await ctx.runtime.publish_message(
                                        audio_output,
                                        topic_id=ctx.topic_id,
                                        sender=self.id
                                    )
                                
                                # 清空缓冲区
                                first_chunks_buffer = []
                        else:
                            # 直接发送后续块
                            audio_chunks = [audio_chunk]
                            
                            # 构造音频输出消息并发送
                            audio_output = AudioOutputMessage(
                                audio_chunks=audio_chunks,
                                transcript=current_transcript,
                                is_final=False
                            )
                            
                            # 通过runtime发送消息
                            if hasattr(ctx, 'runtime') and hasattr(ctx, 'topic_id') and ctx.runtime and ctx.topic_id:
                                await ctx.runtime.publish_message(
                                    audio_output,
                                    topic_id=ctx.topic_id,
                                    sender=self.id
                                )
            
            # 处理最后的缓冲区
            if first_chunks_buffer and self.agent_state != AgentState.INTERRUPTED:
                print(f"[Brain][info] 发送剩余的{len(first_chunks_buffer)}个初始音频块")
                
                # 构造音频输出消息并发送
                audio_output = AudioOutputMessage(
                    audio_chunks=first_chunks_buffer,
                    transcript=current_transcript,
                    is_final=True
                )
                
                # 通过runtime发送消息
                if hasattr(ctx, 'runtime') and hasattr(ctx, 'topic_id') and ctx.runtime and ctx.topic_id:
                    await ctx.runtime.publish_message(
                        audio_output,
                        topic_id=ctx.topic_id,
                        sender=self.id
                    )
            
            # 保存音频数据到实例变量，以便后续使用
            self.last_audio_data = all_audio_data
            
            # 记录AI回复
            if response_data["current_transcript"]:
                print(f"[Brain][info] 响应转录: {response_data['current_transcript']}")
                
                assistant_message = {
                    "role": "assistant",
                    "content": [{"type": "text", "text": response_data["current_transcript"]}]
                }
                self.messages.append(assistant_message)
            elif response_data["ai_text"]:
                print(f"[Brain][info] 响应文本: {response_data['ai_text']}")
                
                assistant_message = {
                    "role": "assistant",
                    "content": [{"type": "text", "text": response_data["ai_text"]}]
                }
                self.messages.append(assistant_message)
            
            # 发送最终的文本输出消息
            if not response_data["interrupted"]:
                text_output = TextOutputMessage(
                    text=response_data["current_transcript"] or response_data["ai_text"]
                )
                
                # 通过runtime发送消息
                if hasattr(ctx, 'runtime') and hasattr(ctx, 'topic_id') and ctx.runtime and ctx.topic_id:
                    await ctx.runtime.publish_message(
                        text_output,
                        topic_id=ctx.topic_id,
                        sender=self.id
                    )
            
            # 更新状态回到空闲
            if self.agent_state == AgentState.SPEAKING:
                old_state = self.agent_state
                self.agent_state = AgentState.IDLE
                await self.notify_state_change(old_state, self.agent_state, ctx)
            
        except Exception as e:
            print(f"[Brain][error] 生成响应时出错: {e}")
            
            # 更新状态回到空闲
            if self.agent_state != AgentState.IDLE:
                old_state = self.agent_state
                self.agent_state = AgentState.IDLE
                await self.notify_state_change(old_state, self.agent_state, ctx)
    
    async def notify_state_change(self, old_state: AgentState, new_state: AgentState, ctx: MessageContext) -> None:
        """
        通知状态变更
        
        Args:
            old_state: 旧状态
            new_state: 新状态
            ctx: 消息上下文
        """
        # 创建状态变更消息
        state_change = StateChangeMessage(
            old_state=old_state.name,
            new_state=new_state.name
        )
        
        # 直接使用self.send_message_to_agent发送
        try:
            # 尝试直接向发送者回复状态变更消息
            if hasattr(ctx, 'sender') and ctx.sender:
                await self.runtime.send_message(
                    state_change,
                    sender=self.id,
                    recipient=ctx.sender
                )
        except Exception as e:
            # 忽略发送错误，不影响主流程
            print(f"[Brain][DEBUG] 发送状态变更消息失败，忽略: {e}")
        
        print(f"[Brain][info] 状态变更: {old_state.name} -> {new_state.name}")
    
    async def _get_llm_response(self) -> str:
        """获取LLM响应"""
        print("[Brain][DEBUG-LLM] 开始请求LLM响应...")
        
        try:
            # 使用初始化时已加载的模型名称
            print(f"[Brain][DEBUG-LLM] 使用模型: {self.model_name}")
            
            # 创建流式聊天完成请求
            response_content = ""
            audio_data = []  # 存储音频数据
            
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=self.messages,
                modalities=["text", "audio"],  # 添加音频模态支持
                stream=True  # 启用流式响应
            )
            
            # 处理流式响应
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content_piece = chunk.choices[0].delta.content
                    response_content += content_piece
                    print(f"[Brain][DEBUG-LLM] 收到流式响应片段: '{content_piece}'", end="", flush=True)
                    
                # 检查是否有音频响应，如果有，我们也需要处理
                if hasattr(chunk.choices[0].delta, "audio") and chunk.choices[0].delta.audio:
                    print("[Brain][DEBUG-LLM] 检测到音频响应片段，正在处理音频数据")
                    audio_data.append(chunk.choices[0].delta.audio)
            
            print(f"\n[Brain][DEBUG-LLM] 完整流式响应: '{response_content[:50]}...'")
            print(f"[Brain][DEBUG-LLM] 收集到 {len(audio_data)} 个音频片段")
            
            # 确保我们返回有效的文本内容
            if not response_content.strip():
                print("[Brain][DEBUG-LLM] 响应内容为空，返回默认消息")
                return "我已收到您的消息，但目前无法提供有效回复。请再试一次。"
            
            # 将音频数据保存到实例变量，以便后续使用
            self.last_audio_data = audio_data
                
            return response_content
            
        except Exception as e:
            print(f"[Brain][ERROR-LLM] LLM请求出错: {e}")
            import traceback
            traceback.print_exc()
            
            # 返回一个错误信息
            return "抱歉，我当前无法处理您的请求，请稍后再试。"
