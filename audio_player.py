import base64
import numpy as np
import pyaudio
import threading
import time
import queue
from config import PLAYER_RATE, FADE_OUT_DURATION, MAX_FINISH_DURATION

class AudioPlayer:
    """支持流式播放和用户打断的音频播放器"""
    def __init__(self):
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
        
    def start_stream(self):
        with self.stream_lock:
            if self.stream is not None:
                self.stop_stream()
                
            try:
                self.stream = self.p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=PLAYER_RATE,
                    output=True
                )
                self.is_playing = True
                self.should_stop = False
                self.buffer_empty.set()
                self.last_audio_time = None
                self.smooth_interrupt = False
                self.interrupt_time = None
                self.fade_out_active = False
                self.fade_out_start_time = None
                self.playback_finished.clear()
                
                self.audio_thread = threading.Thread(target=self._play_audio_continuous)
                self.audio_thread.daemon = True
                self.audio_thread.start()
                print("音频输出流已创建，开始持续播放...")
            except Exception as e:
                print(f"创建音频流时出错: {e}")
                self.is_playing = False
                self.stream = None
    
    def add_audio_data(self, audio_data):
        """添加音频数据到队列"""
        if not self.is_playing:
            self.start_stream()
            
        if self.should_stop and not self.smooth_interrupt:
            return
            
        try:
            if self.playback_finished.is_set():
                self.playback_finished.clear()
                
            wav_bytes = base64.b64decode(audio_data)
            audio_np = np.frombuffer(wav_bytes, dtype=np.int16)
            
            if self.smooth_interrupt and self.interrupt_time:
                current_time = time.time()
                if current_time - self.interrupt_time > self.max_finish_duration:
                    print("平滑打断已达到最大时间，停止更多音频")
                    return
            
            self.audio_queue.put(audio_np.tobytes())
            self.buffer_empty.clear()
            self.last_audio_time = time.time()
        except Exception as e:
            print(f"音频处理错误: {e}")
            
    def _play_audio_continuous(self):
        """后台持续音频播放线程"""
        buffer = b""
        min_buffer_size = 2048
        initial_buffer_size = 2048
        is_initial_buffer = True
        is_final_flush = False
        
        try:
            while self.is_playing and (not self.should_stop or self.smooth_interrupt):
                current_time = time.time()
                
                if self.smooth_interrupt and self.interrupt_time and self.fade_out_enabled and not self.fade_out_active:
                    self.fade_out_active = True
                    self.fade_out_start_time = current_time
                    print("开始音量淡出效果...")
                
                if self.smooth_interrupt and self.interrupt_time:
                    elapsed = current_time - self.interrupt_time
                    if elapsed > 2.0:
                        print("达到最大等待时间，强制停止音频")
                        self.playback_finished.set()
                        self.buffer_empty.set()
                        break
                    
                    if self.audio_queue.empty() and len(buffer) == 0:
                        print("平滑打断：当前句子已完成")
                        self.playback_finished.set()
                        self.buffer_empty.set()
                        break
                
                try:
                    if self.audio_queue.empty() and len(buffer) == 0:
                        if not is_final_flush:
                            silence_samples = int(PLAYER_RATE * 0.05)
                            silence = np.zeros(silence_samples, dtype=np.int16)
                            buffer = silence.tobytes()
                            is_final_flush = True
                        else:
                            print("最终静音块已播放，播放真正结束")
                            self.buffer_empty.set()
                            self.playback_finished.set()
                            break
                    
                    try:
                        while not self.audio_queue.empty():
                            chunk = self.audio_queue.get(block=False)
                            buffer += chunk
                            self.audio_queue.task_done()
                            is_final_flush = False
                    except queue.Empty:
                        pass
                    
                    required_size = initial_buffer_size if is_initial_buffer else min_buffer_size
                    
                    if len(buffer) >= required_size and (not self.should_stop or self.smooth_interrupt):
                        if is_initial_buffer:
                            print("初始缓冲完成，开始平滑播放...")
                            is_initial_buffer = False
                        
                        chunk_size = min(8192, len(buffer))
                        chunk = buffer[:chunk_size]
                        buffer = buffer[chunk_size:]
                        
                        if self.fade_out_active and self.fade_out_start_time:
                            fade_progress = min(1.0, (current_time - self.fade_out_start_time) / self.fade_out_duration)
                            audio_data = np.frombuffer(chunk, dtype=np.int16)
                            volume_factor = max(0, 1.0 - fade_progress)
                            audio_data = (audio_data * volume_factor).astype(np.int16)
                            chunk = audio_data.tobytes()
                            
                            if fade_progress > 0.9 and self.audio_queue.empty() and len(buffer) == 0:
                                print("淡出接近完成，结束播放")
                                self.buffer_empty.set()
                                self.playback_finished.set()
                                break
                        
                        with self.stream_lock:
                            if self.stream and (not self.should_stop or self.smooth_interrupt):
                                try:
                                    self.stream.write(chunk)
                                except Exception as e:
                                    print(f"音频播放过程中出错: {e}")
                                    break
                    
                    if len(buffer) == 0 and self.audio_queue.empty() and not is_final_flush:
                        time.sleep(0.01)
                        
                except Exception as e:
                    print(f"音频播放错误: {e}")
                    time.sleep(0.1)
                    
        finally:
            self.is_playing = False
            self.smooth_interrupt = False
            self.fade_out_active = False
            self.buffer_empty.set()
            self.playback_finished.set()
            print("音频播放线程已退出")
    
    def is_audio_complete(self):
        """检查是否所有音频数据都已播放完成"""
        if not self.is_playing:
            return True
        return self.playback_finished.is_set()
    
    def request_smooth_interrupt(self):
        """请求平滑打断，将在当前句子完成后停止"""
        if self.is_playing and not self.should_stop:
            print("请求平滑打断，将在当前语音单元结束后停止...")
            self.smooth_interrupt = True
            self.should_stop = True
            self.interrupt_time = time.time()
            
            if self.fade_out_enabled:
                print("准备执行音量淡出效果...")
            
            return True
        return False
    
    def stop_stream(self):
        """正常停止音频播放"""
        self.should_stop = True
        self.is_playing = False
        self.smooth_interrupt = False
        
        try:
            while not self.audio_queue.empty():
                self.audio_queue.get(block=False)
                self.audio_queue.task_done()
        except queue.Empty:
            pass
        
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1.0)
        
        with self.stream_lock:
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                    print(f"关闭音频流时出错(已忽略): {e}")
                finally:
                    self.stream = None
            
        self.buffer_empty.set()
        self.playback_finished.set()
        self.last_audio_time = None
        print("音频流已停止")
    
    def stop_immediately(self):
        """立即停止音频播放并清空队列"""
        self.should_stop = True
        self.is_playing = False
        self.smooth_interrupt = False
        
        with self.audio_queue.mutex:
            self.audio_queue.queue.clear()
        
        if self.stream and self.fade_out_enabled:
            try:
                print("播放短暂静音以实现平滑结束...")
                silent_samples = int(PLAYER_RATE * 0.05)
                silence = np.zeros(silent_samples, dtype=np.int16)
                
                with self.stream_lock:
                    if self.stream:
                        self.stream.write(silence.tobytes())
            except Exception as e:
                print(f"播放静音时出错(已忽略): {e}")
        
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1.0)
        
        with self.stream_lock:
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                    print(f"关闭音频流时出错(已忽略): {e}")
                finally:
                    self.stream = None
            
        self.buffer_empty.set()
        self.playback_finished.set()
        self.last_audio_time = None
        self.fade_out_active = False
        print("音频流已立即停止")
    
    def close(self):
        """关闭音频设备"""
        self.stop_stream()
        
        try:
            self.p.terminate()
        except Exception as e:
            print(f"终止PyAudio时出错(已忽略): {e}")