import base64
import wave
import io
import numpy as np
import pyaudio

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