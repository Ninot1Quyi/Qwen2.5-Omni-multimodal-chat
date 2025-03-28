import threading
import time
import json
import random
import numpy as np
import math
from voice_chat import QwenVoiceChat

class VoiceChatAPI:
    def __init__(self):
        self.voice_chat = None
        self.conversation_thread = None
        self.is_running = False
        self.window = None
        self.status = "idle"
        self.volume_update_thread = None
        self.stop_volume_updates = threading.Event()
    
    def set_window(self, window):
        """设置pywebview窗口对象"""
        self.window = window
    
    def check_connection(self):
        """检查与后端的连接"""
        return {'success': True, 'message': '连接成功'}
    
    def start_conversation(self):
        """开始语音对话"""
        if self.is_running:
            return {'success': False, 'message': '会话已经在运行中'}
        
        try:
            self.voice_chat = QwenVoiceChat()
            self.is_running = True
            self.stop_volume_updates.clear()
            self.conversation_thread = threading.Thread(target=self.run_conversation)
            self.conversation_thread.daemon = True
            self.conversation_thread.start()
            
            # 启动音量数据模拟线程
            self.volume_update_thread = threading.Thread(target=self.simulate_volume_data)
            self.volume_update_thread.daemon = True
            self.volume_update_thread.start()
            
            return {'success': True, 'message': '会话已开始'}
        except Exception as e:
            return {'success': False, 'message': f'启动失败: {str(e)}'}
    
    def stop_conversation(self):
        """停止语音对话"""
        if not self.is_running:
            return {'success': False, 'message': '没有运行中的会话'}
        
        try:
            self.is_running = False
            self.stop_volume_updates.set()
            
            if self.voice_chat:
                self.voice_chat.interrupt_event.set()
                self.voice_chat.close()
                self.voice_chat = None
            
            if self.conversation_thread and self.conversation_thread.is_alive():
                self.conversation_thread.join(timeout=2.0)
            
            if self.volume_update_thread and self.volume_update_thread.is_alive():
                self.volume_update_thread.join(timeout=1.0)
            
            self.update_status("idle")
            return {'success': True, 'message': '会话已结束'}
        except Exception as e:
            return {'success': False, 'message': f'停止失败: {str(e)}'}
    
    def update_status(self, status):
        """更新UI状态"""
        self.status = status
        if self.window:
            self.window.evaluate_js(f'window.updateStatus("{status}")')
    
    def simulate_volume_data(self):
        """模拟音量数据并发送到前端
        
        在实际应用中，可以从AudioRecorder获取真实的音量数据
        """
        try:
            update_interval = 0.06  # 60ms更新一次
            phase_offset = 0
            time_counter = 0
            
            while self.is_running and not self.stop_volume_updates.is_set():
                if self.status == "idle":
                    time.sleep(0.1)
                    continue
                
                # 生成30个波浪点 (前端有30个波形条)
                num_points = 30
                volume_data = []
                
                # 根据状态选择不同参数
                if self.status == "speaking":
                    # 说话状态：较大振幅，较复杂的波形
                    main_frequency = 1.5
                    secondary_frequency = 3.0
                    amplitude = 0.35
                    noise_level = 0.15
                    base_level = 0.5
                else:  # 监听状态
                    # 监听状态：较小振幅，较简单的波形
                    main_frequency = 1.0
                    secondary_frequency = 2.0
                    amplitude = 0.25
                    noise_level = 0.2
                    base_level = 0.35
                
                # 生成波浪形状 (使用正弦波+噪声)
                for i in range(num_points):
                    # 正弦波组合
                    x = i / num_points * 2 * math.pi
                    wave1 = math.sin(main_frequency * x + phase_offset)
                    wave2 = math.sin(secondary_frequency * x + phase_offset * 1.5) * 0.5
                    
                    # 添加随机噪声
                    noise = (random.random() * 2 - 1) * noise_level
                    
                    # 组合所有成分
                    value = base_level + amplitude * (wave1 + wave2) + noise
                    
                    # 确保值在0-1范围内
                    value = max(0.05, min(0.95, value))
                    volume_data.append(value)
                
                # 更新相位偏移，创造波浪动态效果
                phase_offset += 0.2
                time_counter += update_interval
                
                # 发送数据到前端
                if self.window and volume_data:
                    volume_json = json.dumps(volume_data)
                    self.window.evaluate_js(f'window.updateVolumeData({volume_json})')
                
                time.sleep(update_interval)
        
        except Exception as e:
            print(f"音量模拟线程出错: {e}")
    
    def generate_wave_pattern(self, complexity=2, smoothness=0.5, length=100):
        """生成波形模式
        
        Args:
            complexity: 波形的复杂度 (频率数量)
            smoothness: 平滑度 (0-1)
            length: 模式长度
            
        Returns:
            包含波形值的数组 (0-1范围)
        """
        x = np.linspace(0, 2 * np.pi, length)
        wave = np.zeros(length)
        
        # 添加多个不同频率的正弦波
        for i in range(1, complexity + 1):
            frequency = i
            amplitude = 1.0 / (i ** smoothness)  # 高频分量振幅较小
            phase = random.random() * 2 * np.pi  # 随机相位
            wave += amplitude * np.sin(frequency * x + phase)
        
        # 归一化到0-1范围
        wave = (wave - wave.min()) / (wave.max() - wave.min())
        return wave.tolist()
    
    def run_conversation(self):
        """运行语音对话的线程方法"""
        if not self.voice_chat:
            return
        
        # 设置语音聊天参数（简化配置，使用默认值）
        self.voice_chat.recording_mode = "dynamic"
        self.voice_chat.enable_speech_recognition = False
        
        # 创建一个特殊的回调，用于更新UI状态
        def on_state_change(state):
            self.update_status(state)
        
        # 扩展原有的语音聊天类
        self.voice_chat.on_state_change = on_state_change
        
        try:
            # 修改语音聊天的主循环
            self.update_status("listening")
            
            while self.is_running:
                # 等待用户输入
                if self.voice_chat.is_ai_speaking:
                    self.update_status("speaking")
                    time.sleep(0.1)
                    continue
                
                self.update_status("listening")
                
                # 开始录音
                audio_base64, audio_file = self.voice_chat.audio_recorder.record_until_silence()
                
                if not audio_base64 or not self.is_running:
                    continue
                
                # 处理音频输入
                self.voice_chat.process_user_input(audio_base64, audio_file)
        except Exception as e:
            print(f"对话线程出错: {e}")
        finally:
            self.is_running = False
            if self.voice_chat:
                self.voice_chat.close()
            self.update_status("idle") 