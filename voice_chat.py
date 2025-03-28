import os
import time
import threading
import speech_recognition as sr
from openai import OpenAI
from config import API_KEY, BASE_URL
from audio_player import AudioPlayer
from audio_recorder import AudioRecorder

class QwenVoiceChat:
    def __init__(self):
        if not API_KEY:
            raise ValueError("API密钥未设置")
        
        self.client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
        )
        
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.8
        self.recognizer.non_speaking_duration = 0.5
        
        self.messages = []
        self.is_ai_speaking = False
        
        self.interrupt_event = threading.Event()
        self.stream_stopped_event = threading.Event()
        self.audio_player = AudioPlayer()
        self.audio_recorder = AudioRecorder()
        
        self.recording_mode = "dynamic"  # 默认使用动态录音模式
        self.recording_seconds = 5
        self.full_transcript = ""
        self.enable_speech_recognition = False
        
        # 中断相关状态
        self.record_after_interrupt = False
        self.interrupt_speaking = False
        self.interrupt_speech_start_time = None
        self.speech_active_after_interrupt = False
        
        # 启动麦克风流
        print("正在初始化麦克风流以进行持续监听...")
        self.audio_recorder.start_mic_stream()
    
    def show_system_info(self):
        print("\n===== 系统信息 =====")
        mics = self.audio_recorder.get_available_microphones()
        print("\n可用麦克风:")
        for i, mic in enumerate(mics):
            print(f"{i+1}. 设备ID: {mic['index']} - {mic['name']} (通道数: {mic['channels']})")
        
        print(f"\n语音识别配置:")
        print(f"  - 能量阈值: {self.recognizer.energy_threshold}")
        print(f"  - 动态能量阈值: {self.recognizer.dynamic_energy_threshold}")
        print(f"  - 暂停阈值: {self.recognizer.pause_threshold}秒")
        print(f"  - 非说话持续时间: {self.recognizer.non_speaking_duration}秒")
        
        print(f"\n录音模式: {'固定时长' if self.recording_mode == 'fixed' else '动态'}")
        if self.recording_mode == 'fixed':
            print(f"录音时长: {self.recording_seconds}秒")
        
        print(f"本地语音识别: {'已启用' if self.enable_speech_recognition else '已禁用'}")
        print("\n===================")
    
    def print_conversation_history(self):
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
    
    def process_user_input(self, audio_base64, temp_file=None):
        """处理用户音频输入并获取AI响应"""
        user_text = ""
        
        if self.enable_speech_recognition and temp_file:
            try:
                with sr.AudioFile(temp_file) as source:
                    audio_data = self.recognizer.record(source)
                    user_text = self.recognizer.recognize_google(audio_data)
                    print(f"您说: {user_text}")
            except Exception as e:
                print(f"本地语音识别失败: {e}")
        
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
        
        if user_text:
            user_message["content"].append({"type": "text", "text": user_text})
        
        self.messages.append(user_message)
        print("\n正在发送音频到Qwen-Omni进行处理...")
        
        self.audio_player.stop_stream()
        
        self.interrupt_event.clear()
        self.stream_stopped_event.clear()
        
        self.is_ai_speaking = True
        self.record_after_interrupt = False
        
        response_data = {
            "ai_text": "",
            "has_audio": False,
            "current_transcript": "",
            "interrupted": False
        }
        
        def receive_response():
            """接收API流式输出并播放音频"""
            audio_buffer = ""
            audio_chunk_count = 0
            initial_audio_chunks = 3
            is_first_audio = True
            all_data_received = False
            
            try:
                completion = self.client.chat.completions.create(
                    model="qwen-omni-turbo",
                    messages=self.messages,
                    modalities=["text", "audio"],
                    audio={"voice": "Cherry", "format": "wav"},
                    stream=True,
                    stream_options={"include_usage": True},
                )
                
                for chunk in completion:
                    if self.interrupt_event.is_set() and not self.audio_player.smooth_interrupt:
                        print("\n[检测到用户中断，停止数据接收]")
                        response_data["interrupted"] = True
                        break
                    
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
                                audio_buffer += delta.audio["data"]
                                audio_chunk_count += 1
                                
                                if is_first_audio and audio_chunk_count < initial_audio_chunks:
                                    continue
                                
                                if is_first_audio:
                                    is_first_audio = False
                                    self.audio_player.start_stream()
                                    print("\n开始音频播放...")
                                
                                if audio_chunk_count >= 5 or len(audio_buffer) > 10000:
                                    self.audio_player.add_audio_data(audio_buffer)
                                    audio_buffer = ""
                                    audio_chunk_count = 0
                
                all_data_received = True
                
                if audio_buffer:
                    self.audio_player.add_audio_data(audio_buffer)
                
                if self.interrupt_event.is_set() and self.audio_player.smooth_interrupt:
                    print("\n中断后等待当前句子完成...")
                    wait_start = time.time()
                    max_wait = 1.5
                
                elif not self.interrupt_event.is_set() and self.audio_player.is_playing:
                    print("\n数据流完成，等待音频播放结束...")
                    max_wait = 5.0
                    wait_start = time.time()
                    
                    while (not self.interrupt_event.is_set() and 
                           self.audio_player.is_playing and 
                           not self.audio_player.playback_finished.is_set() and
                           time.time() - wait_start < max_wait):
                        
                        if int(time.time()) % 2 == 0:
                            queue_size = self.audio_player.audio_queue.qsize()
                            buffer_empty = self.audio_player.buffer_empty.is_set()
                            print(f"\n音频状态: 队列大小={queue_size}, 缓冲区空={buffer_empty}, 播放完成={self.audio_player.playback_finished.is_set()}")
                        
                        self.audio_player.playback_finished.wait(0.1)
                    
                    if self.audio_player.playback_finished.is_set():
                        print("\n音频播放完成")
                    elif time.time() - wait_start >= max_wait:
                        print(f"\n等待音频播放超时({max_wait}秒)，强制停止")
                        self.audio_player.stop_immediately()
                    
                    if not self.interrupt_event.is_set():
                        time.sleep(0.2)
                
            except Exception as e:
                print(f"\n处理响应时出错: {e}")
            finally:
                self.stream_stopped_event.set()
                if self.interrupt_event.is_set() and not self.audio_player.smooth_interrupt:
                    self.audio_player.stop_immediately()
                elif all_data_received:
                    time.sleep(0.01)
                    self.audio_player.stop_stream()
        
        response_thread = threading.Thread(target=receive_response)
        response_thread.daemon = True
        response_thread.start()
        
        try:
            while response_thread.is_alive():
                if self.interrupt_event.is_set() and not self.audio_player.smooth_interrupt:
                    print("\n[检测到用户中断，立即停止]")
                    self.audio_player.stop_immediately()
                    break
                elif self.interrupt_event.is_set() and self.audio_player.smooth_interrupt:
                    print("\n[检测到用户中断，等待句子完成...]")
                time.sleep(0.01)
            
            response_thread.join(timeout=2.0)
            if response_thread.is_alive():
                print("\n[警告] 数据接收线程未能及时停止，强制终止")
                self.audio_player.stop_immediately()
                
        except Exception as e:
            print(f"\n主线程监控错误: {e}")
        finally:
            self.is_ai_speaking = False
            self.interrupt_event.set()
            
            if self.audio_player.is_playing:
                print("\n确保音频播放已停止...")
                self.audio_player.stop_stream()
            
            self.stream_stopped_event.clear()
            self.interrupt_event.clear()
            
            time.sleep(0.1)
        
        print("")
        
        if response_data["current_transcript"]:
            self.full_transcript += response_data["current_transcript"] + " "
            print(f"\n当前段落转录: {response_data['current_transcript']}")
            print(f"累计转录: {self.full_transcript}")
        
        if response_data["has_audio"] and response_data["current_transcript"]:
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
        
        self.print_conversation_history()
    
    def start_conversation(self):
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
        
        rec_choice = input("是否启用本地语音识别? (y/n, 默认n): ")
        self.enable_speech_recognition = rec_choice.lower().strip() == 'y'
        print(f"本地语音识别: {'已启用' if self.enable_speech_recognition else '已禁用'}")
        
        print("您可以在AI说话时打断它。")
        print("检测到静音时将自动停止录音。")
        
        greeting_message = {
            "role": "assistant",
            "content": [{"type": "text", "text": "你好！我是Qwen-Omni。今天我能帮你什么忙？"}]
        }
        self.messages.append(greeting_message)
        
        self.record_after_interrupt = False
        self.interrupt_speaking = False
        self.interrupt_speech_start_time = None
        self.speech_active_after_interrupt = False
        
        self.audio_recorder.speech_detected_event.clear()
        self.audio_recorder.speech_ended_event.clear()
        
        try:
            while True:
                while self.is_ai_speaking:
                    time.sleep(0.1)
                
                if self.record_after_interrupt:
                    print("\n正在处理用户打断时的语音...")
                    audio_base64, audio_file = self.audio_recorder.record_until_silence()
                    
                    self.record_after_interrupt = False
                    self.interrupt_speaking = False
                    self.interrupt_speech_start_time = None
                    self.speech_active_after_interrupt = False
                    
                    if not audio_base64:
                        print("打断期间未获取到有效的音频数据")
                        continue
                    
                    print("\n正在发送打断时的语音输入...")
                    self.process_user_input(audio_base64, audio_file)
                    
                    if audio_file and os.path.exists(audio_file):
                        os.remove(audio_file)
                    
                    continue
                
                print("\n等待用户输入...")
                if self.recording_mode == "fixed":
                    print("正在进行固定时长录音...")
                    # TODO: 如果需要，在此实现固定时长录音
                    continue
                else:
                    print("正在进行动态录音...")
                    audio_base64, audio_file = self.audio_recorder.record_until_silence()
                
                if not audio_base64:
                    print("未检测到有效音频。请重试。")
                    continue
                
                self.process_user_input(audio_base64, audio_file)
                
                if audio_file and os.path.exists(audio_file):
                    os.remove(audio_file)
                
        except KeyboardInterrupt:
            print("\n结束对话...")
            self.interrupt_event.set()
            self.is_ai_speaking = False
            time.sleep(0.01)
            
            self.audio_recorder.stop_mic_stream()
            self.audio_player.close()
            print("所有资源已释放，程序已终止。")
    
    def close(self):
        """清理资源"""
        self.audio_recorder.close()
        self.audio_player.close()