import os
import time
import threading
from openai import OpenAI
import base64
import tempfile
import datetime
import shutil
import io
import wave
from queue import Queue
from typing import Dict, List, Callable, Any, Optional
from config import (
    API_KEY, BASE_URL, 
    CHANNELS, AUDIO_FORMAT, RATE, CHUNK, RECORD_SECONDS,
    MIN_SPEECH_DURATION, SPEECH_VOLUME_THRESHOLD, 
    NORMAL_VOLUME_THRESHOLD, MIN_POSITIVE_FRAMES, MIN_NEGATIVE_FRAMES,
    PLAYER_RATE, FADE_OUT_DURATION, MAX_FINISH_DURATION, DEBUG
)
from mouth import Mouth
from ears import Ears
from utils import save_wav_file
from enum import Enum, auto

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

class StateManager:
    """状态管理器，负责集中管理状态转换和事件通信"""
    
    def __init__(self, initial_state=ChatState.IDLE, debug=False):
        self._state = initial_state
        self._state_lock = threading.RLock()
        self._event_queue = Queue()
        self._running = False
        self._processor_thread = None
        self._session_id = 0
        self._session_lock = threading.RLock()
        self._debug = debug
        
        # 状态和事件监听器
        self._state_listeners: List[Callable[[ChatState, ChatState], None]] = []
        self._event_listeners: Dict[SystemEvent, List[Callable[[Any], None]]] = {
            event: [] for event in SystemEvent
        }
        
    def set_debug(self, debug):
        """设置调试模式"""
        self._debug = debug
    
    def _debug_log(self, message):
        """只在调试模式打印日志"""
        if self._debug:
            print(f"[StateManager] {message}")
        
    def start(self):
        """启动状态管理器"""
        if self._running:
            return
            
        self._running = True
        self._processor_thread = threading.Thread(target=self._process_events)
        self._processor_thread.daemon = True
        self._processor_thread.start()
        
    def stop(self):
        """停止状态管理器"""
        self._running = False
        self.post_event(SystemEvent.SESSION_ENDED)
        if self._processor_thread and self._processor_thread.is_alive():
            self._processor_thread.join(timeout=2.0)
            
    def _process_events(self):
        """事件处理线程：处理事件队列并执行状态转换"""
        import traceback
        from queue import Empty
        
        while self._running:
            try:
                # 从队列获取事件，设置超时避免CPU空转
                try:
                    event, data = self._event_queue.get(timeout=0.1)
                except Empty:
                    # 队列为空是正常情况，继续等待
                    continue
                
                # 处理获取到的事件
                if event not in SystemEvent:
                    print(f"警告: 收到未知事件类型 {event}")
                    self._event_queue.task_done()
                    continue
                
                # 处理事件
                self._handle_event(event, data)
                self._event_queue.task_done()
                
            except Exception as e:
                # 只在运行时记录错误
                if self._running:
                    print(f"事件处理错误: {str(e)}")
                    print(f"错误详情: {traceback.format_exc()}")
                    
                    # 尝试标记任务完成，避免队列阻塞
                    try:
                        self._event_queue.task_done()
                    except:
                        pass  # 忽略重复的task_done调用可能引发的异常
    
    def _handle_event(self, event: SystemEvent, data: Any = None):
        """处理单个事件并执行相应的状态转换"""
        old_state = new_state = None
        
        with self._state_lock:
            old_state = self._state
            
            # 根据当前状态和接收到的事件确定下一个状态
            if event == SystemEvent.USER_SPEECH_STARTED:
                if self._state in [ChatState.IDLE, ChatState.AI_SPEAKING]:
                    new_state = ChatState.USER_SPEAKING
            
            elif event == SystemEvent.USER_SPEECH_ENDED:
                if self._state == ChatState.USER_SPEAKING:
                    new_state = ChatState.IDLE
            
            elif event == SystemEvent.AI_RESPONSE_STARTED:
                if self._state == ChatState.IDLE:
                    new_state = ChatState.AI_SPEAKING
            
            elif event == SystemEvent.AI_RESPONSE_ENDED:
                if self._state in [ChatState.AI_SPEAKING, ChatState.INTERRUPTED]:
                    new_state = ChatState.IDLE
            
            elif event == SystemEvent.USER_INTERRUPT:
                if self._state == ChatState.AI_SPEAKING:
                    new_state = ChatState.INTERRUPTED
            
            # 如果状态发生变化，更新状态并通知监听器
            if new_state and new_state != old_state:
                self._state = new_state
                # 解锁后通知，避免死锁
        
        # 通知事件监听器
        self._notify_event_listeners(event, data)
        
        # 如果状态已变化，通知状态监听器
        if new_state and new_state != old_state:
            self._notify_state_listeners(old_state, new_state)
    
    def post_event(self, event: SystemEvent, data: Any = None):
        """发布事件到事件队列"""
        if not self._running:
            self._debug_log(f"警告: 状态管理器未运行，忽略事件 {event.name}")
            return False
            
        if event not in SystemEvent:
            self._debug_log(f"警告: 尝试发布未知事件 {event}")
            return False
            
        try:
            self._event_queue.put((event, data))
            self._debug_log(f"事件已入队: {event.name}")
            return True
        except Exception as e:
            import traceback
            print(f"事件发布错误({event.name}): {str(e)}")
            print(f"错误详情: {traceback.format_exc()}")
            return False
        
    def get_state(self) -> ChatState:
        """获取当前状态"""
        with self._state_lock:
            return self._state
            
    def new_session(self) -> int:
        """创建新会话，返回会话ID"""
        with self._session_lock:
            self._session_id += 1
            return self._session_id
    
    def get_session_id(self) -> int:
        """获取当前会话ID"""
        with self._session_lock:
            return self._session_id
    
    def add_state_listener(self, listener: Callable[[ChatState, ChatState], None]):
        """添加状态变化监听器"""
        self._state_listeners.append(listener)
        
    def add_event_listener(self, event: SystemEvent, listener: Callable[[Any], None]):
        """添加事件监听器"""
        self._event_listeners[event].append(listener)
        
    def _notify_state_listeners(self, old_state: ChatState, new_state: ChatState):
        """通知所有状态监听器"""
        for listener in self._state_listeners:
            try:
                listener(old_state, new_state)
            except Exception as e:
                import traceback
                print(f"状态监听器错误: {str(e)}")
                print(f"监听器错误详情: {traceback.format_exc()}")
                
    def _notify_event_listeners(self, event: SystemEvent, data: Any = None):
        """通知特定事件的监听器"""
        if event not in self._event_listeners:
            return
            
        for listener in self._event_listeners[event]:
            try:
                listener(data)
            except Exception as e:
                import traceback
                print(f"事件'{event.name}'监听器错误: {str(e)}")
                print(f"监听器错误详情: {traceback.format_exc()}")

