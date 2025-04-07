"""
Mouth组件
负责音频输出和语音合成
"""

import asyncio
import time
import threading
import queue
import base64
import numpy as np
import pyaudio
import traceback
from typing import Optional, List, Any, Dict

import autogen_core
from autogen_core import RoutedAgent, message_handler, MessageContext

from .messages import (
    AudioOutputMessage, 
    InterruptMessage, 
    StartSpeakingMessage,
    StopSpeakingMessage,
    StateChangeMessage,
    LLMResponse
)
from .state import AgentState
from config import PLAYER_RATE, FADE_OUT_DURATION, MAX_FINISH_DURATION


class Mouth(RoutedAgent):
    """负责音频输出和语音合成，集成了AudioPlayer功能"""
    
    def __init__(self, description: str = "Mouth Agent - 负责音频输出和语音合成"):
        """初始化Mouth组件"""
        super().__init__(description)
        self.is_speaking = False
        self.playback_task = None
        self.agent_state = AgentState.IDLE
        
        # 音频播放器相关属性
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.is_playing = False
        self.should_stop = False
        self.audio_thread = None
        self.audio_queue = queue.Queue()
        self.buffer_empty = threading.Event()
        self.buffer_empty.set()  # 初始状态为空
        self.last_audio_time = None
        
        # 播放完成事件
        self.playback_finished = threading.Event()
        
        # 平滑打断功能
        self.smooth_interrupt = False
        self.max_finish_duration = MAX_FINISH_DURATION
        self.interrupt_time = None
        
        # 淡出效果
        self.fade_out_enabled = True
        self.fade_out_duration = FADE_OUT_DURATION
        self.fade_out_active = False
        self.fade_out_start_time = None
        
        # 流操作锁
        self.stream_lock = threading.RLock()
    
    @classmethod
    def _handles_types(cls):
        """重写以解决AnyType序列化的问题"""
        # 先使用父类方法获取所有类型
        types = super()._handles_types()
        
        # 显式添加消息类型处理
        from .messages import (
            AudioOutputMessage, 
            InterruptMessage, 
            StartSpeakingMessage,
            StopSpeakingMessage,
            StateChangeMessage,
            LLMResponse
        )
        
        # 确保消息类型已注册
        message_types = [t[0] for t in types]
        
        if AudioOutputMessage not in message_types:
            types.append((AudioOutputMessage, cls.handle_audio_output))
            print(f"[Mouth][DEBUG] 注册AudioOutputMessage处理器")
        if InterruptMessage not in message_types:
            types.append((InterruptMessage, cls.handle_interrupt))
            print(f"[Mouth][DEBUG] 注册InterruptMessage处理器")
        if StartSpeakingMessage not in message_types:
            types.append((StartSpeakingMessage, cls.handle_start_speaking))
            print(f"[Mouth][DEBUG] 注册StartSpeakingMessage处理器")
        if StopSpeakingMessage not in message_types:
            types.append((StopSpeakingMessage, cls.handle_stop_speaking))
            print(f"[Mouth][DEBUG] 注册StopSpeakingMessage处理器")
        if StateChangeMessage not in message_types:
            types.append((StateChangeMessage, cls.handle_state_change))
            print(f"[Mouth][DEBUG] 注册StateChangeMessage处理器")
        if LLMResponse not in message_types:
            types.append((LLMResponse, cls.handle_llm_response))
            print(f"[Mouth][DEBUG] 注册LLMResponse处理器")
            
        # 打印所有已注册的处理器
        registered_types = []
        for t in types:
            if t[0] != autogen_core._type_helpers.AnyType:
                try:
                    registered_types.append(t[0].__name__ if hasattr(t[0], '__name__') else str(t[0]))
                except:
                    registered_types.append(str(t[0]))
        print(f"[Mouth][DEBUG] 所有已注册的处理器: {registered_types}")
            
        # 排除AnyType
        return [t for t in types if t[0] != autogen_core._type_helpers.AnyType]
    
    async def initialize(self) -> None:
        """初始化音频播放器"""
        print("[Mouth][info] Mouth初始化完成")
        print(f"[Mouth][DEBUG] 已注册的消息处理器类型: {list(self._handlers.keys()) if hasattr(self, '_handlers') else '[无]'}")
    
    async def start(self) -> None:
        """启动Mouth组件"""
        print("[Mouth][info] Mouth启动完成")
        
        # 打印消息处理器类型名称
        handler_types = []
        if hasattr(self, '_handlers'):
            for handler_type in self._handlers.keys():
                try:
                    handler_types.append(handler_type.__name__ if hasattr(handler_type, '__name__') else str(handler_type))
                except:
                    handler_types.append(str(handler_type))
        print(f"[Mouth][DEBUG] 消息处理器类型: {handler_types}")
        
        # 添加一个定时检查任务，每5秒输出一次状态信息
        async def check_status():
            while True:
                print(f"[Mouth][DEBUG] 当前状态: {self.agent_state.name}, 消息处理器: {list(self._handlers.keys()) if hasattr(self, '_handlers') else '[]'}")
                await asyncio.sleep(5.0)
        
        # 启动状态检查任务
        asyncio.create_task(check_status())
    
    async def stop(self) -> None:
        """停止Mouth组件"""
        # 停止当前播放
        await self._stop_speaking(True)
        
        print("[Mouth][info] Mouth已停止")
    
    async def close(self) -> None:
        """关闭并清理Mouth资源"""
        await self.stop()
        
        # 关闭PyAudio
        try:
            self.p.terminate()
        except Exception as e:
            print(f"[Mouth][ERROR] 终止PyAudio时出错: {e}")
        
        print("[Mouth][info] Mouth已关闭")
    
    def start_stream(self):
        """启动音频流"""
        with self.stream_lock:
            # 如果已经有活跃的流，先尝试关闭它
            if self.stream is not None:
                try:
                    print("[Mouth][DEBUG] 检测到已存在的音频流，先关闭它")
                    self.stop_stream()
                    # 短暂等待确保资源释放
                    time.sleep(0.2)
                except Exception as e:
                    print(f"[Mouth][ERROR] 关闭现有音频流时出错: {e}")
                
            # 即使关闭失败也继续尝试创建新流
            try:
                # 检查PyAudio对象是否有效
                if self.p is None or not hasattr(self.p, 'open'):
                    print("[Mouth][DEBUG] PyAudio对象无效，重新创建")
                    try:
                        # 如果已存在，先尝试终止
                        if self.p is not None:
                            try:
                                self.p.terminate()
                            except:
                                pass
                        # 重新创建PyAudio对象
                        self.p = pyaudio.PyAudio()
                    except Exception as e:
                        print(f"[Mouth][ERROR] 创建PyAudio对象时出错: {e}")
                        return
                
                # 创建音频流
                print("[Mouth][DEBUG] 开始创建新的音频流")
                self.stream = self.p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=PLAYER_RATE,  # 使用配置的采样率
                    output=True
                )
                
                # 设置所有状态标志
                self.is_playing = True
                self.should_stop = False
                self.buffer_empty.set()
                self.last_audio_time = None
                self.smooth_interrupt = False
                self.interrupt_time = None
                self.fade_out_active = False
                self.fade_out_start_time = None
                self.playback_finished.clear()
                
                # 启动音频播放线程
                if self.audio_thread is not None and self.audio_thread.is_alive():
                    print("[Mouth][WARNING] 检测到旧的音频线程仍在运行，等待其终止")
                    try:
                        self.audio_thread.join(timeout=0.5)
                    except:
                        pass
                
                # 创建新的音频线程
                self.audio_thread = threading.Thread(target=self._play_audio_continuous)
                self.audio_thread.daemon = True
                self.audio_thread.start()
                print("[Mouth][info] 音频输出流已创建，开始持续播放...")
            except Exception as e:
                print(f"[Mouth][ERROR] 创建音频流时出错: {e}")
                self.is_playing = False
                self.stream = None
                
                # 输出更多诊断信息
                try:
                    import sys
                    print(f"[Mouth][DEBUG] Python版本: {sys.version}")
                    print(f"[Mouth][DEBUG] PyAudio版本: {pyaudio.__version__}")
                    print(f"[Mouth][DEBUG] 系统音频设备:")
                    if self.p is not None:
                        for i in range(self.p.get_device_count()):
                            try:
                                device_info = self.p.get_device_info_by_index(i)
                                print(f"  设备 {i}: {device_info['name']}")
                            except:
                                print(f"  设备 {i}: 无法获取信息")
                except Exception as e:
                    print(f"[Mouth][ERROR] 获取音频诊断信息时出错: {e}")
    
    def add_audio_data(self, audio_data):
        """添加音频数据到播放队列"""
        if not self.is_playing:
            self.start_stream()
            
        if self.should_stop and not self.smooth_interrupt:
            return
            
        try:
            if self.playback_finished.is_set():
                self.playback_finished.clear()
                
            wav_bytes = base64.b64decode(audio_data)
            # 直接转换为numpy数组，不进行任何处理
            audio_np = np.frombuffer(wav_bytes, dtype=np.int16)
            
            # 检查平滑打断
            if self.smooth_interrupt and self.interrupt_time:
                current_time = time.time()
                if current_time - self.interrupt_time > self.max_finish_duration:
                    print("[Mouth][DEBUG] 平滑打断已达到最大时间，停止更多音频")
                    return
            
            # 直接添加到队列
            self.audio_queue.put(audio_np.tobytes())
            self.buffer_empty.clear()
            self.last_audio_time = time.time()
        except Exception as e:
            print(f"[Mouth][ERROR] 音频处理错误: {e}")
    
    def _play_audio_continuous(self):
        """后台持续音频播放线程"""
        buffer = b""
        min_buffer_size = 1024  # 减小缓冲区以提高响应速度
        is_initial_buffer = True
        
        try:
            while self.is_playing and (not self.should_stop or self.smooth_interrupt):
                current_time = time.time()
                
                # 处理淡出效果
                if self.fade_out_active:
                    # 如果淡出结束，停止处理
                    if self.fade_out_start_time and (current_time - self.fade_out_start_time >= self.fade_out_duration):
                        print("[Mouth][DEBUG] 淡出效果结束，停止播放")
                        self.should_stop = True
                        break
                
                # 处理超时
                if self.last_audio_time and self.audio_queue.empty():
                    # 如果队列为空且一段时间没有新数据
                    idle_time = current_time - self.last_audio_time
                    
                    if idle_time > 0.5:  # 如果500ms内没有新数据
                        if not self.buffer_empty.is_set():
                            self.buffer_empty.set()
                            print("[Mouth][DEBUG] 缓冲区空闲")
                    
                    if idle_time > 2.0 and not is_initial_buffer:  # 如果2秒内没有新数据
                        print("[Mouth][DEBUG] 音频流空闲超过2秒，认为播放结束")
                        self.playback_finished.set()
                        break
                
                # 获取音频数据
                try:
                    # 使用非阻塞方式获取队列数据
                    chunk_bytes = self.audio_queue.get(block=True, timeout=0.1)
                    is_initial_buffer = False
                    
                    # 重置缓冲区空闲标志
                    if self.buffer_empty.is_set():
                        self.buffer_empty.clear()
                    
                    # 更新最后接收音频的时间
                    self.last_audio_time = current_time
                    
                    # 合并数据到缓冲区
                    buffer += chunk_bytes
                    
                    # 当缓冲区足够大时播放
                    if len(buffer) >= min_buffer_size:
                        if self.stream:
                            # 应用淡出效果
                            if self.fade_out_active and self.fade_out_enabled:
                                # 计算淡出进度
                                if self.fade_out_start_time:
                                    elapsed = current_time - self.fade_out_start_time
                                    if elapsed >= self.fade_out_duration:
                                        # 淡出完成，停止播放
                                        self.should_stop = True
                                        break
                                    
                                    # 计算音量衰减系数 (1.0 -> 0.0)
                                    fade_factor = max(0.0, 1.0 - elapsed / self.fade_out_duration)
                                    
                                    # 应用音量衰减
                                    audio_np = np.frombuffer(buffer, dtype=np.int16)
                                    audio_np = (audio_np * fade_factor).astype(np.int16)
                                    buffer = audio_np.tobytes()
                            
                            # 播放音频
                            try:
                                with self.stream_lock:
                                    if self.stream:
                                        self.stream.write(buffer, exception_on_underflow=False)
                            except Exception as e:
                                print(f"[Mouth][ERROR] 播放音频时出错: {e}")
                            
                            # 清空缓冲区
                            buffer = b""
                
                except queue.Empty:
                    # 队列为空，但缓冲区可能还有数据
                    if buffer and len(buffer) > 0 and self.stream:
                        try:
                            with self.stream_lock:
                                if self.stream:
                                    self.stream.write(buffer, exception_on_underflow=False)
                            buffer = b""
                        except Exception as e:
                            print(f"[Mouth][ERROR] 播放剩余缓冲数据时出错: {e}")
                
                except Exception as e:
                    print(f"[Mouth][ERROR] 音频处理循环出错: {e}")
                    buffer = b""  # 出错时清空缓冲区
                    time.sleep(0.1)
            
            # 处理剩余的缓冲区数据
            if buffer and len(buffer) > 0 and self.stream and not self.should_stop:
                try:
                    with self.stream_lock:
                        if self.stream:
                            self.stream.write(buffer, exception_on_underflow=False)
                except Exception as e:
                    print(f"[Mouth][ERROR] 播放最终缓冲数据时出错: {e}")
            
            print("[Mouth][DEBUG] 音频播放线程结束")
        
        except Exception as e:
            print(f"[Mouth][ERROR] 音频播放线程致命错误: {e}")
            traceback.print_exc()
        finally:
            # 设置播放完成标志
            self.buffer_empty.set()
            self.playback_finished.set()
            print("[Mouth][DEBUG] 音频播放完成")
    
    def is_audio_complete(self):
        """检查是否所有音频数据都已播放完成"""
        # 如果队列为空且流不再活跃，认为播放完成
        return self.audio_queue.empty() and self.buffer_empty.is_set()
    
    def request_smooth_interrupt(self):
        """请求平滑打断，将在当前句子完成后停止"""
        if not self.is_playing:
            return False
            
        print("[Mouth][DEBUG] 请求平滑打断")
        
        self.smooth_interrupt = True
        self.should_stop = True
        self.interrupt_time = time.time()
        return True
    
    def stop_stream(self):
        """正常停止音频播放"""
        if not self.is_playing:
            return
            
        print("[Mouth][DEBUG] 正常停止音频流...")
        
        # 设置停止标志
        self.should_stop = True
        self.is_playing = False
        
        # 清空音频队列
        try:
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()
        except Exception as e:
            print(f"[Mouth][ERROR] 清空音频队列出错: {e}")
        
        # 等待播放线程结束
        if self.audio_thread and self.audio_thread.is_alive():
            try:
                self.audio_thread.join(timeout=1.0)
                if self.audio_thread.is_alive():
                    print("[Mouth][WARNING] 音频线程未能在超时内结束")
            except Exception as e:
                print(f"[Mouth][ERROR] 等待音频线程结束时出错: {e}")
        
        # 关闭音频流
        with self.stream_lock:
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                    self.stream = None
                    print("[Mouth][DEBUG] 音频流已关闭")
                except Exception as e:
                    print(f"[Mouth][ERROR] 关闭音频流时出错: {e}")
                    try:
                        # 额外尝试
                        if self.stream:
                            self.stream.close()
                    except:
                        pass
                    self.stream = None
        
        # 重置所有状态标志
        self.buffer_empty.set()
        self.playback_finished.set()
        self.last_audio_time = None
        self.fade_out_active = False
        self.fade_out_start_time = None
        
        print("[Mouth][info] 音频流已停止")
    
    def stop_with_fadeout(self, fadeout_time=0.1):
        """
        使用快速淡出效果停止音频播放
        
        Args:
            fadeout_time: 淡出时间，以秒为单位，默认0.1秒
        """
        if not self.is_playing:
            return False
            
        print(f"[Mouth][DEBUG] 执行快速淡出 ({fadeout_time}秒)...")
        
        # 设置打断参数
        self.smooth_interrupt = True
        self.should_stop = True
        self.interrupt_time = time.time()
        
        # 设置淡出参数
        self.fade_out_enabled = True
        self.fade_out_duration = fadeout_time  # 使用指定的淡出时间
        self.fade_out_active = True  # 立即开始淡出
        self.fade_out_start_time = time.time()
        
        # 设置最大等待时间略长于淡出时间
        self.max_finish_duration = fadeout_time + 0.05
        
        # 清空音频队列，只处理当前正在播放的片段
        try:
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()
        except Exception as e:
            print(f"[Mouth][ERROR] 清空音频队列时出错: {e}")
            
        return True
    
    def stop_immediately(self):
        """立即停止音频播放并清空队列"""
        # 首先设置所有标志位
        self.should_stop = True
        self.is_playing = False
        self.smooth_interrupt = False
        self.fade_out_active = False
        
        print("[Mouth][DEBUG] 立即停止音频播放...")
        
        # 清空队列
        try:
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()
        except Exception as e:
            print(f"[Mouth][ERROR] 清空音频队列出错(已忽略): {e}")
        
        # 播放一段短暂的静音以平滑过渡
        if self.stream and self.fade_out_enabled:
            try:
                print("[Mouth][DEBUG] 播放短暂静音以实现平滑结束...")
                silent_samples = int(PLAYER_RATE * 0.02)  # 缩短静音时长
                silence = np.zeros(silent_samples, dtype=np.int16)
                
                with self.stream_lock:
                    if self.stream:
                        try:
                            self.stream.write(silence.tobytes(), exception_on_underflow=False)
                        except Exception as e:
                            print(f"[Mouth][ERROR] 播放静音时出错(已忽略): {e}")
            except Exception as e:
                print(f"[Mouth][ERROR] 准备静音时出错(已忽略): {e}")
        
        # 强制停止音频线程
        if self.audio_thread and self.audio_thread.is_alive():
            try:
                self.audio_thread.join(timeout=0.5)  # 减少等待时间
                if self.audio_thread.is_alive():
                    print("[Mouth][WARNING] 音频线程未能在超时内结束")
            except Exception as e:
                print(f"[Mouth][ERROR] 等待音频线程结束时出错: {e}")
        
        # 关闭并释放音频流
        with self.stream_lock:
            if self.stream:
                try:
                    self.stream.stop_stream()
                except Exception as e:
                    print(f"[Mouth][ERROR] 停止音频流时出错(已忽略): {e}")
                
                try:
                    self.stream.close()
                except Exception as e:
                    print(f"[Mouth][ERROR] 关闭音频流时出错(已忽略): {e}")
                
                self.stream = None
        
        # 重置所有状态
        self.buffer_empty.set()
        self.playback_finished.set()
        self.last_audio_time = None
        self.fade_out_active = False
        self.fade_out_start_time = None
        self.interrupt_time = None
        self.audio_thread = None  # 清除音频线程引用
        
        print("[Mouth][info] 音频流已立即停止")
    
    @message_handler
    async def handle_audio_output(self, message: AudioOutputMessage, ctx: MessageContext) -> None:
        """
        处理音频输出消息
        
        Args:
            message: 音频输出消息
            ctx: 消息上下文
        """
        print("\n" + "=" * 50)
        print(f"[Mouth][DEBUG] ===== 收到音频输出消息 =====")
        print(f"[Mouth][DEBUG] 消息类型: {type(message).__name__}")
        print(f"[Mouth][DEBUG] 音频块数量: {len(message.audio_chunks) if message.audio_chunks else 0}")
        print(f"[Mouth][DEBUG] 是否为最终块: {message.is_final}")
        print(f"[Mouth][DEBUG] 消息来源: {ctx.sender if hasattr(ctx, 'sender') else '未知'}")
        print(f"[Mouth][DEBUG] 当前状态: {self.agent_state.name}")
        
        # 检查音频数据的有效性
        if message.audio_chunks:
            for i, chunk in enumerate(message.audio_chunks):
                print(f"[Mouth][DEBUG] 音频块 {i+1}/{len(message.audio_chunks)} 数据长度: {len(chunk.data) if chunk.data else 0}")
        
        print(f"[Mouth][DEBUG] 消息上下文属性: {dir(ctx)}")
        print("=" * 50 + "\n")
        
        if not message.audio_chunks:
            print("[Mouth][warning] 没有音频数据可播放")
            return
        
        # 更新状态为说话中（如果还不是）
        if self.agent_state != AgentState.SPEAKING:
            old_state = self.agent_state
            self.agent_state = AgentState.SPEAKING
            await self.notify_state_change(old_state, self.agent_state, ctx)
        
        # 设置说话状态
        self.is_speaking = True
        
        # 处理音频数据
        print("[Mouth][info] 开始处理音频数据进行播放...")
        await self._play_audio(message, ctx)
        print("[Mouth][info] 音频数据处理完成")
        
        # 如果是最后一个音频块，则结束说话
        if message.is_final and self.is_speaking:
            # 更新状态为空闲
            old_state = self.agent_state
            self.agent_state = AgentState.IDLE
            await self.notify_state_change(old_state, self.agent_state, ctx)
            self.is_speaking = False
            print("[Mouth][info] 所有音频播放完成，状态更新为空闲")
    
    @message_handler
    async def handle_start_speaking(self, message: StartSpeakingMessage, ctx: MessageContext) -> None:
        """
        处理开始说话消息
        
        Args:
            message: 开始说话消息
            ctx: 消息上下文
        """
        print("[Mouth][info] 收到开始说话指令")
        
        # 确保音频流已启动
        if not self.is_playing:
            self.start_stream()
            
        # 更新状态为说话中
        old_state = self.agent_state
        self.agent_state = AgentState.SPEAKING
        await self.notify_state_change(old_state, self.agent_state, ctx)
        self.is_speaking = True
    
    @message_handler
    async def handle_stop_speaking(self, message: StopSpeakingMessage, ctx: MessageContext) -> None:
        """
        处理停止说话消息
        
        Args:
            message: 停止说话消息
            ctx: 消息上下文
        """
        print("[Mouth][info] 收到停止说话指令")
        
        # 停止当前播放
        await self._stop_speaking(smooth=message.smooth)
        
        if self.agent_state == AgentState.SPEAKING:
            # 更新状态为空闲
            old_state = self.agent_state
            self.agent_state = AgentState.IDLE
            await self.notify_state_change(old_state, self.agent_state, ctx)
    
    @message_handler
    async def handle_interrupt(self, message: InterruptMessage, ctx: MessageContext) -> None:
        """
        处理打断消息
        
        Args:
            message: 打断消息
            ctx: 消息上下文
        """
        print("[Mouth][info] 收到打断指令")
        
        # 如果当前正在播放，则进行平滑打断
        if self.is_speaking:
            await self._stop_speaking(smooth=message.smooth)
            
            # 更新状态为空闲
            old_state = self.agent_state
            self.agent_state = AgentState.IDLE
            await self.notify_state_change(old_state, self.agent_state, ctx)
    
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
            print(f"[Mouth][info] 状态变更通知: {old_state.name} -> {new_state.name}")
            
            # 如果某个组件变为SPEAKING，而我们正在SPEAKING，则停止播放
            if (new_state == AgentState.SPEAKING and 
                old_state != AgentState.SPEAKING and 
                self.agent_state == AgentState.SPEAKING and
                message.sender != self.id):
                print("[Mouth][info] 其他组件开始说话，停止当前播放")
                await self._stop_speaking(smooth=True)
                
                # 更新自身状态为空闲
                self.agent_state = AgentState.IDLE
                await self.notify_state_change(AgentState.SPEAKING, AgentState.IDLE, ctx)
    
    @message_handler
    async def handle_llm_response(self, message: LLMResponse, ctx: MessageContext) -> None:
        """
        处理LLM响应消息，进行文本到语音合成
        
        Args:
            message: LLM响应消息
            ctx: 消息上下文
        """
        print(f"[Mouth][DEBUG] 收到LLM响应: {message.text[:50]}..." if len(message.text) > 50 else f"[Mouth][DEBUG] 收到LLM响应: {message.text}")
        
        # 检查是否包含音频数据
        if not message.audio_chunks:
            print("[Mouth][WARNING] LLM响应中没有音频数据，无法播放")
            return
            
        # 更新状态为说话中
        old_state = self.agent_state
        self.agent_state = AgentState.SPEAKING
        await self.notify_state_change(old_state, self.agent_state, ctx)
        
        # 设置说话状态
        self.is_speaking = True
        
        # 创建音频输出消息
        audio_output = AudioOutputMessage(
            audio_chunks=message.audio_chunks,
            is_final=True
        )
        
        # 处理音频播放
        await self._play_audio(audio_output, ctx)
        
        # 播放结束后更新状态
        old_state = self.agent_state
        self.agent_state = AgentState.IDLE
        await self.notify_state_change(old_state, self.agent_state, ctx)
        self.is_speaking = False
        
        print("[Mouth][DEBUG] LLM响应播放完成")
    
    async def _play_audio(self, message: AudioOutputMessage, ctx: MessageContext) -> None:
        """
        播放音频数据
        
        Args:
            message: 音频输出消息
            ctx: 消息上下文
        """
        # 设置说话状态
        self.is_speaking = True
        
        # 创建播放任务
        self.playback_task = asyncio.create_task(self._play_audio_task(message))
        
        # 等待播放任务完成
        try:
            await self.playback_task
        except asyncio.CancelledError:
            print("[Mouth][info] 播放任务被取消")
    
    async def _play_audio_task(self, message: AudioOutputMessage) -> None:
        """播放音频任务"""
        try:
            # 取消已有的播放任务
            if self.playback_task and self.playback_task != asyncio.current_task():
                self.playback_task.cancel()
                try:
                    await self.playback_task
                except asyncio.CancelledError:
                    pass
            
            # 确保先前的资源已清理
            if self.is_playing and self.stream is not None:
                print("[Mouth][DEBUG] 检测到上一次播放可能未完全清理，主动停止")
                self.stop_immediately()
                await asyncio.sleep(0.2)  # 给一点时间让资源释放
                
            # 启动音频流（如果尚未启动）
            if not self.is_playing or self.stream is None:
                print("[Mouth][info] 启动音频流")
                self.start_stream()
            
            # 添加强制重置逻辑
            if self.stream is None:
                print("[Mouth][WARNING] 流启动失败，尝试重新初始化音频系统")
                try:
                    # 尝试重新初始化PyAudio
                    if self.p is not None:
                        try:
                            self.p.terminate()
                        except:
                            pass
                    self.p = pyaudio.PyAudio()
                    self.start_stream()
                    if self.stream is None:
                        print("[Mouth][ERROR] 重新初始化后仍无法创建音频流，无法播放")
                        return
                except Exception as e:
                    print(f"[Mouth][ERROR] 重新初始化音频系统失败: {e}")
                    return
                    
            # 遍历并播放所有数据块
            for chunk in message.audio_chunks:
                # 检查是否需要停止播放
                if not self.is_speaking:
                    print("[Mouth][info] 播放过程中检测到停止标志，中断播放")
                    break
                
                # 检查流是否有效
                if self.stream is None:
                    print("[Mouth][ERROR] 音频流为空，无法播放数据块")
                    self.is_speaking = False
                    break
                    
                # 添加音频数据到播放队列
                self.add_audio_data(chunk.data)
            
            # 如果是最后一组数据块，等待播放完成
            if message.is_final and self.is_speaking:
                print("[Mouth][info] 音频数据全部入队，等待播放完成")
                await self._wait_for_playback_complete()
        
        except asyncio.CancelledError:
            print("[Mouth][info] 播放任务被取消")
            # 确保取消时资源正确释放
            try:
                self.stop_immediately()
            except Exception as e:
                print(f"[Mouth][ERROR] 取消时停止播放出错: {e}")
            raise
        except Exception as e:
            print(f"[Mouth][error] 播放音频时出错: {e}")
            traceback.print_exc()
            # 确保异常时资源正确释放
            try:
                self.stop_immediately()
            except:
                pass
        finally:
            # 确保资源始终被释放
            print("[Mouth][DEBUG] 播放任务结束，确保资源清理")
            if not self.is_speaking and self.is_playing:
                try:
                    self.stop_stream()
                except:
                    # 如果正常停止失败，强制停止
                    try:
                        self.stop_immediately()
                    except:
                        pass
    
    async def _wait_for_playback_complete(self, timeout: float = 30.0) -> None:
        """
        等待音频播放完成
        
        Args:
            timeout: 最大等待时间，默认30秒
        """
        start_time = time.time()
        check_interval = 0.1  # 检查间隔，秒
        
        while self.is_playing:
            # 检查是否超时
            if time.time() - start_time > timeout:
                print(f"[Mouth][warning] 等待播放完成超时({timeout}秒)，强制停止")
                self.stop_immediately()
                break
            
            # 检查播放是否完成
            if (self.audio_queue.qsize() == 0 and 
                self.buffer_empty.is_set() and 
                self.is_audio_complete()):
                print("[Mouth][info] 播放完成")
                break
            
            # 等待一小段时间
            await asyncio.sleep(check_interval)
    
    async def _stop_speaking(self, smooth: bool = True) -> None:
        """
        停止播放
        
        Args:
            smooth: 是否平滑淡出，默认为True
        """
        if not self.is_speaking:
            return
        
        print(f"[Mouth][info] 停止播放(smooth={smooth})")
        self.is_speaking = False
        
        # 停止音频播放
        if self.is_playing:
            if smooth:
                self.stop_with_fadeout(fadeout_time=0.1)
                print("[Mouth][info] 使用平滑淡出停止播放")
            else:
                self.stop_immediately()
                print("[Mouth][info] 立即停止播放")
        
        # 取消播放任务
        if self.playback_task and not self.playback_task.done():
            self.playback_task.cancel()
            try:
                await self.playback_task
            except asyncio.CancelledError:
                pass
    
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
        
        # 通过runtime发送消息，首先检查ctx是否具有必要的属性
        try:
            if hasattr(ctx, 'runtime') and hasattr(ctx, 'topic_id') and ctx.runtime and ctx.topic_id:
                await ctx.runtime.publish_message(
                    state_change,
                    topic_id=ctx.topic_id,
                    sender=self.id
                )
                print(f"[Mouth][DEBUG] 通过ctx.runtime发布状态变更消息: {old_state.name} -> {new_state.name}")
            elif hasattr(self, 'runtime'):
                # 使用self.runtime直接发送状态变更消息
                try:
                    # 创建一个异步任务发送消息
                    async def send_state_change():
                        try:
                            # 向所有代理广播状态变更
                            if hasattr(self.runtime, 'publish_message'):
                                await self.runtime.publish_message(
                                    state_change,
                                    topic_id=autogen_core.DefaultTopicId(),
                                    sender=self.id
                                )
                                print(f"[Mouth][DEBUG] 通过self.runtime广播状态变更消息")
                        except Exception as e:
                            print(f"[Mouth][DEBUG] 广播状态变更消息时出错(已忽略): {e}")
                    
                    # 启动异步任务但不等待结果
                    asyncio.create_task(send_state_change())
                except Exception as e:
                    print(f"[Mouth][DEBUG] 创建状态变更任务时出错(已忽略): {e}")
        except Exception as e:
            print(f"[Mouth][DEBUG] 发送状态变更消息时出错(已忽略): {e}")
        
        print(f"[Mouth][info] 状态变更: {old_state.name} -> {new_state.name}")
