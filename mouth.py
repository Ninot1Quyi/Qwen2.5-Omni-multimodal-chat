import base64
import numpy as np
import pyaudio
import threading
import time
import queue
from config import PLAYER_RATE, FADE_OUT_DURATION, MAX_FINISH_DURATION
from core_pipeline import (
    ProcessorBase, Frame, FrameType
)

class Mouth(ProcessorBase):
    """音频输出处理器 - 负责播放音频数据"""
    def __init__(self, name="audio_output"):
        super().__init__(name)
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.audio_queue = queue.Queue()
        self.is_playing = False
        self.should_stop = False
        self.smooth_interrupt = False
        self.buffer_empty = threading.Event()
        self.buffer_empty.set()  # 初始状态为空
        self.playback_finished = threading.Event()
        self.fade_out_enabled = True
        self.fade_out_duration = FADE_OUT_DURATION
        self.fade_out_active = False
        self.fade_out_start_time = None
        self.max_finish_duration = MAX_FINISH_DURATION
        self.interrupt_time = None
        self.last_audio_time = None
        self.stream_lock = threading.RLock()
        self.playback_thread = None
        
        print("[Mouth] 初始化完成")
        
    def start_stream(self):
        """启动音频输出流"""
        with self.stream_lock:
            if self.stream is not None:
                self.stop_stream()
                
            try:
                # 创建音频流
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
                
                # 启动播放线程
                self.playback_thread = threading.Thread(target=self._play_audio_continuous)
                self.playback_thread.daemon = True
                self.playback_thread.start()
                print("[Mouth] 音频输出流已创建，开始持续播放...")
                return True
            except Exception as e:
                print(f"[Mouth] 创建音频流时出错: {e}")
                self.is_playing = False
                self.stream = None
                return False
    
    def process_frame(self, frame):
        """处理帧"""
        if frame.type == FrameType.SYSTEM:
            cmd = frame.data.get("command")
            if cmd == "stop":
                self.stop_immediately()
            elif cmd == "pause":
                self.smooth_interrupt = True
                self.should_stop = True
                self.interrupt_time = time.time()
            elif cmd == "clear_pipeline":
                print("[Mouth] 收到清空管道命令，立即停止播放并清空音频队列")
                self.stop_immediately()
                # 确保音频队列为空
                while not self.audio_queue.empty():
                    try:
                        self.audio_queue.get_nowait()
                        self.audio_queue.task_done()
                    except queue.Empty:
                        break
                self.buffer_empty.set()
            
            # 处理开始播放事件
            event = frame.data.get("event")
            if event == "play_audio" and "audio_data" in frame.data:
                self.add_audio_data(frame.data["audio_data"])
                print(f"[Mouth] 收到音频数据，长度: {len(frame.data['audio_data'])} 字符")
                
        elif frame.type == FrameType.DATA:
            # 处理音频数据
            if "audio_data" in frame.data:
                self.add_audio_data(frame.data["audio_data"])
    
    def add_audio_data(self, audio_data):
        """添加音频数据到队列"""
        # 检查播放线程状态，如果不存在或已结束但状态仍为playing，则重置状态
        if self.is_playing and (self.playback_thread is None or not self.playback_thread.is_alive()):
            print("[Mouth] 检测到播放线程已结束但状态未重置，强制重置状态")
            self.is_playing = False
            self.stream = None
        
        # 如果未播放状态，则启动流
        if not self.is_playing:
            self.start_stream()
            
        if self.should_stop and not self.smooth_interrupt:
            print("[Mouth] 已停止，不再接收新音频")
            return
            
        try:
            if self.playback_finished.is_set():
                self.playback_finished.clear()
                
            # 如果是base64编码的音频
            if isinstance(audio_data, str) and (audio_data.startswith("data:audio") or len(audio_data) > 100):
                try:
                    # 提取base64部分
                    if "base64," in audio_data:
                        audio_data = audio_data.split("base64,")[1]
                    
                    wav_bytes = base64.b64decode(audio_data)
                    print(f"[Mouth] base64解码成功，长度: {len(wav_bytes)} 字节")
                    # 直接转换为numpy数组，不进行任何处理
                    audio_np = np.frombuffer(wav_bytes, dtype=np.int16)
                    audio_data = audio_np.tobytes()
                except Exception as e:
                    print(f"[Mouth] 解码base64音频失败: {e}")
                    return
            
            # 平滑打断检查
            if self.smooth_interrupt and self.interrupt_time:
                current_time = time.time()
                if current_time - self.interrupt_time > self.max_finish_duration:
                    print("[Mouth] 平滑打断已达到最大时间，停止更多音频")
                    return
            
            # 添加到队列
            self.audio_queue.put(audio_data)
            self.buffer_empty.clear()
            self.last_audio_time = time.time()
            print(f"[Mouth] 音频数据已添加到队列，当前队列大小: {self.audio_queue.qsize()}")
        except Exception as e:
            print(f"[Mouth] 音频处理错误: {e}")
            
    def _play_audio_continuous(self):
        """后台持续音频播放线程"""
        print("[Mouth] 播放线程已启动")
        buffer = b""
        min_buffer_size = 1024  # 减小缓冲区以提高响应速度
        is_initial_buffer = True
        last_check_time = time.time()
        check_interval = 0.005  # 每5毫秒检查一次终止请求
        chunks_played = 0
        
        try:
            while self.is_playing and (not self.should_stop or self.smooth_interrupt):
                current_time = time.time()
                
                # 立即检查是否有直接停止请求
                if self.should_stop and not self.smooth_interrupt:
                    print("[Mouth] 检测到直接停止请求，立即终止播放")
                    break
                
                # 处理淡出效果
                if self.smooth_interrupt and self.interrupt_time and self.fade_out_enabled and not self.fade_out_active:
                    self.fade_out_active = True
                    self.fade_out_start_time = current_time
                    print("[Mouth] 开始音量淡出效果...")
                
                # 检查是否已经到达最大完成时间
                if self.smooth_interrupt and self.interrupt_time:
                    elapsed = current_time - self.interrupt_time
                    if elapsed > self.max_finish_duration * 0.8:  # 降低到80%的最大等待时间
                        print("[Mouth] 达到最大等待时间的80%，强制停止音频")
                        break
                
                try:
                    # 处理队列中的音频数据
                    chunks_processed = 0
                    while not self.audio_queue.empty():
                        # 每处理几个数据块就检查一次终止请求
                        chunks_processed += 1
                        if chunks_processed % 5 == 0 and self.should_stop and not self.smooth_interrupt:
                            print("[Mouth] 数据处理中检测到停止请求，立即终止")
                            break
                            
                        chunk = self.audio_queue.get(block=False)
                        buffer += chunk
                        self.audio_queue.task_done()
                    
                    # 再次检查终止请求
                    if self.should_stop and not self.smooth_interrupt:
                        print("[Mouth] 数据处理后检测到停止请求，立即终止")
                        break
                    
                    # 当缓冲区有足够数据，或者是最后的数据时播放
                    if len(buffer) >= min_buffer_size or (len(buffer) > 0 and self.audio_queue.empty()):
                        if is_initial_buffer:
                            print("[Mouth] 初始缓冲完成，开始平滑播放...")
                            is_initial_buffer = False
                        
                        # 对当前块应用淡出效果（如果需要）
                        if self.fade_out_active and self.fade_out_start_time:
                            fade_progress = min(1.0, (current_time - self.fade_out_start_time) / self.fade_out_duration)
                            audio_data = np.frombuffer(buffer, dtype=np.int16)
                            
                            # 使用非线性淡出曲线，在开始时变化较慢，结束时变化较快
                            volume_factor = max(0, 1.0 - (fade_progress * fade_progress))
                            
                            # 应用音量变化
                            audio_data = (audio_data * volume_factor).astype(np.int16)
                            buffer = audio_data.tobytes()
                            
                            # 如果淡出接近完成，结束播放
                            if fade_progress >= 0.6:  # 降低阈值，当达到60%时就结束
                                print(f"[Mouth] 淡出已达到阈值 {fade_progress:.2f}，结束播放")
                                break
                        
                        # 检查是否应当强制停止(如果打断且超过了最大时间)
                        if self.smooth_interrupt and self.interrupt_time:
                            elapsed = current_time - self.interrupt_time
                            if elapsed > self.max_finish_duration * 0.4:  # 进一步减小等待时间到40%
                                print("[Mouth] 打断等待时间过长，强制停止")
                                break
                        
                        # 播放前再次检查终止请求
                        if self.should_stop and not self.smooth_interrupt:
                            print("[Mouth] 播放前检测到停止请求，立即终止")
                            break
                        
                        # 播放音频数据
                        with self.stream_lock:
                            if self.stream and (not self.should_stop or self.smooth_interrupt):
                                try:
                                    # 将大块数据分成小块播放，每块之间检查终止请求
                                    if len(buffer) > 2048 and not self.smooth_interrupt:
                                        chunks = [buffer[i:i+2048] for i in range(0, len(buffer), 2048)]
                                        for i, small_chunk in enumerate(chunks):
                                            # 每播放一小块就检查终止请求
                                            if i > 0 and self.should_stop and not self.smooth_interrupt:
                                                print(f"[Mouth] 分块播放中检测到停止请求，已播放{i}/{len(chunks)}块，立即终止")
                                                break
                                            self.stream.write(small_chunk, exception_on_underflow=False)
                                            chunks_played += 1
                                    else:
                                        self.stream.write(buffer, exception_on_underflow=False)
                                        chunks_played += 1
                                    print(f"[Mouth] 已播放音频数据，总计 {chunks_played} 个块")
                                except Exception as e:
                                    print(f"[Mouth] 音频播放过程中出错: {e}")
                                    break
                        buffer = b""
                    
                    # 检查是否应当结束播放
                    if self.audio_queue.empty() and len(buffer) == 0:
                        if self.smooth_interrupt:
                            print("[Mouth] 平滑打断：当前音频已完成")
                            break
                        
                        # 检查两次音频之间的等待时间
                        if self.last_audio_time:
                            wait_time = current_time - self.last_audio_time
                            if wait_time > 1.0:  # 如果超过1秒没有新音频，结束播放
                                print(f"[Mouth] 等待音频数据超时，播放完成")
                                break
                    
                    # 如果队列为空，短暂暂停以避免CPU占用过高
                    if self.audio_queue.empty() and not self.should_stop:
                        # 用更短的时间轮询，提高响应性
                        time.sleep(0.01)
                    
                    # 定期检查是否需要退出
                    if current_time - last_check_time >= check_interval:
                        last_check_time = current_time
                        if self.should_stop and not self.smooth_interrupt:
                            break
                
                except Exception as e:
                    print(f"[Mouth] 音频处理循环出错: {e}")
                    break
        except Exception as e:
            print(f"[Mouth] 播放线程异常: {e}")
        finally:
            # 确保线程结束时总是重置播放状态
            self.is_playing = False
            self.should_stop = False
            self.playback_finished.set()
            self.buffer_empty.set()
            
            # 关闭音频流
            with self.stream_lock:
                if self.stream:
                    try:
                        self.stream.stop_stream()
                        self.stream.close()
                    except Exception as e:
                        print(f"[Mouth] 关闭音频流时出错: {e}")
                    finally:
                        self.stream = None
            
            print(f"[Mouth] 播放线程结束，共播放了 {chunks_played} 个音频块")
            
            # 显式重置播放状态变量，确保下次能重新启动
            self.playback_thread = None
    
    def is_audio_complete(self):
        """检查音频播放是否已完成"""
        return self.buffer_empty.is_set() and self.audio_queue.empty()
    
    def request_smooth_interrupt(self):
        """请求平滑打断播放"""
        if not self.is_playing:
            return False
        
        self.smooth_interrupt = True
        self.should_stop = True
        self.interrupt_time = time.time()
        print("[Mouth] 已请求平滑打断播放")
        
        if self.playback_thread and self.playback_thread.is_alive():
            return True
        
        return False
    
    def stop_with_fadeout(self, fadeout_time=0.1):
        """停止播放并应用淡出效果"""
        if fadeout_time > 0:
            self.fade_out_duration = fadeout_time
            return self.request_smooth_interrupt()
        else:
            return self.stop_immediately()
    
    def stop_stream(self):
        """关闭音频流但不中断当前播放"""
        with self.stream_lock:
            self.should_stop = True
            
            if self.stream:
                try:
                    print("[Mouth] 开始关闭音频流...")
                    
                    # 清空队列
                    while not self.audio_queue.empty():
                        try:
                            self.audio_queue.get_nowait()
                            self.audio_queue.task_done()
                        except queue.Empty:
                            break
                    
                    # 关闭流
                    self.stream.stop_stream()
                    self.stream.close()
                    self.stream = None
                
                    # 设置事件
                    self.buffer_empty.set()
                    self.playback_finished.set()
                    
                    # 等待播放线程结束 (加入超时防止死锁)
                    if self.playback_thread and self.playback_thread.is_alive():
                        print("[Mouth] 等待播放线程结束...")
                        self.playback_thread.join(timeout=1.0)
                    
                    # 无论线程是否结束，都强制重置状态
                    self.is_playing = False
                    self.smooth_interrupt = False
                    self.fade_out_active = False
                    self.playback_thread = None
                    
                    print("[Mouth] 音频流已完全关闭")
                    return True
                    
                except Exception as e:
                    print(f"[Mouth] 关闭音频流时出错: {e}")
                    # 出错时也重置关键状态
                    self.is_playing = False
                    self.playback_thread = None
                    return False
    
    def stop_immediately(self):
        """立即停止所有播放"""
        print("[Mouth] 执行立即停止...")
        
        # 设置标志
        self.should_stop = True
        self.smooth_interrupt = False
        
        # 清空队列
        try:
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                    self.audio_queue.task_done()
                except queue.Empty:
                    break
        except:
            pass
            
        # 停止流
        success = self.stop_stream()
        return success
    
    def close(self):
        """关闭并清理资源"""
        self.stop_immediately()
        if self.p:
            try:
                self.p.terminate()
            except Exception as e:
                print(f"[Mouth] 终止PyAudio时出错: {e}")