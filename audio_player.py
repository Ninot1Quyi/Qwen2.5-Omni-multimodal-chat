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
                # 完全按照官方示例创建音频流
                self.stream = self.p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=PLAYER_RATE,  # 使用配置的24000采样率
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
            # 直接转换为numpy数组，不进行任何处理
            audio_np = np.frombuffer(wav_bytes, dtype=np.int16)
            
            # Qwen模型输出的音频已经是24kHz，无需重采样
            if self.smooth_interrupt and self.interrupt_time:
                current_time = time.time()
                if current_time - self.interrupt_time > self.max_finish_duration:
                    print("平滑打断已达到最大时间，停止更多音频")
                    return
            
            # 直接添加到队列
            self.audio_queue.put(audio_np.tobytes())
            self.buffer_empty.clear()
            self.last_audio_time = time.time()
        except Exception as e:
            print(f"音频处理错误: {e}")
            
    def _play_audio_continuous(self):
        """后台持续音频播放线程"""
        buffer = b""
        min_buffer_size = 1024  # 减小缓冲区以提高响应速度
        is_initial_buffer = True
        
        try:
            while self.is_playing and (not self.should_stop or self.smooth_interrupt):
                current_time = time.time()
                
                # 处理淡出效果
                if self.smooth_interrupt and self.interrupt_time and self.fade_out_enabled and not self.fade_out_active:
                    self.fade_out_active = True
                    self.fade_out_start_time = current_time
                    print("开始音量淡出效果...")
                
                # 检查是否已经到达最大完成时间
                if self.smooth_interrupt and self.interrupt_time:
                    elapsed = current_time - self.interrupt_time
                    if elapsed > self.max_finish_duration:
                        print("达到最大等待时间，强制停止音频")
                        break
                
                try:
                    # 处理队列中的音频数据
                    while not self.audio_queue.empty():
                        chunk = self.audio_queue.get(block=False)
                        buffer += chunk
                        self.audio_queue.task_done()
                    
                    # 当缓冲区有足够数据，或者是最后的数据时播放
                    if len(buffer) >= min_buffer_size or (len(buffer) > 0 and self.audio_queue.empty()):
                        if is_initial_buffer:
                            print("初始缓冲完成，开始平滑播放...")
                            is_initial_buffer = False
                        
                        # 对当前块应用淡出效果（如果需要）
                        if self.fade_out_active and self.fade_out_start_time:
                            fade_progress = min(1.0, (current_time - self.fade_out_start_time) / self.fade_out_duration)
                            audio_data = np.frombuffer(buffer, dtype=np.int16)
                            
                            # 使用非线性淡出曲线，在开始时变化较慢，结束时变化较快
                            # 这样可以使淡出效果在开始时更平滑，结束时更快
                            volume_factor = max(0, 1.0 - (fade_progress * fade_progress))
                            
                            # 应用音量变化
                            audio_data = (audio_data * volume_factor).astype(np.int16)
                            buffer = audio_data.tobytes()
                            
                            # 如果淡出接近完成，结束播放
                            if fade_progress >= 0.7:  # 降低阈值，当达到70%时就结束
                                print(f"淡出已达到阈值 {fade_progress:.2f}，结束播放")
                                break
                        
                        # 检查是否应当强制停止(如果打断且超过了最大时间)
                        if self.smooth_interrupt and self.interrupt_time:
                            elapsed = current_time - self.interrupt_time
                            if elapsed > self.max_finish_duration * 0.5:  # 进一步减小等待时间
                                print("打断等待时间过长，强制停止")
                                break
                        
                        # 播放音频数据
                        with self.stream_lock:
                            if self.stream and (not self.should_stop or self.smooth_interrupt):
                                try:
                                    self.stream.write(buffer, exception_on_underflow=False)
                                except Exception as e:
                                    print(f"音频播放过程中出错: {e}")
                                    break
                        buffer = b""
                    
                    # 检查是否应当结束播放
                    if self.audio_queue.empty() and len(buffer) == 0:
                        if self.smooth_interrupt:
                            print("平滑打断：当前音频已完成")
                            break
                        
                        # 播放结束，等待新数据
                        if not is_initial_buffer:  # 避免初始状态误触发
                            self.buffer_empty.set()
                            self.playback_finished.set()
                            
                            # 等待更多音频数据
                            if self.last_audio_time and (current_time - self.last_audio_time) > 0.5:  # 从1.0降为0.5
                                print("等待音频数据超时，播放完成")
                                break
                    
                    # 短暂休眠以降低CPU使用率
                    time.sleep(0.001)
                    
                except Exception as e:
                    print(f"音频播放错误: {e}")
                    time.sleep(0.01)
        
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
            
            # 减少等待时间，更快响应打断
            self.max_finish_duration = 0.2  # 从1.0降低到0.3秒
            
            if self.fade_out_enabled:
                self.fade_out_duration = 0.2  # 加快淡出速度
                self.fade_out_active = True  # 立即开始淡出效果
                self.fade_out_start_time = time.time()
                print("开始执行音量淡出效果...")
            
            # 清空待播放队列，只播放当前正在播放的片段
            try:
                with self.audio_queue.mutex:
                    self.audio_queue.queue.clear()
            except:
                pass
                
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
                    self.stream = None
                    print("音频流已关闭")
                except Exception as e:
                    print(f"关闭音频流时出错: {e}")
                    self.stream = None
        
        self.buffer_empty.set()
        self.playback_finished.set()
        self.last_audio_time = None
        print("音频流已停止")
    
    def stop_with_fadeout(self, fadeout_time=0.1):
        """使用快速淡出效果停止音频播放
        
        Args:
            fadeout_time: 淡出时间，以秒为单位，默认0.1秒
        """
        if not self.is_playing:
            return False
            
        print(f"执行快速淡出 ({fadeout_time}秒)...")
        
        # 设置打断参数
        self.smooth_interrupt = True
        self.should_stop = True
        self.interrupt_time = time.time()
        
        # 设置淡出参数
        self.fade_out_enabled = True
        self.fade_out_duration = fadeout_time  # 使用指定的淡出时间
        self.fade_out_active = True  # 立即开始淡出
        self.fade_out_start_time = time.time()
        
        # 设置最大等待时间略长于淡出时间
        self.max_finish_duration = fadeout_time + 0.05
        
        # 清空音频队列，只处理当前正在播放的片段
        try:
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()
        except:
            pass
            
        return True
    
    def stop_immediately(self):
        """立即停止音频播放并清空队列"""
        # 首先设置所有标志位
        self.should_stop = True
        self.is_playing = False
        self.smooth_interrupt = False
        self.fade_out_active = False
        
        # 清空队列
        try:
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()
        except Exception as e:
            print(f"清空音频队列出错(已忽略): {e}")
        
        # 播放一段短暂的静音以平滑过渡
        if self.stream and self.fade_out_enabled:
            try:
                print("播放短暂静音以实现平滑结束...")
                silent_samples = int(PLAYER_RATE * 0.02)  # 缩短静音时长
                silence = np.zeros(silent_samples, dtype=np.int16)
                
                with self.stream_lock:
                    if self.stream:
                        try:
                            self.stream.write(silence.tobytes(), exception_on_underflow=False)
                        except Exception:
                            pass  # 忽略任何错误，确保能继续执行
            except Exception as e:
                print(f"播放静音时出错(已忽略): {e}")
        
        # 强制停止音频线程
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=0.5)  # 减少等待时间
        
        # 关闭并释放音频流
        with self.stream_lock:
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                    print(f"关闭音频流时出错(已忽略): {e}")
                finally:
                    self.stream = None
        
        # 重置所有状态
        self.buffer_empty.set()
        self.playback_finished.set()
        self.last_audio_time = None
        self.fade_out_active = False
        self.fade_out_start_time = None
        self.interrupt_time = None
        
        print("音频流已立即停止")
    
    def close(self):
        """关闭音频设备"""
        self.stop_stream()
        
        try:
            self.p.terminate()
        except Exception as e:
            print(f"终止PyAudio时出错(已忽略): {e}")