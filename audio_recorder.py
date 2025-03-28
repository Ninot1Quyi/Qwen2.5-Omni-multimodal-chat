import pyaudio
import threading
import time
import torch
import numpy as np
from config import (
    AUDIO_FORMAT, CHANNELS, RATE, CHUNK,
    MIN_SPEECH_DURATION, SPEECH_VOLUME_THRESHOLD,
    NORMAL_VOLUME_THRESHOLD, MIN_POSITIVE_FRAMES,
    MIN_NEGATIVE_FRAMES
)
from utils import convert_frames_to_wav, save_wav_file, wav_to_base64

class AudioRecorder:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.mic_stream = None
        self.is_mic_active = False
        self.mic_lock = threading.Lock()
        
        # 初始化 Silero VAD
        torch.set_num_threads(1)
        self.model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad')
        (self.get_speech_timestamps,
         self.save_audio,
         self.read_audio,
         self.VADIterator,
         self.collect_chunks) = utils
        
        self.vad_iterator = self.VADIterator(self.model)
        
        # 持续监听
        self.continuous_listening = True
        self.listening_thread = None
        
        # 缓冲区
        self.circular_buffer = []
        self.circular_buffer_size = int(1 * RATE / CHUNK)  # 1秒的预缓冲
        self.mic_data_buffer = []
        
        # 语音结束检测参数
        self.end_silence_frames = 45  # 约1.4秒的静音判定
        self.end_buffer_frames = 15   # 约0.5秒的结束缓冲
        
        # 事件
        self.speech_detected_event = threading.Event()
        self.speech_ended_event = threading.Event()
    
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
    
    def _continuous_listening_thread(self):
        """后台持续监听线程"""
        print("持续监听线程已启动")
        speech_start_time = None
        consecutive_silence_count = 0
        vad_positive_frames = 0
        vad_negative_frames = 0
        end_buffer_count = 0
        is_ending = False
        
        self.circular_buffer = []
        self.mic_data_buffer = []
        
        self.speech_detected_event.clear()
        self.speech_ended_event.clear()
        
        try:
            while self.continuous_listening and self.is_mic_active:
                try:
                    if self.mic_stream is None:
                        print("麦克风流无效，尝试重新启动...")
                        time.sleep(0.01)
                        continue
                    
                    data = self.mic_stream.read(CHUNK, exception_on_overflow=False)
                    
                    # 只在语音开始前维护预缓冲
                    if speech_start_time is None:
                        self.circular_buffer.append(data)
                        if len(self.circular_buffer) > self.circular_buffer_size:
                            self.circular_buffer.pop(0)
                    
                    audio_int16 = np.frombuffer(data, dtype=np.int16)
                    volume = np.max(np.abs(audio_int16))
                    
                    audio_float32 = audio_int16.astype(np.float32) / 32768.0
                    audio_tensor = torch.tensor(audio_float32)
                    
                    speech_dict = self.vad_iterator(audio_tensor)
                    is_speech_vad = bool(speech_dict and 'start' in speech_dict)
                    
                    if is_speech_vad:
                        vad_positive_frames += 1
                        vad_negative_frames = 0
                        if is_ending:  # 如果检测到新的语音，重置结束状态
                            is_ending = False
                            end_buffer_count = 0
                    else:
                        vad_negative_frames += 1
                        vad_positive_frames = 0
                    
                    is_speech = (vad_positive_frames >= MIN_POSITIVE_FRAMES) or (is_speech_vad and volume > NORMAL_VOLUME_THRESHOLD)
                    
                    if not is_speech_vad and volume < 300:
                        consecutive_silence_count += 1
                    else:
                        consecutive_silence_count = 0
                        if is_ending:  # 如果有声音，重置结束状态
                            is_ending = False
                            end_buffer_count = 0
                    
                    current_time = time.time()
                    
                    if is_speech and speech_start_time is None:
                        speech_start_time = current_time
                        print(f"检测到语音，开始录音...")
                        self.mic_data_buffer = list(self.circular_buffer)  # 复制预缓冲的数据
                        self.speech_detected_event.set()
                    elif speech_start_time is not None:
                        self.mic_data_buffer.append(data)  # 持续添加新的音频数据
                        
                        # 检查是否进入结束状态
                        if not is_ending and (vad_negative_frames >= MIN_NEGATIVE_FRAMES or consecutive_silence_count >= self.end_silence_frames):
                            is_ending = True
                            end_buffer_count = 0
                            print("检测到可能的语音结束，等待确认...")
                        
                        # 在结束状态下累积额外的缓冲帧
                        if is_ending:
                            end_buffer_count += 1
                            if end_buffer_count >= self.end_buffer_frames:
                                speech_duration = current_time - speech_start_time
                                
                                if speech_duration >= MIN_SPEECH_DURATION:
                                    print(f"语音结束，持续时间: {speech_duration:.2f}秒")
                                    self.speech_ended_event.set()
                                    time.sleep(0.05)
                                
                                speech_start_time = None
                                is_ending = False
                                end_buffer_count = 0
                    
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
    
    def record_until_silence(self, temp_file="temp_audio.wav"):
        """录音直到检测到静音"""
        print("等待语音输入...")
        recording_data = []
        max_wait_time = 60
        
        self.speech_detected_event.clear()
        self.speech_ended_event.clear()
        
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
            else:
                print("检测到语音结束，停止录音")
            
            recording_data = list(self.mic_data_buffer)  # 获取完整的录音数据
            self.mic_data_buffer = []
            
            if recording_data:
                audio_duration = len(recording_data) * CHUNK / RATE
                print(f"录音完成，音频长度: {audio_duration:.2f}秒")
                
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