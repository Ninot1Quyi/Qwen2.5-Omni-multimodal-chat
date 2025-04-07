"""
Ears组件
负责音频输入和语音活动检测(VAD)
"""

import asyncio
import time
import traceback
import threading
import os
import collections
import pyaudio
import numpy as np
import onnxruntime
import base64
from typing import Optional, Tuple, Any, List, Dict

import autogen_core
from autogen_core import RoutedAgent, message_handler, MessageContext

from .messages import (
    AudioInputMessage, 
    SpeechDetectedMessage,
    StartListeningMessage,
    StopListeningMessage,
    StateChangeMessage
)
from .state import AgentState
from config import (
    AUDIO_FORMAT, CHANNELS, RATE, CHUNK,
    MIN_SPEECH_DURATION, SPEECH_VOLUME_THRESHOLD,
    NORMAL_VOLUME_THRESHOLD, MIN_POSITIVE_FRAMES,
    MIN_NEGATIVE_FRAMES
)
from utils import convert_frames_to_wav, wav_to_base64

# VAD模型参数
VAD_THRESHOLD = 0.6  # 从0.5提高到0.6，提高检测阈值
END_BUFFER_FRAMES = 10  # 从1增加到10，约等于0.3秒
MIN_NEG_FRAMES_FOR_ENDING = 8  # 从6增加到8帧，需要更多连续静音帧
MAX_SPEECH_DURATION = 180.0  # 最长允许180秒语音
PRE_BUFFER_FRAMES = int(1.0 * RATE / CHUNK)  # 从0.5秒增加到1.0秒的前置缓冲
SPEECH_CONFIRM_FRAMES = 2  # 需要连续5帧检测到语音才开始录音
PRE_DETECTION_BUFFER_SIZE = int(2.0 * RATE / CHUNK)  # 2秒的预检测缓冲


