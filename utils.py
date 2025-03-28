import base64
import wave
import io
import numpy as np
import pyaudio
import platform
import sys
import inspect

def convert_frames_to_wav(frames, p: pyaudio.PyAudio, channels, format, rate):
    """将音频帧转换为WAV格式字节"""
    buffer = io.BytesIO()
    wf = wave.open(buffer, 'wb')
    wf.setnchannels(channels)
    wf.setsampwidth(p.get_sample_size(format))
    wf.setframerate(rate)
    wf.writeframes(b''.join(frames))
    wf.close()
    return buffer.getvalue()

def save_wav_file(filename, frames, p: pyaudio.PyAudio, channels, format, rate):
    """将音频帧保存为WAV文件"""
    wf = wave.open(filename, 'wb')
    wf.setnchannels(channels)
    wf.setsampwidth(p.get_sample_size(format))
    wf.setframerate(rate)
    wf.writeframes(b''.join(frames))
    wf.close()

def wav_to_base64(wav_bytes):
    """将WAV字节转换为base64字符串"""
    if len(wav_bytes) > 44:  # 44是WAV文件头大小
        return base64.b64encode(wav_bytes).decode("utf-8")
    return None

def calculate_volume(audio_data):
    """计算音频数据的音量"""
    return np.max(np.abs(np.frombuffer(audio_data, dtype=np.int16)))

def apply_windows_compatibility_patches():
    """为Windows平台应用兼容性补丁，解决对象类型比较问题"""
    if platform.system().lower() != 'windows':
        return  # 仅在Windows上应用补丁
    
    # 为特定类型打补丁
    import threading
    import webview
    import webview.window
    
    # 打补丁的类型列表
    classes_to_patch = [
        threading.Event,
        threading.Thread,
        webview.window.Window
    ]
    
    # 尝试添加可能存在的DOM元素类
    try:
        if hasattr(webview, 'dom') and hasattr(webview.dom, 'element'):
            classes_to_patch.append(webview.dom.element)
    except (AttributeError, ImportError):
        pass
    
    # 针对每个类应用补丁
    for cls in classes_to_patch:
        try:
            patch_class_eq(cls)
        except (TypeError, AttributeError) as e:
            print(f"警告: 无法为 {cls.__name__} 打补丁: {e}")

def patch_class_eq(cls):
    """为类添加安全的__eq__方法"""
    if hasattr(cls, '__patched_by_qwen_omni'):
        return  # 已经打过补丁了
    
    original_eq = cls.__eq__ if hasattr(cls, '__eq__') else None
    
    def safe_eq(self, other):
        if hasattr(other, '__class__'):
            class_name = str(other.__class__)
            if 'Rectangle' in class_name or 'System.Drawing' in class_name:
                return False
        if original_eq and original_eq is not object.__eq__:
            return original_eq(self, other)
        return self is other
    
    cls.__eq__ = safe_eq
    cls.__patched_by_qwen_omni = True

def monkey_patch_threading_event():
    """为threading.Event添加补丁，避免与Rectangle类型比较问题"""
    import threading
    
    # 保存原始的__eq__方法
    original_eq = threading.Event.__eq__
    
    # 定义新的__eq__方法
    def safe_eq(self, other):
        if hasattr(other, '__class__'):
            class_name = str(other.__class__)
            if 'Rectangle' in class_name or 'System.Drawing' in class_name:
                return False
        return original_eq(self, other)
    
    # 应用补丁
    threading.Event.__eq__ = safe_eq

def safe_compare(obj1, obj2):
    """安全地比较两个对象，避免类型转换问题"""
    # 如果其中一个对象是Rectangle类型，返回False
    if (hasattr(obj1, '__class__') and ('Rectangle' in str(obj1.__class__) or 'System.Drawing' in str(obj1.__class__))) or \
       (hasattr(obj2, '__class__') and ('Rectangle' in str(obj2.__class__) or 'System.Drawing' in str(obj2.__class__))):
        return False
    
    # 尝试正常比较
    try:
        return obj1 == obj2
    except (TypeError, Exception):
        # 类型不兼容时，比较对象标识
        return obj1 is obj2

# 在Windows平台上自动应用补丁
if platform.system().lower() == 'windows':
    monkey_patch_threading_event()