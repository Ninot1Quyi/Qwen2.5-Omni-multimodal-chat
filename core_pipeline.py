import os
import time
import asyncio
import threading
import uuid
import collections
import numpy as np
import queue
import wave
import io
import base64
from enum import Enum, auto
from typing import Dict, List, Callable, Any, Optional, Union
from config import (
    API_KEY, BASE_URL, 
    CHANNELS, AUDIO_FORMAT, RATE, CHUNK, 
    PLAYER_RATE, FADE_OUT_DURATION, MAX_FINISH_DURATION
)

class FrameType(Enum):
    """帧类型枚举"""
    DATA = auto()       # 普通数据帧
    CONTROL = auto()    # 控制帧(优先处理)
    SYSTEM = auto()     # 系统帧(立即处理)

class Frame:
    """表示流水线中传递的数据帧"""
    def __init__(self, type: FrameType, data=None, metadata=None):
        self.type = type
        self.data = data or {}
        self.metadata = metadata or {}
        self.timestamp = time.time()
        self.id = str(uuid.uuid4())
        
    def __str__(self):
        return f"Frame[{self.type.name}]: {', '.join(self.data.keys())}"

class CancellationToken:
    """取消令牌，用于协调任务取消"""
    def __init__(self):
        self._cancelled = threading.Event()
        self._callbacks = []
    
    def cancel(self):
        """触发取消信号"""
        if not self._cancelled.is_set():
            self._cancelled.set()
            for callback in self._callbacks:
                try:
                    callback()
                except Exception as e:
                    print(f"Error in cancellation callback: {e}")
    
    def is_cancelled(self):
        """检查是否已取消"""
        return self._cancelled.is_set()
    
    def register_callback(self, callback):
        """注册取消回调函数"""
        if callback not in self._callbacks:
            self._callbacks.append(callback)
        return lambda: self._callbacks.remove(callback) if callback in self._callbacks else None
    
    def reset(self):
        """重置取消状态"""
        self._cancelled.clear()
        self._callbacks = []

class ProcessorContext:
    """处理器上下文，维护处理链信息和全局状态"""
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.state = {}
        self.cancellation_token = CancellationToken()
        
    def is_cancelled(self):
        """检查是否已取消"""
        return self.cancellation_token.is_cancelled()
    
    def new_session(self):
        """创建新会话"""
        self.session_id = str(uuid.uuid4())
        self.state = {}
        return self.session_id

class ThreadSafeQueue:
    """线程安全的队列封装，适用于多线程环境"""
    def __init__(self, maxsize=0):
        self.queue = queue.Queue(maxsize)
        self.mutex = threading.RLock()
        
    def put(self, item, block=True, timeout=None):
        """添加项到队列"""
        return self.queue.put(item, block, timeout)
        
    def get(self, block=True, timeout=None):
        """从队列获取项"""
        return self.queue.get(block, timeout)
    
    def empty(self):
        """检查队列是否为空"""
        return self.queue.empty()
    
    def clear(self):
        """清空队列"""
        with self.mutex:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except queue.Empty:
                    break
    
    def task_done(self):
        """标记任务完成"""
        self.queue.task_done()
    
    def qsize(self):
        """获取队列大小"""
        return self.queue.qsize()

class ProcessorBase:
    """处理器基类"""
    def __init__(self, name):
        self.name = name
        self.next_processor = None
        self.prev_processor = None
        self.context = None
        self.input_queue = ThreadSafeQueue()
        self.is_running = False
        self.thread = None
        self.lock = threading.RLock()
    
    def set_context(self, context):
        """设置处理器上下文"""
        self.context = context
        
    def set_next(self, processor):
        """设置下一个处理器"""
        self.next_processor = processor
        processor.prev_processor = self
        return processor
        
    def send_downstream(self, frame):
        """向下游发送帧"""
        if self.next_processor:
            # 系统帧优先直接处理，而不是放入队列
            if frame.type == FrameType.SYSTEM:
                self.next_processor.process_frame(frame)
            else:
                self.next_processor.enqueue_frame(frame)
    
    def send_upstream(self, frame):
        """向上游发送帧（用于控制和反馈）"""
        if self.prev_processor:
            # 系统帧总是优先处理
            if frame.type == FrameType.SYSTEM:
                self.prev_processor.process_frame(frame)
            else:
                self.prev_processor.enqueue_frame(frame)
    
    def enqueue_frame(self, frame):
        """将帧放入处理队列"""
        self.input_queue.put(frame)
        
    def process_frame(self, frame):
        """处理单个帧，子类必须实现"""
        raise NotImplementedError("Subclasses must implement process_frame")
    
    def start(self):
        """启动处理器"""
        with self.lock:
            if self.is_running:
                return
                
            self.is_running = True
            self.thread = threading.Thread(target=self._process_loop)
            self.thread.daemon = True
            self.thread.start()
    
    def stop(self):
        """停止处理器"""
        with self.lock:
            if not self.is_running:
                return
                
            self.is_running = False
            self.input_queue.clear()
            
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=1.0)
    
    def _process_loop(self):
        """处理循环"""
        try:
            while self.is_running and (self.context is None or not self.context.is_cancelled()):
                try:
                    # 使用超时，避免无限等待
                    frame = self.input_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                try:
                    # 处理帧
                    self.process_frame(frame)
                except Exception as e:
                    print(f"处理器 {self.name} 处理帧时出错: {e}")
                finally:
                    self.input_queue.task_done()
        
        except Exception as e:
            print(f"处理器 {self.name} 的处理循环出错: {e}")
        finally:
            print(f"处理器 {self.name} 的处理循环已停止")

