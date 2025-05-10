import os
import time
import threading
from openai import OpenAI
import base64
from queue import Queue
from typing import Dict, List, Callable, Any
from config import (
    API_KEY, BASE_URL, DEBUG
)
from mouth import Mouth
from ears import Ears
from enum import Enum, auto
from core_pipeline import ConversationPipeline
from processors import AIProcessor, EventProcessor

class SystemEvent(Enum):
    """系统事件枚举类，用于事件驱动的状态转换"""
    USER_SPEECH_STARTED = auto()
    USER_SPEECH_ENDED = auto()
    AI_RESPONSE_STARTED = auto()
    AI_RESPONSE_ENDED = auto()
    USER_INTERRUPT = auto()
    SESSION_ENDED = auto()

class ChatState(Enum):
    """对话状态枚举类"""
    IDLE = auto()           # 空闲状态
    USER_SPEAKING = auto()  # 用户说话中
    AI_SPEAKING = auto()    # AI说话中
    INTERRUPTED = auto()    # 已被打断

class Agent:
    def __init__(self, gui_mode=True, debug=False, on_state_change=None):
        """初始化语音对话代理
        
        Args:
            gui_mode: 是否使用GUI模式，默认为True
            debug: 是否启用调试模式，打印详细日志
            on_state_change: 状态变化回调函数，用于GUI模式更新UI
        """
        if not API_KEY:
            raise ValueError("API密钥未设置")
        
        # 配置参数
        self.gui_mode = gui_mode
        self.debug = debug
        
        # 状态回调函数
        self.on_state_change = on_state_change
        
        # 新的流处理管道
        self.pipeline = ConversationPipeline()
        
        # 初始化处理器
        self._setup_processors()
        
        # 会话控制
        self.is_running = False
        self.session_end_event = threading.Event()
        
    def _setup_processors(self):
        """设置处理器管道"""
        # 创建处理器实例
        audio_input = Ears()
        ai_processor = AIProcessor()
        audio_output = Mouth()
        event_processor = EventProcessor(on_state_change=self.on_state_change)
        
        # 添加处理器到管道
        self.pipeline.add_processor(audio_input)
        self.pipeline.add_processor(ai_processor)
        self.pipeline.add_processor(audio_output)
        self.pipeline.add_processor(event_processor)
        
        # 连接处理器
        self.pipeline.connect_processors()
        
        # 保存引用以便直接访问
        self.audio_input = audio_input
        self.ai_processor = ai_processor
        self.audio_output = audio_output
        self.event_processor = event_processor
    
    def print_conversation_history(self):
        """打印对话历史"""
        messages = self.ai_processor.messages
        if not messages:
            print("对话历史为空")
            return
        
        print("\n===== 对话历史 =====")
        for i, msg in enumerate(messages):
            role = msg["role"]
            if role == "user":
                has_audio = any(content.get("type") == "input_audio" for content in msg["content"])
                has_text = any(content.get("type") == "text" for content in msg["content"])
                print(f"{i+1}. 用户: ", end="")
                if has_text:
                    for content in msg["content"]:
                        if content.get("type") == "text":
                            print(f"{content['text']}")
                            break
                elif has_audio:
                    print("[语音输入]")
                else:
                    print("[未知输入]")
            elif role == "assistant":
                print(f"{i+1}. AI: ", end="")
                if isinstance(msg["content"], list) and msg["content"] and "text" in msg["content"][0]:
                    print(f"{msg['content'][0]['text']}")
                else:
                    print("[未知响应]")
        print("===================\n")
    
    def show_system_info(self):
        """显示系统信息"""
        print("\n===== 系统信息 =====")
        mics = self.audio_input.get_available_microphones()
        print("\n可用麦克风:")
        for i, mic in enumerate(mics):
            print(f"{i+1}. 设备ID: {mic['index']} - {mic['name']} (通道数: {mic['channels']})")
        print("\n===================")
    
    def start(self):
        """启动语音对话系统"""
        print("正在启动与Qwen-Omni的语音对话...")
        
        if not self.gui_mode:
            self.show_system_info()
        
        # 重置消息历史
        self.ai_processor.messages = []
        self.ai_processor.full_transcript = ""
        
        # 重置状态
        self.is_running = True
        self.session_end_event.clear()
        
        try:
            # 启动管道
            self.pipeline.start()
            
            print("语音对话系统已启动，等待用户输入...")
            return True
        
        except Exception as e:
            print(f"启动语音对话时出错: {e}")
            self.is_running = False
            return False
    
    def stop(self):
        """停止语音对话系统"""
        if not self.is_running:
            return False
        
        try:
            print("正在停止语音对话...")
            # 立即标记为非运行状态
            self.is_running = False
            # 设置会话结束事件
            self.session_end_event.set()
            
            # 停止所有音频播放
            if self.audio_output.is_playing:
                print("立即停止所有音频播放...")
                self.audio_output.stop_immediately()
            
            # 停止麦克风流
            print("停止麦克风流和所有监听线程...")
            self.audio_input.stop_mic_stream()
            
            # 等待麦克风流完全停止
            time.sleep(0.2)
            
            # 停止处理管道
            self.pipeline.stop()
            
            # 通知状态变化回调
            if self.on_state_change:
                self.on_state_change("idle")
            
            print("语音对话已完全停止")
            return True
        
        except Exception as e:
            print(f"停止语音对话时出错: {e}")
            return False
    
    def close(self):
        """清理资源"""
        self.stop()
        self.audio_input.close()
        self.audio_output.close()