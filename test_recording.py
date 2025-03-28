import os
import sys
import numpy as np
import sounddevice as sd
import soundfile as sf
import time
import subprocess
from datetime import datetime

class AudioRecorder:
    def __init__(self):
        # 音频设置
        self.RATE = 16000
        self.CHANNELS = 1
        self.DTYPE = np.int16
        
        # 创建录音文件夹
        self.recordings_dir = "test_recordings"
        if not os.path.exists(self.recordings_dir):
            os.makedirs(self.recordings_dir)
        
        # 当前选择的设备
        self.selected_device = None
        
        # 检查并请求权限
        self.check_permissions()
    
    def check_permissions(self):
        """检查并请求麦克风权限"""
        print("检查麦克风权限...")
        
        # macOS系统检查方式
        if sys.platform == 'darwin':
            try:
                # 尝试直接使用麦克风录制短音频来检查权限
                print("正在测试麦克风权限，请稍等...")
                test_recording = sd.rec(
                    frames=int(self.RATE * 0.1),  # 只录制0.1秒
                    samplerate=self.RATE,
                    channels=self.CHANNELS,
                    dtype=self.DTYPE,
                    blocking=True
                )
                
                # 检查是否真的录到了数据
                if np.max(np.abs(test_recording)) > 0:
                    print("麦克风权限正常。")
                    return True
                else:
                    print("麦克风可能没有权限或静音状态。")
            except Exception as e:
                print(f"麦克风权限测试失败: {e}")
            
            print("\n请确保已授予麦克风访问权限:")
            print("1. 打开系统偏好设置 > 安全性与隐私 > 隐私 > 麦克风")
            print("2. 确保Terminal或者Python应用已被勾选")
            print("3. 重启Terminal和应用后再试")
            
            # 尝试打开系统隐私设置
            try:
                subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"])
                print("已为您打开系统偏私设置，请授权后重新运行程序。")
            except:
                pass
                
            input("\n请确认麦克风权限已授予后按回车键继续...")
        
        # Linux系统检查方式
        elif sys.platform.startswith('linux'):
            print("在Linux系统上，请确保您的用户已被添加到'audio'组。")
            print("您也可以尝试运行 'pulseaudio --start' 来启动音频服务。")
        
        # Windows系统检查方式
        elif sys.platform == 'win32':
            print("在Windows系统上，请确保已在隐私设置中允许应用访问麦克风。")
            print("设置 > 隐私 > 麦克风")
        
        return True
    
    def get_available_devices(self):
        """获取所有可用的音频设备"""
        devices = sd.query_devices()
        input_devices = []
        
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:  # 如果是输入设备
                input_devices.append({
                    'index': i,
                    'name': device['name'],
                    'channels': device['max_input_channels'],
                    'sample_rate': int(device['default_samplerate'])
                })
        return input_devices
    
    def test_device(self, device_index, duration=1):
        """测试设备并返回最大音量"""
        try:
            print(f"测试设备 {device_index}，请说话...")
            
            # 先尝试短音频，降低延迟
            sd.sleep(500)  # 短暂等待，让用户准备好
            
            # 录制测试音频
            recording = sd.rec(
                frames=int(self.RATE * duration),
                samplerate=self.RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                device=device_index,
                blocking=True
            )
            
            # 计算最大音量
            max_volume = np.max(np.abs(recording))
            print(f"设备音量: {max_volume}")
            
            # 保存测试音频，便于调试
            test_filename = os.path.join(self.recordings_dir, f"test_device_{device_index}.wav")
            sf.write(test_filename, recording, self.RATE)
            print(f"测试音频已保存: {test_filename}")
            
            return max_volume
        except Exception as e:
            print(f"测试设备时出错: {e}")
            return 0
    
    def select_device(self):
        """让用户选择麦克风设备"""
        devices = self.get_available_devices()
        if not devices:
            print("未检测到任何麦克风设备！")
            return None
        
        print("\n===== 麦克风设备列表 =====")
        for i, device in enumerate(devices):
            print(f"{i+1}. {device['name']}")
        
        # 自动测试所有设备，找出能正常工作的
        print("\n正在自动测试所有麦克风设备...")
        working_devices = []
        for device in devices:
            print(f"\n测试设备: {device['name']} (ID: {device['index']})")
            volume = self.test_device(device['index'], 1)
            if volume > 0:
                working_devices.append({
                    'index': device['index'],
                    'name': device['name'],
                    'volume': volume
                })
                print(f"✅ 设备工作正常，音量: {volume}")
            else:
                print(f"❌ 设备未检测到声音，可能无法使用")
        
        if working_devices:
            print("\n以下设备可以正常使用:")
            for i, device in enumerate(working_devices):
                print(f"{i+1}. {device['name']} (音量: {device['volume']})")
            
            # 默认选择音量最大的设备
            best_device = max(working_devices, key=lambda x: x['volume'])
            print(f"\n推荐使用: {best_device['name']} (音量: {best_device['volume']})")
        
        while True:
            try:
                choice = input("\n请选择麦克风设备编号 (直接按回车使用默认/推荐设备): ")
                if not choice.strip():
                    # 使用默认设备或推荐设备
                    if working_devices:
                        self.selected_device = best_device['index']
                        print(f"使用推荐设备: {best_device['name']}")
                    else:
                        default_device = sd.query_devices(kind='input')
                        self.selected_device = default_device['index']
                        print(f"使用默认设备: {default_device['name']}")
                    return self.selected_device
                
                choice = int(choice) - 1
                if 0 <= choice < len(devices):
                    selected_device = devices[choice]
                    print(f"\n测试设备: {selected_device['name']}")
                    
                    # 进行更长时间的测试
                    print("请对着麦克风清晰地说几句话...")
                    max_volume = self.test_device(selected_device['index'], 3)
                    
                    if max_volume < 50:
                        print("警告：设备音量很低，可能没有正确捕获声音")
                        confirm = input("是否仍要使用此设备？(y/n): ")
                        if confirm.lower().strip() != 'y':
                            continue
                    
                    self.selected_device = selected_device['index']
                    print(f"已选择设备: {selected_device['name']}")
                    return self.selected_device
                else:
                    print("无效的选择，请重试")
            except ValueError:
                print("请输入有效的数字")
            except KeyboardInterrupt:
                print("\n选择已取消")
                return None
    
    def show_system_info(self):
        """显示系统信息和录音设置"""
        print("\n===== 系统信息 =====")
        print(f"操作系统: {sys.platform}")
        
        try:
            default_device = sd.query_devices(kind='input')
            print(f"默认输入设备: ID={default_device['index']}, 名称={default_device['name']}")
        except:
            print("无法获取默认输入设备")
        
        print("\n可用麦克风设备:")
        devices = self.get_available_devices()
        for i, device in enumerate(devices):
            print(f"{i+1}. 设备ID: {device['index']} - {device['name']} (通道数: {device['channels']})")
        print("\n===================")
    
    def record_audio(self, duration=5):
        """录制指定时长的音频"""
        # 生成文件名（包含时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.recordings_dir, f"recording_{timestamp}.wav")
        
        print(f"\n开始录音 (录制{duration}秒)...")
        print(f"录音将保存到: {filename}")
        print("请对着麦克风清晰地说话...")
        
        try:
            # 计算总采样点数
            total_samples = int(self.RATE * duration)
            
            # 使用sounddevice录制音频
            recording = sd.rec(
                frames=total_samples,
                samplerate=self.RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                device=self.selected_device,  # 使用选择的设备
                blocking=False
            )
            
            # 显示录音进度条
            print()
            for i in range(int(duration)):
                progress = int((i / duration) * 20)
                bar = "▓" * progress + "░" * (20 - progress)
                print(f"\r录音进度: {bar} {int(i/duration*100)}%", end="")
                sd.sleep(1000)  # 暂停1秒
            
            # 等待录音完成
            sd.wait()
            print("\r录音进度: ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 100%")
            
            # 计算音量统计
            max_volume = np.max(np.abs(recording))
            min_volume = np.min(np.abs(recording))
            avg_volume = np.mean(np.abs(recording))
            
            print(f"\n录音完成!")
            print(f"音量统计:")
            print(f"  - 最大音量: {max_volume}")
            print(f"  - 最小音量: {min_volume}")
            print(f"  - 平均音量: {avg_volume:.2f}")
            
            if max_volume < 100:
                print("警告：录音音量很低，可能没有正确捕获声音")
                
                # 如果音量极低，询问是否要增益
                if max_volume < 50 and max_volume > 0:
                    apply_gain = input("是否要应用增益以提高音量? (y/n): ")
                    if apply_gain.lower().strip() == 'y':
                        # 应用增益
                        gain_factor = min(100 / max_volume, 10)  # 最多增益10倍
                        recording = recording * gain_factor
                        print(f"已应用 {gain_factor:.2f}x 增益")
            
            # 保存录音
            sf.write(filename, recording, self.RATE)
            
            # 验证文件
            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                print(f"\n录音文件已保存:")
                print(f"  - 文件名: {filename}")
                print(f"  - 文件大小: {file_size} 字节")
                print(f"  - 录音时长: {duration} 秒")
                print(f"  - 采样率: {self.RATE} Hz")
                print(f"  - 通道数: {self.CHANNELS}")
                return True
            else:
                print("\n错误：录音文件未能成功保存")
                return False
            
        except Exception as e:
            print(f"\n录音错误: {e}")
            return False
    
    def close(self):
        """清理资源"""
        sd.stop()

def main():
    try:
        print("===== 麦克风测试工具 =====")
        print("此工具会测试麦克风并保存录音文件")
        
        recorder = AudioRecorder()
        
        # 显示系统信息
        recorder.show_system_info()
        
        # 选择麦克风设备
        if recorder.select_device() is None:
            print("未能选择有效的麦克风设备，程序退出")
            return
        
        while True:
            try:
                # 让用户选择录音时长
                duration_input = input("\n请输入录音时长（秒），或按回车退出: ")
                if not duration_input.strip():
                    break
                    
                duration = float(duration_input)
                if duration <= 0:
                    print("录音时长必须大于0")
                    continue
                
                # 录制音频
                recorder.record_audio(duration)
                
                # 询问是否继续
                if input("\n是否继续录音？(y/n): ").lower().strip() != 'y':
                    break
                    
            except ValueError:
                print("请输入有效的数字")
                continue
            except KeyboardInterrupt:
                print("\n录音已取消")
                break
        
        print("\n测试结束")
        
    except Exception as e:
        print(f"错误: {e}")
    finally:
        recorder.close()

if __name__ == "__main__":
    main() 