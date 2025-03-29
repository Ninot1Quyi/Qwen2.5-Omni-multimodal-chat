import pyaudio
import threading
import time
import os
import numpy as np
import onnxruntime
import collections
from config import (
    AUDIO_FORMAT, CHANNELS, RATE, CHUNK,
    MIN_SPEECH_DURATION, SPEECH_VOLUME_THRESHOLD,
    NORMAL_VOLUME_THRESHOLD, MIN_POSITIVE_FRAMES,
    MIN_NEGATIVE_FRAMES
)
from utils import convert_frames_to_wav, save_wav_file, wav_to_base64

# ONNX模型的静音判断阈值 - 提高以降低灵敏度
VAD_THRESHOLD = 0.6  # 从0.5提高到0.6，提高检测阈值
# 语音结束后缓冲帧数 - 增加帧数提供更长的后置缓冲
END_BUFFER_FRAMES = 10  # 从1增加到10，约等于0.3秒
# 调整语音结束临界帧数 - 增加检测帧数
MIN_NEG_FRAMES_FOR_ENDING = 8  # 从6增加到8帧，需要更多连续静音帧
# 语音最长持续时间(秒)，超过此时间强制结束
MAX_SPEECH_DURATION = 180.0  # 最长允许180秒语音
# 前置缓冲区大小，单位为帧数 - 增加前置缓冲以确保句子开头完整
PRE_BUFFER_FRAMES = int(1.0 * RATE / CHUNK)  # 从0.5秒增加到1.0秒的前置缓冲
# 语音确认帧数 - 需要连续检测到多少帧才确认语音开始
SPEECH_CONFIRM_FRAMES = 2  # 需要连续5帧检测到语音才开始录音
# 预检测缓冲区大小 - 用于存储可能的语音开始前的数据
PRE_DETECTION_BUFFER_SIZE = int(2.0 * RATE / CHUNK)  # 2秒的预检测缓冲

