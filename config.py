import pyaudio
import json
import os

# 调试设置
DEBUG = False  # 设置为True时开启调试模式，包括保存录音文件

# 音频设置
AUDIO_FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000  # Silero VAD 支持的采样率
CHUNK = 512   # 32毫秒帧大小 (16000 * 0.032 = 512)，与 Silero VAD 兼容
RECORD_SECONDS = 5

# API 设置
try:
    with open('key.json', 'r', encoding='utf-8') as f:
        api_config = json.load(f)
    API_KEY = api_config['api_key']
    BASE_URL = api_config['base_url']
except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
    print(f"Error loading API configuration from key.json: {e}")
    API_KEY = ''
    BASE_URL = ''

# VAD 设置
MIN_SPEECH_DURATION = 0.1
SPEECH_VOLUME_THRESHOLD = 700
NORMAL_VOLUME_THRESHOLD = 500
MIN_POSITIVE_FRAMES = 3
MIN_NEGATIVE_FRAMES = 20

# 音频播放器设置
PLAYER_RATE = 24000           # 播放器采样率匹配模型输出
FADE_OUT_DURATION = 0.15      # 标准淡出持续时间（秒）
MAX_FINISH_DURATION = 0.25    # 被打断时最大允许的完成时间（秒）