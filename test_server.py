import os
import webview
import sys

def main():
    """测试pywebview服务器配置"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"当前目录: {current_dir}")
    
    # 设置服务器静态文件目录
    static_dir = os.path.join(current_dir, 'web')
    print(f"静态文件目录: {static_dir}")
    print(f"静态文件目录存在: {os.path.exists(static_dir)}")
    
    # 检查模板和静态文件
    templates_dir = os.path.join(static_dir, 'templates')
    css_dir = os.path.join(static_dir, 'static', 'css')
    js_dir = os.path.join(static_dir, 'static', 'js')
    
    print(f"模板目录存在: {os.path.exists(templates_dir)}")
    print(f"CSS目录存在: {os.path.exists(css_dir)}")
    print(f"JS目录存在: {os.path.exists(js_dir)}")
    
    # 检查具体文件
    index_file = os.path.join(templates_dir, 'index.html')
    css_file = os.path.join(css_dir, 'style.css')
    js_file = os.path.join(js_dir, 'app.js')
    
    print(f"index.html存在: {os.path.exists(index_file)}")
    print(f"style.css存在: {os.path.exists(css_file)}")
    print(f"app.js存在: {os.path.exists(js_file)}")
    
    try:
        # 创建一个简单的窗口
        window = webview.create_window(
            '测试', 
            'file://' + os.path.join(current_dir, 'web/templates/index.html'),
            width=800, 
            height=600
        )
        
        # 启动服务器
        print("正在启动服务器...")
        webview.start(debug=True, http_server=True)
        
    except Exception as e:
        print(f"出错: {e}")
        
if __name__ == "__main__":
    main() 