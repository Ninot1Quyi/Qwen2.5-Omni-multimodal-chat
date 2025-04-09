import threading
import time
import json
import random
import numpy as np
import math
import sys
import platform
from Agent import Agent
from mouth import Mouth
from ears import Ears

# 创建一个Window包装类，用于安全地访问window对象
class WindowWrapper:
    def __init__(self, window=None):
        self._window = window
    
    def set_window(self, window):
        self._window = window
    
    def evaluate_js(self, js_code):
        """安全地执行JavaScript代码"""
        if self._window:
            try:
                return self._window.evaluate_js(js_code)
            except Exception as e:
                print(f"执行JavaScript失败: {e}")
                return None
        return None
    
    # 避免与Rectangle进行比较
    def __eq__(self, other):
        if hasattr(other, '__class__'):
            class_name = str(other.__class__)
            if 'Rectangle' in class_name:
                return False
        return self is other
    
    def __hash__(self):
        return hash(id(self))

class AgentAPI:
    def __init__(self):
        # 初始化应用状态
        self.window = None
        self.is_running = False
        self.agent = None
        self.debug_mode = False
        
        # Agent配置默认值
        self.agent_config = {
            'recording_mode': 'dynamic',  # 默认使用动态录音模式
            'recording_seconds': 5,       # 默认录音时长（固定模式下使用）
        }
        
        # 状态监测与控制
        self.status = "idle"  # 当前状态：idle, listening, speaking
        self.window_wrapper = WindowWrapper()  # 使用包装类
        self.volume_update_thread = None
        # 修改以避免Rectangle.op_Equality兼容性问题
        self._stop_volume_updates = False  # 使用布尔标志替代Event对象
    
    # 添加特殊方法以解决Windows平台的兼容性问题
    def __eq__(self, other):
        # 用于解决Windows下System.Drawing.Rectangle比较问题
        if hasattr(other, '__class__'):
            class_name = str(other.__class__)
            # 检查是否与Rectangle类型比较
            if 'Rectangle' in class_name:
                return False
            # 检查是否与Window类型比较
            if 'Window' in class_name or 'webview.window' in class_name:
                return False
        return self is other
    
    def __hash__(self):
        # 配合__eq__方法一起实现正确的哈希表行为
        return hash(id(self))
    
    def set_window(self, window):
        """设置pywebview窗口对象"""
        self.window_wrapper.set_window(window)
    
    def configure_agent(self, config):
        """配置Agent参数"""
        # 更新配置
        for key, value in config.items():
            if key in self.agent_config:
                self.agent_config[key] = value
                
        # 如果Agent实例已存在，则更新其配置
        if self.agent:
            # 更新配置
            self.agent.recording_mode = self.agent_config['recording_mode']
            self.agent.recording_seconds = self.agent_config['recording_seconds']
            
        return {"status": "success", "message": "Agent配置已更新"}
    
    def check_connection(self):
        """检查与后端的连接"""
        return {'success': True, 'message': '连接成功'}
    
    def start_conversation(self):
        """开始语音对话"""
        if self.is_running:
            return {'success': False, 'message': '会话已经在运行中'}
        
        try:
            # 初始化Agent实例
            self.agent = Agent(
                gui_mode=True,
                recording_mode=self.agent_config['recording_mode'],
                recording_seconds=self.agent_config['recording_seconds'],
                on_state_change=self.update_status
            )
            
            # 设置运行状态
            self.is_running = True
            self._stop_volume_updates = False  # 清除停止标志
            
            # 启动语音对话
            success = self.agent.start()
            if not success:
                return {'success': False, 'message': '启动失败'}
            
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
            print("正在停止语音对话...")
            self.is_running = False
            self._stop_volume_updates = True  # 设置停止标志
            
            if self.agent:
                # 停止语音对话
                self.agent.stop()
                self.agent = None
            
            # 等待音量更新线程结束
            if self.volume_update_thread and self.volume_update_thread.is_alive():
                self.volume_update_thread.join(timeout=1.0)
                print("音量更新线程已终止")
            
            # 更新UI状态
            self.update_status("idle")
            print("语音对话已完全停止")
            
            return {'success': True, 'message': '会话已结束'}
        except Exception as e:
            print(f"停止语音对话时出错: {str(e)}")
            return {'success': False, 'message': f'停止失败: {str(e)}'}
    
    def update_status(self, status):
        """更新UI状态"""
        self.status = status
        self.window_wrapper.evaluate_js(f'window.updateStatus("{status}")')
    
    def simulate_volume_data(self):
        """模拟音量数据并发送到前端
        
        在实际应用中，可以从AudioRecorder获取真实的音量数据
        """
        try:
            update_interval = 0.06  # 60ms更新一次
            phase_offset = 0
            time_counter = 0
            
            while self.is_running and not self._stop_volume_updates:
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
                if volume_data:
                    volume_json = json.dumps(volume_data)
                    self.window_wrapper.evaluate_js(f'window.updateVolumeData({volume_json})')
                
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