class Ears(RoutedAgent):
    """负责音频输入和语音检测，集成了AudioRecorder功能"""
    
    def __init__(self, description: str = "Ears Agent - 负责音频输入和语音检测"):
        """初始化Ears组件"""
        super().__init__(description)
        self.agent_state = AgentState.IDLE
        self.is_running = False
        self.debug = True
        
        # 音频录制器相关属性
        self.p = pyaudio.PyAudio()
        self.mic_stream = None
        self.is_mic_active = False
        self.mic_lock = threading.Lock()
        
        # 初始化VAD模型
        self.onnx_model = None
        self.vad_initialized = False
        
        # VAD状态
        self.state = None
        self.context = None
        self.sr = RATE
        
        # 持续监听
        self.continuous_listening = True
        self.listening_thread = None
        
        # 长循环缓冲区 - 保存最近180秒的音频数据
        max_buffer_seconds = MAX_SPEECH_DURATION
        max_buffer_frames = int(max_buffer_seconds * RATE / CHUNK)
        self.long_buffer = collections.deque(maxlen=max_buffer_frames)
        
        # 语音索引记录
        self.speech_start_index = -1  # 语音开始的索引位置
        self.speech_end_index = -1    # 语音结束的索引位置
        self.current_buffer_index = 0 # 当前缓冲区索引位置
        
        # 标准预缓冲区（仅用于VAD检测）
        self.circular_buffer = collections.deque(maxlen=PRE_DETECTION_BUFFER_SIZE)
        self.mic_data_buffer = []
        
        # 语音检测状态变量
        self.first_speech_frame_index = -1  # 首次检测到语音的帧索引
        
        # 语音结束检测参数
        self.end_silence_frames = 45  # 约1.4秒的静音判定(增加到45)
        self.end_buffer_frames = END_BUFFER_FRAMES  # 使用新的缓冲帧设置
        
        # 事件
        self.speech_detected_event = threading.Event()
        self.speech_ended_event = threading.Event()
        
        # 录音模式
        self.recording_mode = "dynamic"  # 默认使用动态录音模式
        self.recording_seconds = 5  # 固定录音时长
    
    @classmethod
    def _handles_types(cls):
        """重写以解决AnyType序列化的问题"""
        # 先使用父类方法获取所有类型
        types = super()._handles_types()
        # 排除AnyType
        return [t for t in types if t[0] != autogen_core._type_helpers.AnyType]
    
    async def initialize(self) -> None:
        """初始化Ears组件和音频录制器"""
        # 初始化VAD模型
        try:
            model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                     "models/silero_vad.onnx")
            print(f"加载Silero VAD ONNX模型: {model_path}")
            self.onnx_model = onnxruntime.InferenceSession(model_path)
            self.reset_vad_state()
            self.vad_initialized = True
        except Exception as e:
            print(f"[Ears][ERROR] 加载VAD模型失败: {e}")
            traceback.print_exc()
        
        print("[Ears][info] Ears初始化完成")
    
    async def start(self) -> None:
        """启动Ears组件和mic流"""
        self.is_running = True
        
        # 启动麦克风流
        self.start_mic_stream()
        
        print("[Ears][info] Ears启动完成")
    
    async def stop(self) -> None:
        """停止Ears组件"""
        self.is_running = False
        
        # 停止麦克风流
        self.stop_mic_stream()
        
        print("[Ears][info] Ears已停止")
    
    async def close(self) -> None:
        """关闭并清理Ears资源"""
        # 停止所有活动
        await self.stop()
        
        # 清理PyAudio
        try:
            self.p.terminate()
        except Exception as e:
            print(f"[Ears][ERROR] 终止PyAudio时出错: {e}")
        
        print("[Ears][info] Ears已关闭")
    
    def reset_vad_state(self, batch_size=1):
        """重置VAD状态"""
        # 完全按照原始AudioRecorder的实现
        self.state = np.zeros((2, batch_size, 128), dtype=np.float32)
        self.context = np.zeros(0, dtype=np.float32)
        self.sr = RATE
    
    def vad_predict(self, audio_data):
        """使用ONNX模型进行VAD预测
        
        Args:
            audio_data: 浮点音频数据 [-1.0, 1.0]
            
        Returns:
            bool: 是否检测到语音
        """
        if not self.vad_initialized:
            return False
            
        # 确保输入形状正确 (固定为512采样点，适用于16kHz采样率)
        if len(audio_data) != 512:
            if self.debug:
                print(f"[Ears][WARNING] 音频样本数量 {len(audio_data)} 不为512，结果可能不正确")
        
        # 重塑输入为模型期望的形状 [batch_size, seq_len]
        audio = np.array(audio_data, dtype=np.float32).reshape(1, -1)
        
        # 准备ONNX输入 - 完全与原始AudioRecorder保持一致
        ort_inputs = {
            "input": audio,
            "state": self.state,
            "sr": np.array(self.sr, dtype=np.int64)
        }
        
        # 执行推理
        try:
            ort_outs = self.onnx_model.run(None, ort_inputs)
            
            # 更新状态，返回格式为 [out, state]
            out, self.state = ort_outs
            
            # 应用VAD阈值
            speech_prob = out[0][0]
            return speech_prob >= VAD_THRESHOLD
        except Exception as e:
            print(f"[Ears][ERROR] VAD预测出错: {e}")
            return False
    
    def start_mic_stream(self):
        """启动麦克风流进行持续监听"""
        with self.mic_lock:
            if self.is_mic_active:
                return
                
            try:
                # 创建麦克风流
                self.mic_stream = self.p.open(
                    format=AUDIO_FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK
                )
                
                self.is_mic_active = True
                print("麦克风流已启动")
                
                # 启动持续监听线程
                self.continuous_listening = True
                self.listening_thread = threading.Thread(target=self._continuous_listening_thread)
                self.listening_thread.daemon = True
                self.listening_thread.start()
                print("持续监听线程已启动")
                
                # 重置相关变量
                self.long_buffer.clear()
                self.circular_buffer.clear()
                self.mic_data_buffer = []
                self.current_buffer_index = 0
                self.speech_start_index = -1
                self.speech_end_index = -1
                self.first_speech_frame_index = -1
                
                print("后台持续监听已启动")
            except Exception as e:
                print(f"[Ears][ERROR] 启动麦克风流出错: {e}")
                self.is_mic_active = False
                self.mic_stream = None
    
    def stop_mic_stream(self):
        """停止麦克风流"""
        self.continuous_listening = False
        
        # 等待线程结束
        if self.listening_thread and self.listening_thread.is_alive():
            try:
                self.listening_thread.join(timeout=2.0)
            except Exception:
                pass
        
        with self.mic_lock:
            if self.mic_stream:
                try:
                    self.mic_stream.stop_stream()
                    self.mic_stream.close()
                    self.mic_stream = None
                    self.is_mic_active = False
                    print("麦克风流已安全停止")
                except Exception as e:
                    print(f"[Ears][ERROR] 停止麦克风流出错: {e}")
                    self.mic_stream = None
                    self.is_mic_active = False
    
    def is_speech_detected(self):
        """检查是否检测到语音活动"""
        return self.speech_detected_event.is_set()
    
    def _continuous_listening_thread(self):
        """后台持续监听线程"""
        print("[Ears][info] 启动持续语音检测...")
        
        # 为子线程创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 重置VAD状态
            self.reset_vad_state()
            
            # 重置事件
            self.speech_detected_event.clear()
            self.speech_ended_event.clear()
            
            # 重置语音检测状态
            self.speech_start_index = -1
            self.speech_end_index = -1
            self.first_speech_frame_index = -1
            
            # 正常检测参数
            is_speech = False
            speech_frames = 0
            silence_frames = 0
            negative_frames = 0
            positive_frames = 0
            last_vad_time = time.time()
            is_recording = False
            recording_started_time = None
            waiting_for_end_confirmation = False
            end_confirmation_buffer_count = 0
            
            # 采样点索引计数
            idx = 0
            
            # 获取音频归一化窗口大小
            frame_window_size = 512  # Silero VAD输入窗口大小
            
            while self.continuous_listening and self.is_mic_active:
                if self.mic_stream is None:
                    time.sleep(0.1)
                    continue
                    
                try:
                    # 读取音频数据
                    audio_data = self.mic_stream.read(CHUNK, exception_on_overflow=False)
                    
                    # 将原始字节数据转换为int16数组
                    audio_int16 = np.frombuffer(audio_data, dtype=np.int16)
                    
                    # 归一化到[-1, 1]范围用于VAD
                    audio_float32 = audio_int16.astype(np.float32) / 32768.0
                    
                    # 将音频帧添加到长期缓冲区
                    with self.mic_lock:
                        self.long_buffer.append(audio_int16)
                        self.current_buffer_index += 1
                    
                    # 为了VAD计算，重新采样到512个点
                    if len(audio_float32) != frame_window_size:
                        # 使用重采样方法获取期望大小的窗口
                        if len(audio_float32) > frame_window_size:
                            audio_vad = audio_float32[:frame_window_size]
                        else:
                            audio_vad = np.pad(audio_float32, (0, frame_window_size - len(audio_float32)), 'constant')
                    else:
                        audio_vad = audio_float32
                    
                    # 进行VAD检测
                    has_speech = self.vad_predict(audio_vad)
                    
                    # 根据VAD结果更新状态
                    idx += 1
                    if has_speech:
                        positive_frames += 1
                        negative_frames = 0
                        
                        # 如果检测到语音但尚未开始录制
                        if not is_recording:
                            speech_frames += 1
                            
                            # 仅当达到确认阈值时才开始录音
                            if speech_frames >= SPEECH_CONFIRM_FRAMES:
                                # 首帧检测
                                if self.first_speech_frame_index == -1:
                                    self.first_speech_frame_index = idx
                                    print(f"[首帧检测] 检测到首个语音帧，索引: {idx}")
                                
                                # 设置语音检测事件
                                if not self.speech_detected_event.is_set():
                                    self.speech_detected_event.set()
                                    print("检测到语音，开始录音...")
                                
                                # 确定语音开始位置
                                with self.mic_lock:
                                    # 计算实际开始位置（包括前置缓冲区）
                                    buffer_length = len(self.long_buffer)
                                    pre_buffer_size = min(PRE_BUFFER_FRAMES, buffer_length)
                                    
                                    # 设置语音开始索引和首帧索引
                                    self.speech_start_index = max(0, self.current_buffer_index - pre_buffer_size)
                                    
                                    print(f"记录语音开始索引: {self.speech_start_index} (首帧索引: {self.first_speech_frame_index}, 当前索引: {idx})")
                                
                                is_recording = True
                                recording_started_time = time.time()
                                waiting_for_end_confirmation = False
                                end_confirmation_buffer_count = 0
                    else:
                        negative_frames += 1
                        silence_frames += 1
                        speech_frames = 0
                        
                        if is_recording:
                            # 检查语音是否应该结束
                            speech_duration = time.time() - recording_started_time if recording_started_time else 0
                            
                            # 如果连续静音足够长，尝试结束录音
                            if negative_frames >= MIN_NEG_FRAMES_FOR_ENDING:
                                if not waiting_for_end_confirmation:
                                    waiting_for_end_confirmation = True
                                    print(f"检测到可能的语音结束，等待确认... [负帧:{negative_frames}, 静音:{silence_frames}, 时长:{speech_duration:.2f}s]")
                                
                                # 使用缓冲区确认结束
                                if waiting_for_end_confirmation:
                                    end_confirmation_buffer_count += 1
                                    print(f"[确认中] 缓冲帧:{end_confirmation_buffer_count}/{self.end_buffer_frames}, 静音帧:{silence_frames}, 负帧:{negative_frames}")
                                    
                                    if end_confirmation_buffer_count >= self.end_buffer_frames:
                                        # 确认语音结束
                                        with self.mic_lock:
                                            self.speech_end_index = self.current_buffer_index
                                            
                                        # 设置语音结束事件
                                        if not self.speech_ended_event.is_set():
                                            self.speech_ended_event.set()
                                            
                                        print(f"语音结束，持续时间: {speech_duration:.2f}秒")
                                        print(f"记录语音结束索引: {self.speech_end_index}")
                                        
                                        # 重置状态
                                        is_recording = False
                                        waiting_for_end_confirmation = False
                                        
                                        # 处理录制的音频
                                        loop.run_until_complete(self._process_recorded_audio())
                            
                            # 检查是否超过最大录音时长
                            if speech_duration > MAX_SPEECH_DURATION:
                                print(f"超过最大录音时长 ({MAX_SPEECH_DURATION}秒)，强制结束录音")
                                
                                with self.mic_lock:
                                    self.speech_end_index = self.current_buffer_index
                                
                                # 设置语音结束事件
                                if not self.speech_ended_event.is_set():
                                    self.speech_ended_event.set()
                                    
                                # 重置状态
                                is_recording = False
                                waiting_for_end_confirmation = False
                                
                                # 处理录制的音频
                                loop.run_until_complete(self._process_recorded_audio())
                    
                    # 简单的CPU使用控制
                    time.sleep(0.005)
                    
                except Exception as e:
                    print(f"[Ears][ERROR] 监听过程中出错: {e}")
                    traceback.print_exc()
                    time.sleep(0.1)
        except Exception as e:
            print(f"[Ears][ERROR] 持续监听线程致命错误: {e}")
            traceback.print_exc()
        finally:
            # 关闭事件循环
            loop.close()
            print("持续监听线程已退出")
    
    async def _process_recorded_audio(self):
        """处理录制的音频并发送到Brain组件"""
        try:
            # 获取语音帧
            frames = self.get_speech_frames()
            
            if frames and len(frames) > 0:
                # 转换为WAV格式
                wav_bytes = convert_frames_to_wav(frames, self.p, CHANNELS, AUDIO_FORMAT, RATE)
                
                # 将二进制WAV数据转换为base64编码的字符串
                audio_data_base64 = base64.b64encode(wav_bytes).decode('utf-8')
                
                # 创建AudioInputMessage
                audio_msg = AudioInputMessage(audio_data=audio_data_base64, format="wav")
                
                # 获取话题ID和消息上下文
                topic_id = autogen_core.DefaultTopicId()
                
                # 我们不再需要创建模拟上下文，直接使用runtime.send_message
                
                # 查找Brain组件
                try:
                    # 使用正确的API查找Brain组件
                    brain_id = None
                    
                    # 尝试直接通过类型获取Brain组件
                    try:
                        brain_id = await self.runtime.get("Brain")
                        print(f"[Ears][DEBUG] 通过类型找到Brain组件: {brain_id}")
                    except Exception as e:
                        print(f"[Ears][DEBUG] 通过类型获取Brain组件失败: {e}")
                        
                        # 如果通过类型获取失败，尝试遍历实例化的Agent
                        if hasattr(self.runtime, '_instantiated_agents'):
                            print("[Ears][DEBUG] 尝试遍历已实例化的Agent")
                            for agent_id, agent in self.runtime._instantiated_agents.items():
                                if agent.__class__.__name__ == "Brain":
                                    brain_id = agent_id
                                    print(f"[Ears][DEBUG] 找到Brain组件: {brain_id}")
                                    break
                    
                    if brain_id is not None:
                        print(f"[Ears][DEBUG] 尝试直接发送音频到Brain: {brain_id}")
                        print(f"[Ears][DEBUG] 音频消息类型: {type(audio_msg).__name__}")
                        print(f"[Ears][DEBUG] 音频数据长度: {len(audio_msg.audio_data)}")
                        print(f"[Ears][DEBUG] 音频格式: {audio_msg.format}")
                        
                        # 打印消息处理器信息
                        try:
                            brain_agent = await self.runtime._get_agent(brain_id)
                            if hasattr(brain_agent, '_handlers'):
                                handler_types = []
                                for handler_type in brain_agent._handlers.keys():
                                    try:
                                        handler_types.append(handler_type.__name__ if hasattr(handler_type, '__name__') else str(handler_type))
                                    except:
                                        handler_types.append(str(handler_type))
                                print(f"[Ears][DEBUG] Brain消息处理器类型: {handler_types}")
                        except Exception as e:
                            print(f"[Ears][WARNING] 无法获取Brain组件的消息处理器信息: {e}")
                        
                        try:
                            # 直接发送音频消息
                            print("[Ears][DEBUG] 开始发送音频消息...")
                            print(f"[Ears][DEBUG] 音频消息大小: {len(audio_msg.audio_data)} bytes")
                            
                            # 使用非阻塞的方式直接发送消息给Brain
                            print("[Ears][DEBUG] 使用非阻塞方式直接发送音频消息...")
                            
                            # 创建一个异步任务来发送消息，这样不会阻塞主线程
                            async def send_audio_message():
                                try:
                                    # 尝试发送消息，但不等待响应
                                    send_task = asyncio.create_task(
                                        self.runtime.send_message(
                                            audio_msg,
                                            recipient=brain_id,
                                            sender=self.id
                                        )
                                    )
                                    
                                    # 设置超时，但不阻塞主线程
                                    try:
                                        await asyncio.wait_for(send_task, timeout=3.0)
                                        print("[Ears][DEBUG] 音频消息已成功发送到Brain")
                                    except asyncio.TimeoutError:
                                        print("[Ears][DEBUG] 发送超时，但任务仍在后台运行")
                                except Exception as e:
                                    print(f"[Ears][ERROR] 发送音频消息时出错: {e}")
                                    import traceback
                                    traceback.print_exc()
                            
                            # 启动异步任务但不等待它完成
                            asyncio.create_task(send_audio_message())
                            print("[Ears][DEBUG] 已启动异步发送任务")
                            print("[Ears][DEBUG] 音频消息已成功发送到Brain")
                            
                            # 等待一些时间让Brain处理消息
                            print("[Ears][DEBUG] 等待Brain处理消息...")
                            await asyncio.sleep(2.0)
                            print("[Ears][DEBUG] 等待结束")
                        except asyncio.TimeoutError:
                            print("[Ears][WARNING] 发送音频超时，但消息可能仍在处理中")
                        except Exception as e:
                            print(f"[Ears][ERROR] 发送音频时出错: {e}")
                            traceback.print_exc()
                    else:
                        print("[Ears][ERROR] 未找到Brain组件，无法发送音频")
                except Exception as e:
                    print(f"[Ears][ERROR] 发送音频到Brain组件时出错: {e}")
                    traceback.print_exc()
            else:
                print("[Ears][WARNING] 未获取到有效的语音帧，不发送音频")
        except Exception as e:
            print(f"[Ears][ERROR] 处理录制音频时出错: {e}")
            traceback.print_exc()
    
    def get_speech_frames(self):
        """获取语音片段的音频帧
        
        Returns:
            list: 语音音频帧列表
        """
        with self.mic_lock:
            # 计算长循环缓冲区的当前大小
            buffer_size = len(self.long_buffer)
            
            # 如果没有足够的数据，返回空列表
            if buffer_size == 0 or self.speech_start_index < 0 or self.speech_end_index < 0:
                return []
            
            # 计算实际的开始和结束位置
            # 添加更多调试信息
            print(f"原始索引 - 开始: {self.speech_start_index}, 结束: {self.speech_end_index}, 当前: {self.current_buffer_index}")
            
            # 修改相对索引计算方法，确保能获取到正确的语音片段
            # 使用当前索引减去缓冲区大小作为基准点
            current_offset = self.current_buffer_index - buffer_size
            relative_start = (self.speech_start_index - current_offset) % buffer_size
            relative_end = (self.speech_end_index - current_offset) % buffer_size
            
            # 确保结束索引不为0，除非故意设置
            if relative_end == 0 and self.speech_end_index > 0:
                relative_end = buffer_size
            
            if self.debug:
                print(f"相对索引 - 开始: {relative_start}, 结束: {relative_end}, 缓冲区大小: {buffer_size}")
            
            # 收集帧数据
            frames = []
            
            # 确保结束索引大于开始索引
            if relative_end <= relative_start:
                print(f"警告: 结束索引({relative_end})小于或等于开始索引({relative_start})，调整为使用缓冲区末尾")
                relative_end = buffer_size
            
            try:
                # 直接获取片段
                if relative_start < buffer_size and relative_end <= buffer_size:
                    frames = list(self.long_buffer)[relative_start:relative_end]
                    print(f"从缓冲区索引 {relative_start} 到 {relative_end} 获取了 {len(frames)} 帧")
                else:
                    print(f"索引超出范围 - 开始: {relative_start}, 结束: {relative_end}, 缓冲区大小: {buffer_size}")
                    frames = []
            except Exception as e:
                print(f"获取语音帧时出错: {e}")
                import traceback
                traceback.print_exc()
                frames = []
            
            if self.debug:
                print(f"获取到语音帧: {len(frames)}帧")
            
            # 重置语音索引
            self.speech_start_index = -1
            self.speech_end_index = -1
            self.first_speech_frame_index = -1
            
            return frames
    
    def set_recording_mode(self, mode: str, seconds: int = 5) -> None:
        """
        设置录音模式
        
        Args:
            mode: 录音模式，"dynamic"或"fixed"
            seconds: 固定录音时的时长，默认5秒
        """
        self.recording_mode = mode
        if mode == "fixed":
            self.recording_seconds = max(1, min(10, seconds))
        print(f"[Ears][DEBUG] 录音模式已设置为: {mode}" + (f", 时长: {seconds}秒" if mode == "fixed" else ""))
    
    async def get_available_microphones(self) -> List[Dict[str, Any]]:
        """获取可用麦克风列表"""
        mics = []
        try:
            for i in range(self.p.get_device_count()):
                dev_info = self.p.get_device_info_by_index(i)
                # 仅添加具有输入通道的设备
                if dev_info["maxInputChannels"] > 0:
                    mics.append({
                        "index": i,
                        "name": dev_info["name"],
                        "channels": dev_info["maxInputChannels"],
                        "sample_rate": int(dev_info["defaultSampleRate"])
                    })
        except Exception as e:
            print(f"[Ears][ERROR] 获取麦克风列表时出错: {e}")
        
        return mics
    
    @message_handler
    async def handle_start_listening(self, message: StartListeningMessage, ctx: MessageContext) -> None:
        """
        处理开始监听消息
        
        Args:
            message: 开始监听消息
            ctx: 消息上下文
        """
        print("[Ears][DEBUG] 收到开始监听指令，准备启动语音监听...")
        
        # 更新状态为监听中
        old_state = self.agent_state
        self.agent_state = AgentState.LISTENING
        await self.notify_state_change(old_state, self.agent_state, ctx)
        print("[Ears][DEBUG] 状态已更新为LISTENING")
        
        # 重置语音检测事件
        self.speech_detected_event.clear()
        self.speech_ended_event.clear()
    
    @message_handler
    async def handle_stop_listening(self, message: StopListeningMessage, ctx: MessageContext) -> None:
        """
        处理停止监听消息
        
        Args:
            message: 停止监听消息
            ctx: 消息上下文
        """
        print("[Ears][DEBUG] 收到停止监听指令")
        
        # 如果正在录音，则停止录音
        if self.agent_state == AgentState.LISTENING:
            # 更新状态为空闲
            old_state = self.agent_state
            self.agent_state = AgentState.IDLE
            await self.notify_state_change(old_state, self.agent_state, ctx)
            print("[Ears][DEBUG] 状态已更新为IDLE")
    
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
            print(f"[Ears][DEBUG] 状态变更通知: {old_state.name} -> {new_state.name}")
            self.agent_state = new_state
    
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
        
        # 通过runtime发送消息
        if ctx.runtime and ctx.topic_id:
            await ctx.runtime.publish_message(
                state_change,
                topic_id=ctx.topic_id,
                sender=self.id
            )
        
        print(f"[Ears][info] 状态变更: {old_state.name} -> {new_state.name}")