class SystemEventEmitter:
    """系统事件发射器，用于发布系统事件"""
    def __init__(self, context):
        self.context = context
        self.listeners = {}
    
    def on(self, event_type, callback):
        """注册事件监听器"""
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(callback)
        
        # 返回取消函数
        def cancel():
            if event_type in self.listeners and callback in self.listeners[event_type]:
                self.listeners[event_type].remove(callback)
        return cancel
    
    def emit(self, event_type, data=None):
        """发射事件"""
        if event_type in self.listeners:
            for callback in self.listeners[event_type]:
                try:
                    callback(data)
                except Exception as e:
                    print(f"事件处理回调出错: {e}")

class ConversationPipeline:
    """对话管道 - 集成所有处理器"""
    def __init__(self):
        # 创建处理器上下文
        self.context = ProcessorContext()
        
        # 创建事件发射器
        self.events = SystemEventEmitter(self.context)
        
        # 处理器实例
        self.processors = []
        
        # 状态跟踪
        self.is_running = False
        self.lock = threading.RLock()
    
    def add_processor(self, processor):
        """添加处理器到管道"""
        processor.set_context(self.context)
        self.processors.append(processor)
        return processor
    
    def connect_processors(self):
        """连接所有处理器"""
        for i in range(len(self.processors) - 1):
            self.processors[i].set_next(self.processors[i+1])
    
    def start(self):
        """启动所有处理器"""
        with self.lock:
            if self.is_running:
                return False
                
            self.is_running = True
            self.context.cancellation_token.reset()
            
            # 启动所有处理器
            for processor in self.processors:
                processor.start()
                
            print(f"处理管道已启动，{len(self.processors)}个处理器在运行")
            
            # 发送启动命令到第一个处理器（通常是音频输入处理器）
            if self.processors:
                self.processors[0].process_frame(Frame(
                    FrameType.SYSTEM,
                    {"command": "start"}
                ))
                print("启动命令已发送到第一个处理器")
                
            return True
    
    def stop(self):
        """停止所有处理器"""
        with self.lock:
            if not self.is_running:
                return False
                
            # 触发取消事件
            self.context.cancellation_token.cancel()
            
            # 停止所有处理器
            for processor in reversed(self.processors):
                processor.stop()
                
            self.is_running = False
            print("处理管道已停止")
            return True
    
    def reset(self):
        """重置管道状态"""
        self.stop()
        self.context.new_session()
        print("处理管道已重置")

# -------------------------------------------------------------------
# 音频处理相关的工具函数
# -------------------------------------------------------------------

def int16_to_float32(audio_int16):
    """将int16音频数据转换为float32格式 (-1.0 到 1.0 范围)"""
    return audio_int16.astype(np.float32) / 32768.0

def float32_to_int16(audio_float32):
    """将float32音频数据 (-1.0 到 1.0 范围) 转换为int16格式"""
    return (audio_float32 * 32768.0).astype(np.int16)

def frames_to_wav_base64(frames, channels, sample_width, rate):
    """将音频帧转换为base64编码的WAV数据"""
    wav_buffer = io.BytesIO()
    
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(b''.join(frames))
    
    wav_buffer.seek(0)
    wav_bytes = wav_buffer.read()
    return base64.b64encode(wav_bytes).decode('utf-8') 