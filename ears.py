import pyaudio
import threading
import time
import os
import numpy as np
import onnxruntime
import collections
from config import (
    AUDIO_FORMAT, CHANNELS, RATE, CHUNK,
    MIN_SPEECH_DURATION
)
from core_pipeline import (
    ProcessorBase, Frame, FrameType, int16_to_float32, frames_to_wav_base64
)

# VAD模型参数
VAD_THRESHOLD = 0.6  # 语音检测阈值
END_BUFFER_FRAMES = 10  # 语音结束后缓冲帧数
MIN_NEG_FRAMES_FOR_ENDING = 8  # 检测结束的连续静音帧数
MAX_SPEECH_DURATION = 180.0  # 语音最长持续时间(秒)
PRE_BUFFER_FRAMES = int(1.0 * RATE / CHUNK)  # 预缓冲帧数
SPEECH_CONFIRM_FRAMES = 2  # 确认语音开始需要的连续帧数
PRE_DETECTION_BUFFER_SIZE = int(2.0 * RATE / CHUNK)  # 预检测缓冲区大小

class Ears(ProcessorBase):
    """音频输入处理器 - 集成了语音检测和处理功能，直接将处理后的语音发送到AI处理器"""
    def __init__(self, name="audio_input"):
        super().__init__(name)
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.vad_model = self._load_vad_model()
        
        # VAD状态变量
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.sr = RATE
        
        # 保存音频文件设置
        self.save_audio_file = True  # 设置为True以保存音频文件
        
        # 循环缓冲区
        self.buffer = collections.deque(maxlen=PRE_DETECTION_BUFFER_SIZE)
        
        # 语音检测状态
        self.speech_detected = False
        self.consecutive_speech_frames = 0
        self.consecutive_silence_frames = 0
        self.is_collecting_speech = False
        self.speech_frames = []
        self.speech_start_time = None
        
        # 同步锁和事件
        self.stream_lock = threading.RLock()
        self.speech_detected_event = threading.Event()
        self.speech_ended_event = threading.Event()
    
        print("[Ears] 初始化完成")
    
    def _load_vad_model(self):
        """加载VAD模型"""
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models/silero_vad.onnx")
        print(f"加载Silero VAD ONNX模型: {model_path}")
        return onnxruntime.InferenceSession(model_path)
    
    def reset_vad_state(self):
        """重置VAD状态 - 现在不再需要保持状态"""
        pass
    
    def start_mic_stream(self):
        """启动麦克风流"""
        with self.stream_lock:
            if self.stream is not None:
                return
            
            try:
                self.stream = self.p.open(
                        format=AUDIO_FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                    frames_per_buffer=CHUNK,
                    stream_callback=self._audio_callback
                )
                print("[Ears] 麦克风流已启动")
        
                # 重置状态
                self.buffer.clear()
                self.speech_frames = []
                self.speech_detected = False
                self.consecutive_speech_frames = 0
                self.consecutive_silence_frames = 0
                self.is_collecting_speech = False
                self.speech_start_time = None
                self.speech_detected_event.clear()
                self.speech_ended_event.clear()
            
            # 重置VAD状态
                self.state = np.zeros((2, 1, 128), dtype=np.float32)
                
                return True
            except Exception as e:
                print(f"[Ears] 启动麦克风流失败: {e}")
                return False
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """音频回调函数"""
        if self.is_running:
            self.enqueue_frame(Frame(
                FrameType.DATA, 
                {"audio_data": in_data, "frame_count": frame_count}
            ))
        return (None, pyaudio.paContinue)
    
    def process_frame(self, frame):
        """处理音频帧"""
        if frame.type == FrameType.SYSTEM:
            cmd = frame.data.get("command")
            if cmd == "stop":
                self.stop_mic_stream()
            elif cmd == "start":
                # 处理启动命令，启动麦克风流
                print("[Ears] 收到启动命令，开始启动麦克风流")
                self.start_mic_stream()
            return
        
        if frame.type == FrameType.DATA and "audio_data" in frame.data:
            audio_data = frame.data["audio_data"]
            
            # 添加到循环缓冲区
            self.buffer.append(audio_data)
                    
            # 转换为numpy数组
            audio_int16 = np.frombuffer(audio_data, dtype=np.int16)
            audio_float32 = int16_to_float32(audio_int16)
            
            # 检测语音
            is_speech = self._detect_speech(audio_float32)
            
            if is_speech:
                self.consecutive_speech_frames += 1
                self.consecutive_silence_frames = 0
            else:
                self.consecutive_silence_frames += 1
                self.consecutive_speech_frames = 0
            
            # 语音开始检测
            if not self.speech_detected and self.consecutive_speech_frames >= SPEECH_CONFIRM_FRAMES:
                self.speech_detected = True
                self.is_collecting_speech = True
                self.speech_start_time = time.time()
                self.speech_frames = list(self.buffer)  # 复制预缓冲区内容
                
                # 发送语音开始事件
                self.speech_detected_event.set()
                            
                # 发送用户打断系统事件帧到下游处理器
                print("[Ears] 检测到用户开始说话，发送用户打断事件到下游处理器")
                self.send_downstream(Frame(
                    FrameType.SYSTEM,
                    {"event": "user_interrupt", "command": "clear_pipeline"}
                ))
                
                # 通知下游
                self.send_downstream(Frame(
                    FrameType.SYSTEM,
                    {"event": "speech_started"}
                ))
                print("[Ears] 检测到语音开始")
                        
            # 收集语音帧
            if self.is_collecting_speech:
                self.speech_frames.append(audio_data)
                                
                # 检查超时
                if self.speech_start_time and (time.time() - self.speech_start_time) > MAX_SPEECH_DURATION:
                    print(f"[Ears] 语音时长超过最大限制 {MAX_SPEECH_DURATION}秒，强制结束")
                    self._end_speech_collection()
                    return
                
                # 检查语音结束
                if self.consecutive_silence_frames >= MIN_NEG_FRAMES_FOR_ENDING:
                    # 添加额外的缓冲帧
                    buffer_count = 0
                    while buffer_count < END_BUFFER_FRAMES and self.is_collecting_speech:
                        buffer_count += 1
                        
                        if buffer_count >= END_BUFFER_FRAMES:
                            self._end_speech_collection()
    
    def _end_speech_collection(self):
        """结束语音收集并将音频发送到AI处理器"""
        if not self.is_collecting_speech:
            return
            
        self.is_collecting_speech = False
        self.speech_detected = False
        
        # 收集的语音转为base64
        if self.speech_frames:
            # 处理完整的语音帧
            try:
                audio_base64 = self._convert_frames_to_base64(self.speech_frames)
                print(f"[Ears] 语音转换为base64完成，长度: {len(audio_base64)}")
                
                # 如果启用了保存音频功能，则保存音频文件
                if self.save_audio_file:
                    self._save_audio_to_file(self.speech_frames, audio_base64)
            
                # 发送语音结束事件
                self.speech_ended_event.set()
                                
                # 直接发送到AI处理器
                try:
                    self.send_downstream(Frame(
                        FrameType.SYSTEM,
                        {
                            "event": "speech_ready", 
                            "audio_base64": audio_base64,
                            "speech_frames": self.speech_frames
                        }
                    ))
                    print(f"[Ears] 语音数据已发送到AI处理器，帧数: {len(self.speech_frames)}")
                except Exception as e:
                    print(f"[Ears] 发送语音数据到AI处理器失败: {e}")
                
                speech_duration = time.time() - self.speech_start_time if self.speech_start_time else 0
                print(f"[Ears] 语音结束，持续时间: {speech_duration:.2f}秒")
            except Exception as e:
                print(f"[Ears] 处理语音时出错: {e}")
        
        # 重置状态
        self.consecutive_speech_frames = 0
        self.consecutive_silence_frames = 0
        self.speech_start_time = None
        self.speech_frames = []
    
    def _convert_frames_to_base64(self, frames):
        """将音频帧转换为base64编码的WAV数据"""
        try:
            result = frames_to_wav_base64(
                frames, 
                CHANNELS, 
                self.p.get_sample_size(AUDIO_FORMAT), 
                RATE
            )
            return result
        except Exception as e:
            print(f"[Ears] 转换音频帧到base64失败: {e}")
            raise

    def _detect_speech(self, audio_float32):
        """使用VAD模型检测语音
        基于 Silero VAD ONNX 模型
        
        Args:
            audio_float32: 输入音频帧 (float32 格式)
        
        Returns:
            bool: 是否检测到语音
        """
        try:
            # 确保输入形状正确 (Silero VAD 默认需要 512 采样点)
            if len(audio_float32) != 512:
                # 如果不是512点，进行补零或截断
                if len(audio_float32) < 512:
                    # 补零
                    padded = np.zeros(512, dtype=np.float32)
                    padded[:len(audio_float32)] = audio_float32
                    audio_float32 = padded
                else:
                    # 取前512点
                    audio_float32 = audio_float32[:512]
            
            # 重塑输入为模型期望的形状 [1, 512]
            audio = np.array(audio_float32, dtype=np.float32).reshape(1, -1)
            
            # 准备ONNX输入
            ort_inputs = {
                "input": audio,
                "state": self.state,  # 使用当前状态
                "sr": np.array(self.sr, dtype=np.int64)  # 添加采样率
            }
            
            # 运行ONNX推理
            ort_outs = self.vad_model.run(None, ort_inputs)
            
            # 更新状态
            if len(ort_outs) > 1:
                self.state = ort_outs[1]
            
            # 获取语音概率 - 第一个输出是语音概率
            speech_prob = ort_outs[0].item()  # 语音概率
            
            # 使用阈值判断是否为语音
            return speech_prob >= VAD_THRESHOLD
            
        except Exception as e:
            print(f"[Ears] VAD检测出错: {e}")
            return False
    
    def stop_mic_stream(self):
        """停止麦克风流"""
        print("[Ears] 停止麦克风流")
        
        with self.stream_lock:
            if self.stream is None:
                return
                
            try:
                # 结束当前语音收集
                if self.is_collecting_speech:
                    self._end_speech_collection()
                
                # 停止音频流
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
                
                print("[Ears] 麦克风流已安全停止")
                return True
            except Exception as e:
                print(f"[Ears] 停止麦克风流时出错: {e}")
                return False
    
    def get_available_microphones(self):
        """获取可用麦克风列表"""
        mics = []
        info = self.p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        
        for i in range(numdevices):
            device_info = self.p.get_device_info_by_host_api_device_index(0, i)
            if device_info.get('maxInputChannels') > 0:
                mics.append({
                    'index': i,
                    'name': device_info.get('name'),
                    'channels': device_info.get('maxInputChannels')
                })
        
        return mics
    
    def is_mic_stream_active(self):
        """检查麦克风流是否活跃"""
        with self.stream_lock:
            return self.stream is not None and self.stream.is_active()
    
    def close(self):
        """关闭资源"""
        self.stop_mic_stream()
        if self.p:
            self.p.terminate()

    def _save_audio_to_file(self, frames, base64_data=None):
        """保存音频帧到文件
        
        Args:
            frames: 音频帧列表
            base64_data: 可选的base64编码的音频数据
        """
        try:
            # 确保目录存在
            save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_record_tmp")
            os.makedirs(save_dir, exist_ok=True)
            
            # 创建时间戳文件名
            timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
            file_path = os.path.join(save_dir, f"audio_{timestamp}.wav")
            
            # 保存原始帧到WAV文件
            import wave
            with wave.open(file_path, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.p.get_sample_size(AUDIO_FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b''.join(frames))
                
            print(f"[Ears] 音频已保存到: {file_path}")
            return file_path
        except Exception as e:
            print(f"[Ears] 保存音频文件失败: {e}")
            return None 