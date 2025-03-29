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
from config import (
    API_KEY, BASE_URL, 
    CHANNELS, AUDIO_FORMAT, RATE, CHUNK, RECORD_SECONDS,
    MIN_SPEECH_DURATION, SPEECH_VOLUME_THRESHOLD, 
    NORMAL_VOLUME_THRESHOLD, MIN_POSITIVE_FRAMES, MIN_NEGATIVE_FRAMES,
    PLAYER_RATE, FADE_OUT_DURATION, MAX_FINISH_DURATION, DEBUG
)
from audio_player import AudioPlayer
from audio_recorder import AudioRecorder
from utils import save_wav_file
from enum import Enum, auto

class ChatState(Enum):
    """对话状态枚举类"""
    IDLE = auto()           # 空闲状态
    USER_SPEAKING = auto()  # 用户说话中
    AI_SPEAKING = auto()    # AI说话中
    INTERRUPTED = auto()    # 已被打断

class QwenVoiceChat:
    def __init__(self):
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
        self.audio_player = AudioPlayer()
        self.audio_recorder = AudioRecorder()
        
        # 配置参数
        self.recording_mode = "dynamic"  # 默认使用动态录音模式
        self.recording_seconds = 5
        self.enable_speech_recognition = False
        
        # 线程同步锁
        self.state_lock = threading.RLock()  # 状态锁
        self.session_lock = threading.RLock()  # 会话锁
        
        # 线程同步事件
        self.user_ready_event = threading.Event()      # 用户准备就绪可以说话
        self.user_done_event = threading.Event()       # 用户完成说话
        self.ai_ready_event = threading.Event()        # AI准备就绪可以响应
        self.ai_done_event = threading.Event()         # AI完成响应
        self.session_end_event = threading.Event()     # 会话结束事件
        self.speech_detected_event = threading.Event() # 用户语音检测事件 (新增)
        self.interrupt_event = threading.Event()       # 用于支持外部中断的事件 (新增)
        
        # 会话状态和控制
        self.current_state = ChatState.IDLE
        self.current_session_id = 0
        self.is_running = False
        
        # 音频缓冲区
        self.user_audio_buffer = []
        
        # 状态回调函数
        self.on_state_change = None
        
        # 初始化状态
        self._reset_state()
        
        # 启动麦克风流
        print("正在初始化麦克风流以进行持续监听...")
        self.audio_recorder.start_mic_stream()
        
        # 创建用户语音检测线程
        self.speech_detection_thread = None
    
    def _reset_state(self):
        """重置所有状态"""
        self.user_ready_event.set()       # 初始状态用户可以开始说话
        self.user_done_event.set()        # 初始状态没有待处理的用户语音
        self.ai_ready_event.clear()       # 初始状态AI不准备响应
        self.ai_done_event.set()          # 初始状态AI没有在响应
        self.speech_detected_event.clear() # 初始状态未检测到用户语音
        
        with self.state_lock:
            self.current_state = ChatState.IDLE
            self.user_audio_buffer = []
    
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
    
    def _continuous_speech_detection(self):
        """持续监听语音检测线程，实时监测用户是否开始说话"""
        print("持续语音检测线程已启动...")
        
        while self.is_running and not self.session_end_event.is_set():
            # 等待语音检测
            if self.audio_recorder.speech_detected_event.wait(0.05):
                print("\n[持续检测] 检测到用户开始说话")
                
                # 设置检测事件，通知其他线程
                self.speech_detected_event.set()
                
                # 强制打断AI（如果正在说话）
                if not self.ai_done_event.is_set():
                    print("[用户优先] 打断当前AI响应...")
                    self._interrupt_ai_speech()
                
                # 等待语音检测事件被处理和清除
                while self.speech_detected_event.is_set() and self.is_running:
                    time.sleep(0.1)
                
                # 重置语音检测器状态
                self.audio_recorder.speech_detected_event.clear()
            
            # 短暂休眠
            time.sleep(0.01)
    
    def _user_listening_thread(self):
        """用户语音监听线程，持续监听用户语音输入"""
        print("用户语音监听线程已启动...")
        
        while self.is_running and not self.session_end_event.is_set():
            try:
                # 设置当前状态为等待用户输入
                with self.state_lock:
                    self.current_state = ChatState.IDLE
                
                # 通知状态变化
                if self.on_state_change:
                    self.on_state_change("listening")
                
                print("\n等待用户输入...")
                
                # 准备接收用户输入
                self.audio_recorder.speech_detected_event.clear()
                self.audio_recorder.speech_ended_event.clear()
                
                # 等待检测到用户开始说话
                print("等待语音输入...")
                
                # 等待语音检测事件
                self.speech_detected_event.wait()
                self.speech_detected_event.clear()
                
                # 如果此时退出了，直接继续
                if not self.is_running or self.session_end_event.is_set():
                    continue
                
                print("检测到用户开始说话，开始录音")
                
                # 设置状态为用户正在说话
                with self.state_lock:
                    self.current_state = ChatState.USER_SPEAKING
                    self.user_audio_buffer = []
                
                # 用户开始说话，通知AI停止说话
                if not self.ai_done_event.is_set():
                    print("用户开始说话，请求AI停止...")
                    self._interrupt_ai_speech()
                
                # 设置用户正在说话标志
                self.user_done_event.clear()
                
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
                    self.user_done_event.set()
                    continue
                
                print(f"录音完成，总共捕获 {len(user_audio_frames)} 帧音频数据")
                
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
            self.user_done_event.set()
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
            with self.session_lock:
                self.current_session_id += 1
            
            print("用户输入处理完成，通知AI线程开始响应")
            
            # 设置AI准备就绪事件，通知AI线程可以开始处理
            self.ai_ready_event.set()
            self.ai_done_event.clear()
            
            # 更新状态
            with self.state_lock:
                self.current_state = ChatState.IDLE
            
            # 设置用户已完成发言
            self.user_done_event.set()
            
        except Exception as e:
            print(f"处理用户音频时出错: {e}")
            self.user_done_event.set()  # 确保事件状态正确
    
    def _ai_response_thread(self):
        """AI响应处理线程"""
        print("AI响应处理线程已启动...")
        
        while self.is_running and not self.session_end_event.is_set():
            # 等待用户输入触发AI响应
            if not self.ai_ready_event.is_set():
                self.ai_ready_event.wait(0.1)
                continue
            
            # 确保当前没有音频播放
            self.audio_player.stop_stream()
            
            try:
                # 设置当前状态
                with self.state_lock:
                    self.current_state = ChatState.AI_SPEAKING
                
                # 记录当前会话ID
                with self.session_lock:
                    current_session_id = self.current_session_id
                
                # 通知状态变化
                if self.on_state_change:
                    self.on_state_change("speaking")
                
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
                    # 检查语音检测事件 - 如果用户开始说话立即停止处理
                    if self.speech_detected_event.is_set():
                        print("\n[检测到用户开始说话，停止AI响应]")
                        response_data["interrupted"] = True
                        # 使用快速淡出功能而不是立即停止
                        if self.audio_player.is_playing:
                            self.audio_player.stop_with_fadeout(fadeout_time=0.1)
                            print("[快速响应] 检测到用户开始说话，执行快速淡出")
                        break
                    
                    # 检查会话是否已经过期
                    with self.session_lock:
                        if current_session_id != self.current_session_id:
                            print(f"\n[会话{current_session_id}已过期] 停止接收数据")
                            response_data["interrupted"] = True
                            # 使用快速淡出而不是立即停止
                            if self.audio_player.is_playing:
                                self.audio_player.stop_with_fadeout(fadeout_time=0.1)
                                print("[快速响应] 会话已过期，执行快速淡出")
                            break
                    
                    # 检查当前状态是否已被打断
                    with self.state_lock:
                        if self.current_state == ChatState.INTERRUPTED:
                            print("\n[检测到用户打断，停止数据接收]")
                            response_data["interrupted"] = True
                            # 使用快速淡出而不是立即停止
                            if self.audio_player.is_playing:
                                self.audio_player.stop_with_fadeout(fadeout_time=0.1)
                                print("[快速响应] 用户打断状态，执行快速淡出")
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
                                # 再次检查是否被打断
                                if self.speech_detected_event.is_set():
                                    print("\n[语音块处理中检测到用户开始说话，停止AI响应]")
                                    # 使用快速淡出
                                    if self.audio_player.is_playing:
                                        self.audio_player.stop_with_fadeout(fadeout_time=0.1)
                                        print("[快速响应] 语音块处理中检测到用户开始说话，执行快速淡出")
                                    break
                                
                                # 处理前再次检查会话是否已过期或被打断
                                with self.state_lock:
                                    if self.current_state == ChatState.INTERRUPTED:
                                        print("\n[AI已被打断，停止处理音频]")
                                        # 使用快速淡出
                                        if self.audio_player.is_playing:
                                            self.audio_player.stop_with_fadeout(fadeout_time=0.1)
                                            print("[快速响应] AI已被打断，执行快速淡出")
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
                with self.state_lock:
                    if (not self.speech_detected_event.is_set() and 
                        self.current_state != ChatState.INTERRUPTED and audio_buffer):
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
                with self.state_lock:
                    should_wait_audio = (not self.speech_detected_event.is_set() and
                                      self.current_state != ChatState.INTERRUPTED and
                                      self.audio_player.is_playing)
                
                if should_wait_audio:
                    print("\n数据流完成，等待音频播放结束...")
                    max_wait = 30.0
                    wait_start = time.time()
                    
                    while True:
                        # 检查用户是否开始说话 - 立即停止等待
                        if self.speech_detected_event.is_set():
                            print("\n[等待播放时检测到用户开始说话，中断播放]")
                            # 使用快速淡出而不是立即停止
                            self.audio_player.stop_with_fadeout(fadeout_time=0.1)
                            print("[快速响应] 等待播放时检测到用户开始说话，执行快速淡出")
                            break
                        
                        # 检查是否应该继续等待
                        with self.state_lock:
                            if (self.current_state == ChatState.INTERRUPTED or 
                                not self.audio_player.is_playing or 
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
            
            except Exception as e:
                print(f"\nAI响应处理出错: {e}")
            
            finally:
                # 停止音频播放
                if self.audio_player.is_playing:
                    print("\n确保音频播放已停止...")
                    self.audio_player.stop_stream()
                
                # 重置状态
                self.ai_ready_event.clear()
                self.ai_done_event.set()
                
                with self.state_lock:
                    self.current_state = ChatState.IDLE
                
                # 通知状态变化回调
                if self.on_state_change:
                    self.on_state_change("listening")
        
    def _interrupt_ai_speech(self):
        """打断AI说话"""
        if self.ai_done_event.is_set():
            return  # AI未在说话，无需打断
        
        print("\n[执行打断] 停止AI响应...")
        
        # 设置状态为已打断
        with self.state_lock:
            self.current_state = ChatState.INTERRUPTED
        
        # 请求立即停止音频播放 - 使用快速淡出
        if self.audio_player.is_playing:
            # 设置快速淡出时间为0.1秒，确保快速平滑过渡
            self.audio_player.stop_with_fadeout(fadeout_time=0.1)
            print("[快速淡出] 在0.1秒内平滑结束AI语音")
        
        # 不需要等待AI完全结束，AI线程会检测到打断状态并自行结束
    
    def start_conversation(self):
        """启动对话系统"""
        print("正在启动与Qwen-Omni的语音对话...")
        
        self.show_system_info()
        
        record_choice = input("\n选择录音模式: 1=固定时长, 2=动态 (默认2): ")
        self.recording_mode = "fixed" if record_choice.strip() == '1' else "dynamic"
        print(f"\n已选择{'固定时长' if self.recording_mode == 'fixed' else '动态'}录音模式")
        
        if self.recording_mode == "fixed":
            try:
                sec = input("请输入录音时长（秒）(默认: 5): ")
                if sec.strip():
                    self.recording_seconds = max(1, min(10, int(sec)))
                print(f"录音时长设置为: {self.recording_seconds}秒")
            except ValueError:
                print("输入无效，使用默认时长5秒")
        
        print("您可以在AI说话时打断它。")
        print("检测到静音时将自动停止录音。")
        
        # 重置消息历史，不再添加欢迎消息
        self.messages = []
        
        # 重置状态
        self._reset_state()
        self.current_session_id = 0
        self.is_running = True
        self.session_end_event.clear()
        
        try:
            # 启动持续语音检测线程
            self.speech_detection_thread = threading.Thread(target=self._continuous_speech_detection)
            self.speech_detection_thread.daemon = True
            self.speech_detection_thread.start()
            
            # 创建AI响应线程
            ai_thread = threading.Thread(target=self._ai_response_thread)
            ai_thread.daemon = True
            ai_thread.start()
            
            # 创建用户输入线程
            user_thread = threading.Thread(target=self._user_listening_thread)
            user_thread.daemon = True
            user_thread.start()
            
            # 主线程等待结束信号
            while True:
                try:
                        time.sleep(0.5)
                except KeyboardInterrupt:
                    print("\n检测到键盘中断，正在结束对话...")
                    break
                
        except Exception as e:
            print(f"主线程出错: {e}")
        finally:
            # 设置结束标志
            self.is_running = False
            self.session_end_event.set()
            
            # 等待线程结束
            if self.speech_detection_thread and self.speech_detection_thread.is_alive():
                self.speech_detection_thread.join(timeout=2.0)
            if ai_thread.is_alive():
                ai_thread.join(timeout=2.0)
            if user_thread.is_alive():
                user_thread.join(timeout=2.0)
            
            # 释放资源
            self.audio_recorder.stop_mic_stream()
            self.audio_player.close()
            print("所有资源已释放，程序已终止。")
    
    def close(self):
        """清理资源"""
        self.is_running = False
        self.session_end_event.set()
        self.interrupt_event.set()  # 设置中断事件
        self.audio_recorder.close()
        self.audio_player.close()