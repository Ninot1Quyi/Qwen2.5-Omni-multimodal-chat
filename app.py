import os
import sys
import webview
import threading
import argparse
from webview_api import VoiceChatAPI

def run_server():
    """启动pywebview服务器"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 创建API实例
    api = VoiceChatAPI()
    
    # 创建窗口配置
    window_settings = {
        'width': 400,
        'height': 433,
        'resizable': True,
        'min_size': (400, 433),
        'background_color': '#FFFFFF',
        'title': 'Qwen-Omni 语音助手',
        'text_select': False,
    }
    
    # 创建窗口并加载HTML
    window = webview.create_window(
        title=window_settings['title'],
        url='file://' + os.path.join(current_dir, 'web/templates/index.html'),
        js_api=api,
        width=window_settings['width'],
        height=window_settings['height'],
        resizable=window_settings['resizable'],
        min_size=window_settings['min_size'],
        background_color=window_settings['background_color'],
        text_select=window_settings['text_select'],
    )
    
    # 设置窗口引用
    api.set_window(window)
    
    # 启动窗口
    webview.start(debug=True, http_server=True)

def run_console():
    """运行命令行版本"""
    from voice_chat import QwenVoiceChat
    voice_chat = QwenVoiceChat()
    try:
        voice_chat.start_conversation()
    except KeyboardInterrupt:
        print("\n命令行版本已终止")
    finally:
        voice_chat.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qwen-Omni 语音助手")
    parser.add_argument('--console', action='store_true', help='在命令行模式下运行')
    args = parser.parse_args()
    
    if args.console:
        run_console()
    else:
        run_server() 