import os
import sys
import webview
import threading
import argparse
import platform
from webview_api import AgentAPI
from utils import apply_windows_compatibility_patches
from Agent import Agent
from mouth import Mouth
from ears import Ears

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
    api = AgentAPI()
    
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
    
    # 在Windows上使用MSHTML (轻量级选择)
    if system_platform == 'windows':
        try:
            # 尝试使用Edge WebView2（如果系统已安装）
            gui_options = 'edgechromium'
            print("[INFO] 使用Edge WebView2作为GUI后端（轻量级）")
        except Exception as e:
            # 回退到MSHTML (基于IE的渲染器)
            gui_options = 'mshtml' 
            print(f"[INFO] 使用MSHTML作为GUI后端（轻量级，回退原因: {e}）")
    else:
        # 在macOS和Linux上使用系统默认
        gui_options = None
        print("[INFO] 使用系统默认GUI后端")
    
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
    
    # 配置语音聊天默认参数（与CLI模式相同的默认配置）
    api.configure_agent({
        'recording_mode': 'dynamic',     # 默认使用动态录音模式
        'recording_seconds': 5,          # 默认录音时长（固定模式下使用）
    })
    
    # 启动窗口，应用平台特定配置
    webview.start(debug=False, http_server=True, gui=gui_options)

def run_console():
    """运行命令行版本"""
    voice_chat = Agent()
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