class AudioRecorder:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.mic_stream = None
        self.is_mic_active = False
        self.mic_lock = threading.Lock()
        
        # 初始化 Silero VAD (ONNX版本)
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models/silero_vad.onnx")
        print(f"加载Silero VAD ONNX模型: {model_path}")
        self.onnx_model = onnxruntime.InferenceSession(model_path)
        
        # VAD状态初始化
        self.reset_vad_state()
        
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
    
    def reset_vad_state(self, batch_size=1):
        """重置VAD状态"""
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
        # 确保输入形状正确 (固定为512采样点，适用于16kHz采样率)
        if len(audio_data) != 512:
            print(f"警告: 音频样本数量 {len(audio_data)} 不为512，结果可能不正确")
        
        # 重塑输入为模型期望的形状 [batch_size, seq_len]
        audio = np.array(audio_data, dtype=np.float32).reshape(1, -1)
        
        # 准备ONNX输入
        ort_inputs = {
            "input": audio,
            "state": self.state,  # 使用当前状态
            "sr": np.array(self.sr, dtype=np.int64)  # 添加采样率
        }
        
        # 运行推理
        ort_outs = self.onnx_model.run(None, ort_inputs)
        
        # 更新状态，返回格式为 [out, state]
        out, self.state = ort_outs
        
        # 返回预测结果: [batch_size, 1] -> 标量值
        return out[0][0] > VAD_THRESHOLD  # 使用全局阈值
    
    def get_available_microphones(self):
        """获取可用麦克风列表"""
        mics = []
        for i in range(self.p.get_device_count()):
            dev_info = self.p.get_device_info_by_index(i)
            if dev_info.get('maxInputChannels') > 0:
                mics.append({
                    'index': i,
                    'name': dev_info.get('name'),
                    'channels': dev_info.get('maxInputChannels'),
                    'sample_rate': dev_info.get('defaultSampleRate')
                })
        return mics
    
    def start_mic_stream(self):
        """启动麦克风流进行持续监听"""
        with self.mic_lock:
            if not self.is_mic_active:
                try:
                    self.mic_stream = self.p.open(
                        format=AUDIO_FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        frames_per_buffer=CHUNK
                    )
                    self.is_mic_active = True
                    print("麦克风流已启动")
                    
                    # 重置索引和缓冲区
                    self.long_buffer.clear()
                    self.circular_buffer.clear()
                    self.current_buffer_index = 0
                    self.speech_start_index = -1
                    self.speech_end_index = -1
                    self.first_speech_frame_index = -1
                    
                    if self.continuous_listening and (self.listening_thread is None or not self.listening_thread.is_alive()):
                        self.listening_thread = threading.Thread(target=self._continuous_listening_thread)
                        self.listening_thread.daemon = True
                        self.listening_thread.start()
                        print("后台持续监听已启动")
                except Exception as e:
                    print(f"启动麦克风流失败: {e}")
    
    def stop_mic_stream(self):
        """停止麦克风流"""
        with self.mic_lock:
            self.continuous_listening = False
            
            if self.is_mic_active and self.mic_stream:
                try:
                    self.is_mic_active = False
                    time.sleep(0.1)
                    self.mic_stream.stop_stream()
                    self.mic_stream.close()
                    self.mic_stream = None
                    print("麦克风流已安全停止")
                except Exception as e:
                    print(f"停止麦克风流时出错: {e}")
                    self.mic_stream = None
    
    def is_mic_stream_active(self):
        """检查麦克风流是否已启动
        
        Returns:
            bool: 麦克风流是否处于活动状态
        """
        with self.mic_lock:
            return self.is_mic_active and self.mic_stream is not None
    
    def _continuous_listening_thread(self):
        """后台持续监听线程"""
        print("持续监听线程已启动")
        speech_start_time = None
        consecutive_silence_count = 0
        vad_positive_frames = 0
        vad_negative_frames = 0
        end_buffer_count = 0
        is_ending = False
        # 记录当检测到可能结束时的索引
        potential_end_index = -1
        
        self.circular_buffer.clear()
        self.mic_data_buffer = []
        
        self.speech_detected_event.clear()
        self.speech_ended_event.clear()
        
        # 重置VAD状态
        self.reset_vad_state()
        
        try:
            while self.continuous_listening and self.is_mic_active:
                try:
                    if self.mic_stream is None:
                        print("麦克风流无效，尝试重新启动...")
                        time.sleep(0.01)
                        continue
                    
                    # 读取音频数据
                    data = self.mic_stream.read(CHUNK, exception_on_overflow=False)
                    
                    # 添加到长循环缓冲区
                    with self.mic_lock:
                        self.long_buffer.append(data)
                        self.current_buffer_index += 1
                    
                    # 始终维护预缓冲区，无论是否已开始录音
                    self.circular_buffer.append(data)
                    
                    # 将音频数据转换为int16格式
                    audio_int16 = np.frombuffer(data, dtype=np.int16)
                    
                    # 转换为浮点数据 [-1, 1]
                    audio_float32 = audio_int16.astype(np.float32) / 32768.0
                    
                    # 使用ONNX模型进行语音检测
                    is_speech_vad = self.vad_predict(audio_float32)
                    
                    # 检测到第一帧语音时记录索引
                    if is_speech_vad and self.first_speech_frame_index == -1 and speech_start_time is None:
                        self.first_speech_frame_index = self.current_buffer_index
                        print(f"[首帧检测] 检测到首个语音帧，索引: {self.first_speech_frame_index}")
                    
                    # 更新语音检测帧计数
                    if is_speech_vad:
                        vad_positive_frames += 1
                        vad_negative_frames = 0
                        if is_ending:  # 如果检测到新的语音，重置结束状态
                            is_ending = False
                            end_buffer_count = 0
                            potential_end_index = -1
                            print("检测到新的语音，取消结束确认")
                    else:
                        vad_negative_frames += 1
                        vad_positive_frames = 0
                        if speech_start_time is not None:
                            consecutive_silence_count += 1
                    
                    # 仅使用VAD结果确定语音状态
                    is_speech = vad_positive_frames >= SPEECH_CONFIRM_FRAMES
                    
                    current_time = time.time()
                    
                    # 如果已经开始录音，检查是否超时
                    if speech_start_time is not None:
                        speech_duration = current_time - speech_start_time
                        if speech_duration > MAX_SPEECH_DURATION:
                            print(f"语音时长超过最大限制 {MAX_SPEECH_DURATION}秒，强制结束")
                            
                            # 记录结束索引
                            with self.mic_lock:
                                self.speech_end_index = self.current_buffer_index
                                
                            self.speech_ended_event.set()
                            
                            # 重置所有状态
                            speech_start_time = None
                            is_ending = False
                            end_buffer_count = 0
                            vad_positive_frames = 0
                            vad_negative_frames = 0
                            consecutive_silence_count = 0
                            potential_end_index = -1
                            self.first_speech_frame_index = -1
                            self.reset_vad_state()
                            continue
                    
                    # 语音开始检测 - 需要连续多帧检测到语音
                    if is_speech and speech_start_time is None:
                        speech_start_time = current_time
                        print(f"检测到语音，开始录音...")
                        
                        # 记录语音开始索引 (从首次检测到语音的帧往前算)
                        with self.mic_lock:
                            # 确定语音真正的开始点
                            if self.first_speech_frame_index > 0:
                                # 从首次检测到语音的帧往前确定更大的前置缓冲
                                actual_pre_buffer = min(
                                    PRE_BUFFER_FRAMES,  # 不超过预设的最大前置缓冲
                                    self.current_buffer_index - self.first_speech_frame_index + SPEECH_CONFIRM_FRAMES  # 加上确认帧数
                                )
                                
                                # 计算实际的开始索引，从首次检测到语音的帧再往前推
                                self.speech_start_index = max(0, self.first_speech_frame_index - actual_pre_buffer)
                            else:
                                # 如果没有记录到首帧，使用当前索引减去前置缓冲
                                self.speech_start_index = max(0, self.current_buffer_index - PRE_BUFFER_FRAMES)
                                
                            print(f"记录语音开始索引: {self.speech_start_index} (首帧索引: {self.first_speech_frame_index}, 当前索引: {self.current_buffer_index})")
                        
                        self.speech_detected_event.set()
                        consecutive_silence_count = 0  # 重置静音计数
                        
                    # 语音结束检测
                    elif speech_start_time is not None:
                        # 检查是否进入结束状态 - 使用更长的静音判定
                        if not is_ending and (vad_negative_frames >= MIN_NEG_FRAMES_FOR_ENDING or consecutive_silence_count >= self.end_silence_frames):
                            is_ending = True
                            end_buffer_count = 0
                            # 记录可能的结束位置 - 这是检测到静音开始的位置
                            potential_end_index = self.current_buffer_index
                            speech_duration = current_time - speech_start_time
                            print(f"检测到可能的语音结束，等待确认... [负帧:{vad_negative_frames}, 静音:{consecutive_silence_count}, 时长:{speech_duration:.2f}s]")
                        
                        # 在结束状态下累积额外的缓冲帧
                        if is_ending:
                            end_buffer_count += 1
                            
                            # 直接输出调试信息，每帧都输出，确保看到计数变化
                            print(f"[确认中] 缓冲帧:{end_buffer_count}/{self.end_buffer_frames}, 静音帧:{consecutive_silence_count}, 负帧:{vad_negative_frames}")
                            
                            # 积累足够的后置缓冲帧后确认语音结束
                            if end_buffer_count >= self.end_buffer_frames:
                                speech_duration = current_time - speech_start_time
                                
                                # 确认语音结束
                                print(f"语音结束，持续时间: {speech_duration:.2f}秒")
                                
                                # 记录语音结束索引
                                with self.mic_lock:
                                    if potential_end_index > 0:
                                        # 使用检测到静音开始的位置作为结束索引，而不是当前位置
                                        # 这样可以避免录入结束后的杂音
                                        self.speech_end_index = potential_end_index
                                    else:
                                        # 如果没有记录到可能的结束位置，使用当前位置
                                        self.speech_end_index = self.current_buffer_index
                                    print(f"记录语音结束索引: {self.speech_end_index}")
                                
                                self.speech_ended_event.set()
                                
                                # 重置所有状态
                                speech_start_time = None
                                is_ending = False
                                end_buffer_count = 0
                                vad_positive_frames = 0
                                vad_negative_frames = 0
                                consecutive_silence_count = 0
                                potential_end_index = -1
                                self.first_speech_frame_index = -1  # 重置首帧检测
                                self.reset_vad_state()  # 重置VAD状态
                    
                except OSError as e:
                    print(f"读取麦克风数据时出错: {e}")
                    time.sleep(0.2)
                except Exception as e:
                    print(f"持续监听线程错误: {e}")
                    time.sleep(0.2)
                    
        except Exception as e:
            print(f"持续监听线程异常终止: {e}")
        finally:
            print("持续监听线程已退出")

    def get_speech_frames(self):
        """获取语音片段的音频帧
        
        Returns:
            list: 语音音频帧列表
        """
        if self.speech_start_index < 0 or self.speech_end_index < 0:
            print("语音索引无效，无法获取语音帧")
            return []
            
        with self.mic_lock:
            # 计算长循环缓冲区的当前大小
            buffer_size = len(self.long_buffer)
            
            # 如果没有足够的数据，返回空列表
            if buffer_size == 0:
                return []
            
            # 计算实际的开始和结束位置
            # 由于使用了collections.deque，我们需要转换为相对索引
            relative_start = (self.speech_start_index - self.current_buffer_index + buffer_size) % buffer_size
            relative_end = (self.speech_end_index - self.current_buffer_index + buffer_size) % buffer_size
            
            print(f"相对索引 - 开始: {relative_start}, 结束: {relative_end}, 缓冲区大小: {buffer_size}")
            
            # 收集帧数据
            frames = []
            
            # 处理两种情况: 1) 开始位置在结束位置之前，2) 开始位置在结束位置之后（环绕情况）
            if relative_start <= relative_end:
                # 简单情况: 直接获取中间的片段
                frames = list(self.long_buffer)[relative_start:relative_end]
            else:
                # 环绕情况: 需要获取两个部分并连接起来
                end_frames = list(self.long_buffer)[relative_start:]
                start_frames = list(self.long_buffer)[:relative_end]
                frames = end_frames + start_frames
            
            print(f"获取到语音帧: {len(frames)}帧")
            return frames
    
    def record_until_silence(self, temp_file="temp_audio.wav"):
        """录音直到检测到静音"""
        print("等待语音输入...")
        max_wait_time = 60
        
        self.speech_detected_event.clear()
        self.speech_ended_event.clear()
        self.speech_start_index = -1
        self.speech_end_index = -1
        self.first_speech_frame_index = -1  # 重置首帧检测
        
        try:
            print("等待检测到语音...")
            speech_detected = self.speech_detected_event.wait(timeout=max_wait_time)
            
            if not speech_detected:
                print("等待语音超时")
                return None, None
            
            print("检测到语音，正在录音...")
            
            print("录音中，等待语音结束...")
            speech_ended = self.speech_ended_event.wait(timeout=max_wait_time)
            
            if not speech_ended:
                print(f"等待语音结束超时({max_wait_time}秒)，强制停止")
                # 如果是超时，手动设置结束索引
                with self.mic_lock:
                    if self.speech_end_index < 0:
                        self.speech_end_index = self.current_buffer_index
            else:
                print("检测到语音结束，停止录音")
            
            # 获取完整语音帧
            recording_data = self.get_speech_frames()
            
            if recording_data:
                audio_duration = len(recording_data) * CHUNK / RATE
                print(f"录音完成，音频长度: {audio_duration:.2f}秒，帧数: {len(recording_data)}")
                
                # 转换为WAV格式
                wav_bytes = convert_frames_to_wav(recording_data, self.p, CHANNELS, AUDIO_FORMAT, RATE)
                base64_audio = wav_to_base64(wav_bytes)
                
                # 保存到文件
                # save_wav_file(temp_file, recording_data, self.p, CHANNELS, AUDIO_FORMAT, RATE)
                
                return base64_audio, temp_file
            else:
                print("未收集到有效的音频数据")
                return None, None
                
        except Exception as e:
            print(f"动态录音过程中出错: {e}")
            return None, None
    
    def close(self):
        """关闭并清理资源"""
        self.stop_mic_stream()
        try:
            self.p.terminate()
        except Exception as e:
            print(f"终止PyAudio时出错(已忽略): {e}")