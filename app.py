import os
import sys
import webview
import threading
import argparse
import platform
from webview_api import VoiceChatAPI
from utils import apply_windows_compatibility_patches

def run_server(headless=False):
    """启动pywebview服务器
    
    Args:
        headless: 如果为True，则以无GUI模式运行
    """
    # 在Windows平台上应用兼容性补丁
    if platform.system().lower() == 'windows':
        apply_windows_compatibility_patches()
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 创建API实例
    api = VoiceChatAPI()
    
    # 如果是无GUI模式，跳过GUI初始化
    if headless:
        # 模拟window对象
        class DummyWindow:
            def evaluate_js(self, js_code):
                pass
        
        api.set_window(DummyWindow())
        # 启动无GUI的对话线程
        api.start_conversation()
        try:
            # 主线程等待
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            api.stop_conversation()
            return
    
    # 创建窗口配置
    window_settings = {
        'width': 400,
        'height': 550,
        'resizable': True,
        'min_size': (400, 550),
        'background_color': '#FFFFFF',
        'title': 'Qwen-Omni 语音助手',
        'text_select': False,
    }
    
    # 根据平台选择最合适的渲染器
    system_platform = platform.system().lower()
    
    # 在Windows上直接使用cwebview (最简单的选择)
    if system_platform == 'windows':
        try:
            # 注意：这里使用cwebview，它比mshtml更现代，且避免了Rectangle兼容性问题
            gui_options = 'cwebview'
            print("[INFO] 使用CWebView作为GUI后端")
        except Exception as e:
            # 回退到mshtml
            gui_options = 'mshtml' 
            print(f"[INFO] 使用MSHTML作为GUI后端 (回退: {e})")
    else:
        # 在macOS和Linux上使用系统默认
        gui_options = None
    
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
    
    # 启动窗口，应用平台特定配置
    webview.start(debug=False, http_server=True, gui=gui_options)

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
    parser.add_argument('--headless', action='store_true', help='无GUI模式运行')
    args = parser.parse_args()
    
    if args.console:
        run_console()
    else:
        run_server(headless=args.headless) 