class Agent:
    def __init__(self, gui_mode=True, recording_mode="dynamic", recording_seconds=5, 
                 enable_speech_recognition=False, on_state_change=None, debug=False):
        """初始化语音对话代理
        
        Args:
            gui_mode: 是否使用GUI模式，默认为True
            recording_mode: 录音模式，'dynamic'或'fixed'，默认为'dynamic'
            recording_seconds: 固定录音模式的录音时长，默认为5秒
            enable_speech_recognition: 是否启用语音识别，默认为False
            on_state_change: 状态变化回调函数，用于GUI模式更新UI
            debug: 是否启用调试模式，打印详细日志
        """
        if not API_KEY:
            raise ValueError("API密钥未设置")
        
        # OpenAI客户端初始化
        self.client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
        )
        
        # 对话历史
        self.messages = []
        self.full_transcript = ""
        
        # 音频处理组件
        self.audio_player = Mouth()
        self.audio_recorder = Ears()
        
        # 配置参数
        self.gui_mode = gui_mode
        self.recording_mode = recording_mode
        self.recording_seconds = recording_seconds
        self.enable_speech_recognition = enable_speech_recognition
        self.debug = debug
        
        # 状态管理器
        self.state_manager = StateManager(debug=debug)
        
        # 线程
        self.speech_detection_thread = None
        self.ai_thread = None
        self.user_thread = None
        
        # 会话控制
        self.is_running = False
        self.session_end_event = threading.Event()
        
        # 音频缓冲区
        self.user_audio_buffer = []
        
        # 状态回调函数
        self.on_state_change = on_state_change
        
        # 设置状态变化监听器
        self.state_manager.add_state_listener(self._on_state_changed)
        
        # 设置事件监听器
        self.state_manager.add_event_listener(SystemEvent.USER_INTERRUPT, self._on_user_interrupt)
        
        # 启动状态管理器
        self.state_manager.start()
        
    def _on_state_changed(self, old_state: ChatState, new_state: ChatState):
        """状态变化回调"""
        print(f"状态变化: {old_state.name} -> {new_state.name}")
        
        # 检查是否是用户主动结束会话
        if not self.is_running:
            print("用户主动结束会话，直接回到初始状态")
            # 如果用户主动结束会话，直接返回初始状态，忽略中间状态
            if self.on_state_change:
                # 不让中间状态影响 UI，直接跳转到初始状态
                self.on_state_change("initial")
            return
        
        # 正常状态变化处理
        # 如果在中断状态下变为 IDLE，不触发 UI 更新，因为这可能是在停止过程中
        if old_state == ChatState.INTERRUPTED and new_state == ChatState.IDLE:
            print("从中断状态变为空闲状态，跳过 UI 更新以避免闪烁")
            return
            
        if self.on_state_change:
            if new_state == ChatState.IDLE:
                self.on_state_change("listening")
            elif new_state == ChatState.USER_SPEAKING:
                self.on_state_change("user_speaking")
            elif new_state == ChatState.AI_SPEAKING:
                self.on_state_change("speaking")
            elif new_state == ChatState.INTERRUPTED:
                # 如果 is_running 已经为 False，则跳过中断状态的 UI 更新
                if self.is_running:
                    self.on_state_change("interrupted")
                else:
                    print("已停止运行，跳过中断状态的 UI 更新")
    
    def _on_user_interrupt(self, data=None):
        """用户打断事件处理"""
        if self.audio_player.is_playing:
            print("[打断事件] 执行立即停止...")
            self.audio_player.stop_immediately()  # 使用立即停止而不是淡出
            
    def _continuous_speech_detection(self):
        """持续监听语音检测线程，实时监测用户是否开始说话"""
        print("持续语音检测线程已启动...")
        
        while self.is_running and not self.session_end_event.is_set():
            # 等待语音检测
            if self.audio_recorder.speech_detected_event.wait(0.05):
                print("\n[持续检测] 检测到用户开始说话")
                
                # 发布用户开始说话事件
                self.state_manager.post_event(SystemEvent.USER_SPEECH_STARTED)
                
                # 重置语音检测器状态
                self.audio_recorder.speech_detected_event.clear()
                
            # 短暂休眠
            time.sleep(0.01)
    
    def _user_listening_thread(self):
        """用户语音监听线程，持续监听用户语音输入"""
        print("用户语音监听线程已启动...")
        
        while self.is_running and not self.session_end_event.is_set():
            try:
                # 等待检测到用户开始说话
                current_state = self.state_manager.get_state()
                
                # 只在IDLE或USER_SPEAKING状态时监听
                if current_state not in [ChatState.IDLE, ChatState.USER_SPEAKING]:
                    time.sleep(0.1)
                    continue
                
                print("\n等待用户输入...")
                
                # 准备接收用户输入
                self.audio_recorder.speech_detected_event.clear()
                self.audio_recorder.speech_ended_event.clear()
                
                # 等待检测到用户开始说话
                print("等待语音输入...")
                
                # 如果状态是IDLE，等待用户开始说话
                if current_state == ChatState.IDLE:
                    self.audio_recorder.speech_detected_event.wait()
                    # 发布用户开始说话事件
                    self.state_manager.post_event(SystemEvent.USER_SPEECH_STARTED)
                
                # 如果此时退出了，直接继续
                if not self.is_running or self.session_end_event.is_set():
                    continue
                
                print("检测到用户开始说话，开始录音")
                
                # 重置音频缓冲区
                self.user_audio_buffer = []
                
                # 等待用户语音结束
                print("正在录制用户语音...")
                speech_end_detected = self.audio_recorder.speech_ended_event.wait(180.0)  # 最长等待180秒
                
                if not speech_end_detected:
                    print("用户语音录制超时，强制结束")
                
                # 从循环缓冲区获取完整的用户语音
                user_audio_frames = self.audio_recorder.get_speech_frames()
                
                # 判断是否有足够的音频数据
                if len(user_audio_frames) < 10:  # 判断是否只有少量帧
                    print("捕获的语音太短，忽略此次输入")
                    continue
                
                print(f"录音完成，总共捕获 {len(user_audio_frames)} 帧音频数据")
                
                # 发布用户结束说话事件
                self.state_manager.post_event(SystemEvent.USER_SPEECH_ENDED, user_audio_frames)
                
                # 处理捕获的音频
                self._process_user_audio(user_audio_frames)
                
            except Exception as e:
                print(f"用户语音监听线程出错: {e}")
            
            # 短暂休眠，避免CPU过度使用
            time.sleep(0.05)
    
    def _process_user_audio(self, audio_frames):
        """处理用户音频数据"""
        if not audio_frames:
            print("没有音频数据可处理")
            return
        
        try:
            print(f"处理用户音频，总帧数: {len(audio_frames)}")
            
            # 计算音频长度
            audio_duration = len(audio_frames) * CHUNK / RATE
            print(f"用户音频长度: {audio_duration:.2f}秒")
            
            audio_base64 = ""
            
            if DEBUG:
                # 在DEBUG模式下才创建临时文件
                temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
                
                # 保存音频文件
                save_wav_file(
                    temp_file, 
                    audio_frames, 
                    self.audio_recorder.p, 
                    CHANNELS, 
                    AUDIO_FORMAT, 
                    RATE
                )
                
                # 保存一个永久副本到recordings目录
                recordings_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
                if not os.path.exists(recordings_dir):
                    os.makedirs(recordings_dir)
                
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                saved_file = os.path.join(recordings_dir, f"user_audio_{timestamp}.wav")
                
                # 复制文件
                shutil.copy2(temp_file, saved_file)
                print(f"用户音频已保存到: {saved_file}")
                
                # 从文件读取编码
                with open(temp_file, 'rb') as f:
                    wav_bytes = f.read()
                    audio_base64 = base64.b64encode(wav_bytes).decode('utf-8')
                
                # 删除临时文件
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            else:
                # 非DEBUG模式下，直接从内存中生成WAV数据并编码为base64
                print(f"DEBUG模式未开启，直接从内存编码音频")
                
                # 创建一个内存中的WAV文件
                wav_buffer = io.BytesIO()
                
                # 使用wave模块写入WAV头和数据
                with wave.open(wav_buffer, 'wb') as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(self.audio_recorder.p.get_sample_size(AUDIO_FORMAT))
                    wf.setframerate(RATE)
                    wf.writeframes(b''.join(audio_frames))
                
                # 获取完整的WAV数据并编码
                wav_buffer.seek(0)
                wav_bytes = wav_buffer.read()
                audio_base64 = base64.b64encode(wav_bytes).decode('utf-8')
            
            # 创建用户消息
            user_message = {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": f"data:audio/wav;base64,{audio_base64}",
                            "format": "wav",
                        },
                    }
                ],
            }
            
            # 添加到对话历史
            self.messages.append(user_message)
            
            # 分配新的会话ID
            new_session_id = self.state_manager.new_session()
            
            print(f"用户输入处理完成，通知AI线程开始响应 (会话ID: {new_session_id})")
            
            # 触发AI响应开始事件
            self.state_manager.post_event(SystemEvent.AI_RESPONSE_STARTED)
            
        except Exception as e:
            print(f"处理用户音频时出错: {e}")
    
    def _ai_response_thread(self):
        """AI响应处理线程"""
        print("AI响应处理线程已启动...")
        
        while self.is_running and not self.session_end_event.is_set():
            try:
                # 只在IDLE或AI_SPEAKING状态处理
                current_state = self.state_manager.get_state()
                current_session_id = self.state_manager.get_session_id()
                
                # 如果不是AI_SPEAKING状态，继续等待
                if current_state != ChatState.AI_SPEAKING:
                    time.sleep(0.1)
                    continue
                
                # 确保当前没有音频播放
                self.audio_player.stop_stream()
                
                print("\n正在发送请求到Qwen-Omni进行处理...")
                
                response_data = {
                    "ai_text": "",
                    "has_audio": False,
                    "current_transcript": "",
                    "interrupted": False
                }
                
                # 准备保存AI音频，仅在DEBUG模式下保存
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                ai_audio_file = None
                ai_audio_buffer = None
                
                if DEBUG:
                    recordings_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
                    if not os.path.exists(recordings_dir):
                        os.makedirs(recordings_dir)
                    
                    ai_audio_file = os.path.join(recordings_dir, f"ai_response_{timestamp}.wav")
                    # 初始化AI音频缓冲区
                    ai_audio_buffer = bytearray()
                
                # 创建API请求
                completion = self.client.chat.completions.create(
                    model="qwen-omni-turbo",
                    messages=self.messages,
                    modalities=["text", "audio"],
                    audio={"voice": "Chelsie", "format": "wav"},
                    stream=True,
                    stream_options={"include_usage": True},
                )
                
                # 准备音频缓冲和状态
                audio_buffer = ""
                audio_chunk_count = 0
                is_first_audio = True
                
                # 处理流式响应
                for chunk in completion:
                    # 首先检查是否应该继续运行
                    if not self.is_running or self.session_end_event.is_set():
                        print("\n[检测到会话结束信号] 立即停止AI响应")
                        response_data["interrupted"] = True
                        # 立即停止播放
                        if self.audio_player.is_playing:
                            self.audio_player.stop_immediately()
                        break
                    
                    # 检查当前状态是否允许继续处理
                    current_state = self.state_manager.get_state()
                    if current_state in [ChatState.USER_SPEAKING, ChatState.INTERRUPTED]:
                        print(f"\n[当前状态为{current_state.name}，停止AI响应]")
                        response_data["interrupted"] = True
                        # 立即停止播放
                        if self.audio_player.is_playing:
                            self.audio_player.stop_immediately()
                        break
                    
                    # 检查会话是否已经过期
                    if current_session_id != self.state_manager.get_session_id():
                        print(f"\n[会话{current_session_id}已过期] 停止接收数据")
                        response_data["interrupted"] = True
                        # 立即停止播放
                        if self.audio_player.is_playing:
                            self.audio_player.stop_immediately()
                        break
                    
                    # 处理响应内容
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        
                        if hasattr(delta, "content") and delta.content:
                            response_data["ai_text"] += delta.content
                            print(delta.content, end="", flush=True)
                        
                        if hasattr(delta, "audio") and delta.audio:
                            response_data["has_audio"] = True
                            
                            if "transcript" in delta.audio:
                                transcript = delta.audio["transcript"]
                                if transcript:
                                    response_data["current_transcript"] += transcript
                            
                            if "data" in delta.audio:
                                # 再次检查是否应该继续运行
                                if not self.is_running or self.session_end_event.is_set():
                                    print("\n[语音块处理中检测到会话结束信号] 立即停止AI响应")
                                    # 立即停止播放
                                    if self.audio_player.is_playing:
                                        self.audio_player.stop_immediately()
                                    break
                                
                                # 检查当前状态
                                current_state = self.state_manager.get_state()
                                if current_state in [ChatState.USER_SPEAKING, ChatState.INTERRUPTED]:
                                    print(f"\n[语音块处理中检测到状态为{current_state.name}，停止AI响应]")
                                    # 立即停止播放
                                    if self.audio_player.is_playing:
                                        self.audio_player.stop_immediately()
                                    break
                                
                                # 解码base64数据并处理
                                audio_data = delta.audio["data"]
                                
                                # 仅在DEBUG模式下收集音频数据以保存到文件
                                if DEBUG and ai_audio_file is not None:
                                    audio_bytes = base64.b64decode(audio_data)
                                    ai_audio_buffer.extend(audio_bytes)
                                
                                # 立即处理音频数据
                                if not is_first_audio:
                                    self.audio_player.add_audio_data(audio_data)
                                else:
                                    audio_buffer += audio_data
                                    audio_chunk_count += 1
                                    
                                    if audio_chunk_count >= 2:  # 减少初始缓冲
                                        is_first_audio = False
                                        self.audio_player.start_stream()
                                        print("\n开始音频播放...")
                                        if audio_buffer:
                                            self.audio_player.add_audio_data(audio_buffer)
                                            audio_buffer = ""
                
                # 处理最后的音频缓冲
                current_state = self.state_manager.get_state()
                if current_state not in [ChatState.USER_SPEAKING, ChatState.INTERRUPTED] and audio_buffer:
                    self.audio_player.add_audio_data(audio_buffer)
                
                # 保存合并的AI音频到文件（仅在DEBUG模式下）
                if DEBUG and ai_audio_file and ai_audio_buffer:
                    try:
                        with open(ai_audio_file, 'wb') as f:
                            f.write(ai_audio_buffer)
                        print(f"AI响应音频已保存到: {ai_audio_file}")
                    except Exception as e:
                        print(f"保存AI音频失败: {e}")
                elif not DEBUG:
                    print(f"DEBUG模式未开启，跳过保存AI响应音频")
                
                # 等待音频播放完成，除非被打断
                current_state = self.state_manager.get_state()
                should_wait_audio = (current_state not in [ChatState.USER_SPEAKING, ChatState.INTERRUPTED] and
                                    self.audio_player.is_playing)
                
                if should_wait_audio:
                    print("\n数据流完成，等待音频播放结束...")
                    max_wait = 30.0
                    wait_start = time.time()
                    
                    while True:
                        # 首先检查是否应该继续运行
                        if not self.is_running or self.session_end_event.is_set():
                            print("\n[等待播放时检测到会话结束信号] 立即停止播放")
                            # 立即停止播放
                            self.audio_player.stop_immediately()
                            break
                            
                        # 检查当前状态
                        current_state = self.state_manager.get_state()
                        if current_state in [ChatState.USER_SPEAKING, ChatState.INTERRUPTED]:
                            print(f"\n[等待播放时状态为{current_state.name}，立即中断播放]")
                            # 立即停止播放
                            self.audio_player.stop_immediately()
                            break
                        
                        # 检查是否应该继续等待
                        if (not self.audio_player.is_playing or 
                            self.audio_player.playback_finished.is_set() or
                            time.time() - wait_start >= max_wait):
                            break
                        
                        # 检查是否有足够的队列数据
                        if (self.audio_player.audio_queue.qsize() == 0 and 
                            self.audio_player.buffer_empty.is_set() and 
                            not self.audio_player.is_audio_complete()):
                            time.sleep(0.5)
                            if self.audio_player.is_audio_complete():
                                print("\n音频播放已完成")
                                break
                        
                        # 短暂等待
                        self.audio_player.playback_finished.wait(0.1)
                    
                    if time.time() - wait_start >= max_wait:
                        print(f"\n等待音频播放超时({max_wait}秒)，强制停止")
                        self.audio_player.stop_immediately()
                
                # 记录AI回复
                if response_data["current_transcript"]:
                    self.full_transcript += response_data["current_transcript"] + " "
                    print(f"\n当前回复转录: {response_data['current_transcript']}")
                    
                    assistant_message = {
                        "role": "assistant",
                        "content": [{"type": "text", "text": response_data["current_transcript"]}]
                    }
                    self.messages.append(assistant_message)
                elif response_data["ai_text"]:
                    assistant_message = {
                        "role": "assistant",
                        "content": [{"type": "text", "text": response_data["ai_text"]}]
                    }
                    self.messages.append(assistant_message)
                
                # 打印对话历史
                self.print_conversation_history()
                
                # 通知AI响应结束
                self.state_manager.post_event(SystemEvent.AI_RESPONSE_ENDED)
            
            except Exception as e:
                print(f"\nAI响应处理出错: {e}")
                # 尝试恢复到IDLE状态
                self.state_manager.post_event(SystemEvent.AI_RESPONSE_ENDED)
            
            finally:
                # 停止音频播放
                if self.audio_player.is_playing:
                    print("\n确保音频播放已停止...")
                    self.audio_player.stop_stream()
                
                # 短暂等待
                time.sleep(0.1)
    
    def show_system_info(self):
        """显示系统信息"""
        print("\n===== 系统信息 =====")
        mics = self.audio_recorder.get_available_microphones()
        print("\n可用麦克风:")
        for i, mic in enumerate(mics):
            print(f"{i+1}. 设备ID: {mic['index']} - {mic['name']} (通道数: {mic['channels']})")
        
        print(f"\n录音模式: {'固定时长' if self.recording_mode == 'fixed' else '动态'}")
        if self.recording_mode == 'fixed':
            print(f"录音时长: {self.recording_seconds}秒")
        
        print("\n===================")
    
    def print_conversation_history(self):
        """打印对话历史"""
        if not self.messages:
            print("对话历史为空")
            return
        
        print("\n===== 对话历史 =====")
        for i, msg in enumerate(self.messages):
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
    
    def start(self):
        """启动语音对话系统
        
        这是简化的接口，用于启动语音对话系统
        """
        print("正在启动与Qwen-Omni的语音对话...")
        
        if not self.gui_mode:
            self.show_system_info()
        
        # 重置消息历史
        self.messages = []
        
        # 重置状态
        self.is_running = True
        self.session_end_event.clear()
        
        try:
            # 启动麦克风流
            print("正在启动麦克风流以进行持续监听...")
            self.audio_recorder.start_mic_stream()
            # 启动持续语音检测线程
            self.speech_detection_thread = threading.Thread(target=self._continuous_speech_detection)
            self.speech_detection_thread.daemon = True
            self.speech_detection_thread.start()
            
            # 创建AI响应线程
            self.ai_thread = threading.Thread(target=self._ai_response_thread)
            self.ai_thread.daemon = True
            self.ai_thread.start()
            
            # 创建用户输入线程
            self.user_thread = threading.Thread(target=self._user_listening_thread)
            self.user_thread.daemon = True
            self.user_thread.start()
            
            # 如果不是GUI模式，则等待用户输入结束
            if not self.gui_mode:
                print("您可以在AI说话时打断它。")
                print("检测到静音时将自动停止录音。")
                
                # 主线程等待结束信号
                while True:
                    try:
                        time.sleep(0.5)
                    except KeyboardInterrupt:
                        print("\n检测到键盘中断，正在结束对话...")
                        break
            
            return True
        
        except Exception as e:
            print(f"启动语音对话时出错: {e}")
            self.is_running = False
            return False
    
    def stop(self):
        """停止语音对话系统
        
        这是简化的接口，用于停止语音对话系统
        """
        if not self.is_running:
            return False
        
        try:
            print("正在停止语音对话...")
            # 立即标记为非运行状态
            self.is_running = False
            # 设置会话结束事件
            self.session_end_event.set()
            
            # 发送事件来切换状态
            # 首先发送用户打断事件，这会将状态切换为 INTERRUPTED
            self.state_manager.post_event(SystemEvent.USER_INTERRUPT)
            # 然后发送会话结束事件
            self.state_manager.post_event(SystemEvent.SESSION_ENDED)
            
            # 立即停止音频播放
            if self.audio_player.is_playing:
                print("立即停止所有音频播放...")
                self.audio_player.stop_immediately()
            
            # 无条件停止麦克风流
            print("停止麦克风流和所有监听线程...")
            self.audio_recorder.stop_mic_stream()
            
            # 等待麦克风流完全停止
            time.sleep(0.2)
            
            # 创建新的会话 ID，确保正在运行的流式响应会被中断
            with self.state_manager._session_lock:
                self.state_manager._session_id += 1
                print(f"创建新的会话 ID: {self.state_manager._session_id}")
            
            # 等待一小段时间，让线程有机会响应
            time.sleep(0.5)
            
            # 强制终止线程
            if self.speech_detection_thread and self.speech_detection_thread.is_alive():
                print("等待语音检测线程结束...")
                self.speech_detection_thread.join(timeout=1.0)
            
            if self.ai_thread and self.ai_thread.is_alive():
                print("等待AI响应线程结束...")
                self.ai_thread.join(timeout=1.0)
            
            if self.user_thread and self.user_thread.is_alive():
                print("等待用户线程结束...")
                self.user_thread.join(timeout=1.0)
                
            # 清空用户音频缓冲区
            self.user_audio_buffer = []
            
            # 停止状态管理器
            self.state_manager.stop()
            
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
        self.audio_recorder.close()
        self.audio_player.close()
        self.state_manager.stop()