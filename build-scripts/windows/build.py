#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Qwen-Omni 语音助手Windows打包脚本
使用PyInstaller将程序打包为Windows可执行文件
"""

import os
import sys
import shutil
import subprocess
import platform
import tempfile

# 确保在正确的工作目录下
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, '../..'))
os.chdir(project_root)

# 检查是否在Windows平台上运行
if platform.system().lower() != 'windows':
    print("错误: 此打包脚本仅适用于Windows平台")
    sys.exit(1)

def clean_dist():
    """清理旧的构建文件"""
    print("正在清理旧的构建文件...")
    dirs_to_clean = ['build', 'dist']
    for dir_path in dirs_to_clean:
        if os.path.exists(dir_path):
            try:
                shutil.rmtree(dir_path)
                print(f"  已删除 {dir_path}/")
            except Exception as e:
                print(f"  警告: 无法删除 {dir_path}/: {e}")

def check_dependencies():
    """检查必要的依赖"""
    print("正在检查系统依赖...")
    
    # 检查PyInstaller
    try:
        import PyInstaller
        print(f"  已安装 PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("  未找到 PyInstaller，将尝试安装")
        return False
    
    return True

def install_requirements():
    """安装所需的依赖"""
    print("正在安装PyInstaller和所需依赖...")
    
    # 首先尝试使用uv
    try:
        subprocess.run(['uv', 'pip', 'install', 'pyinstaller'], check=True)
        subprocess.run(['uv', 'pip', 'install', '-r', 'requirements.txt'], check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"  使用uv安装失败: {e}")
    
    # 尝试使用标准pip
    try:
        subprocess.run([sys.executable, '-m', 'ensurepip', '--upgrade'], check=False)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'], check=False)
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'], check=True)
        return True
    except subprocess.SubprocessError as e:
        print(f"  使用pip安装失败: {e}")
        return False

def create_spec_file():
    """创建PyInstaller的spec文件"""
    print("正在创建spec文件...")
    
    # 使用direct_spec.txt模板
    direct_template_path = os.path.join(script_dir, 'direct_spec.txt')
    if os.path.exists(direct_template_path):
        try:
            with open(direct_template_path, 'r', encoding='utf-8') as f:
                spec_content = f.read()
            print("  已从模板文件加载spec内容")
            
            # 确保文件没有GBK不支持的字符
            try:
                spec_content.encode('gbk', errors='strict')
            except UnicodeEncodeError:
                print("  警告: 模板文件包含GBK编码不支持的字符，将进行替换")
                spec_content = spec_content.encode('gbk', errors='replace').decode('gbk')
            
            with open('qwen_omni.spec', 'w', encoding='utf-8') as f:
                f.write(spec_content)
            print("  已创建 qwen_omni.spec")
            return True
        except Exception as e:
            print(f"  模板加载失败: {e}")
    
    # 使用内置模板作为备份方案
    print("  使用内置模板")
    spec_content = """# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

datas = [
    ('web/templates', 'web/templates'),
    ('web/static', 'web/static'),
    ('assets/Qwen.ico', 'assets'),
]

if os.path.exists('key.json'):
    datas.append(('key.json', '.'))

hiddenimports = [
    'pyaudio', 'numpy', 'webview', 'threading', 'json',
    'platform', 'webview.platforms.winforms',
]

a = Analysis(
    ['app.py'],
    pathex=[os.path.abspath('.')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='QwenOmniVoiceAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='assets/Qwen.ico',
    version='file_version.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='QwenOmniVoiceAssistant',
)
"""
    
    try:
        with open('qwen_omni.spec', 'w', encoding='utf-8') as f:
            f.write(spec_content)
        print("  已创建 qwen_omni.spec")
        return True
    except Exception as e:
        print(f"  创建spec文件失败: {e}")
        return False

def find_pyinstaller():
    """查找PyInstaller可执行文件的路径"""
    paths_to_check = [
        # 当前Python环境的Scripts目录
        os.path.join(os.path.dirname(sys.executable), 'Scripts', 'pyinstaller.exe'),
        os.path.join(os.path.dirname(sys.executable), 'Scripts', 'pyinstaller'),
        # 用户安装的PyInstaller
        shutil.which('pyinstaller'),
        # 通过模块运行
        sys.executable + ' -m PyInstaller',
    ]
    
    for path in paths_to_check:
        if path and (os.path.exists(path) or ' -m ' in path):
            return path
    
    # 备选方案：直接使用Python -m
    return [sys.executable, '-m', 'PyInstaller']

def build_executable():
    """使用PyInstaller构建可执行文件"""
    print("正在构建Windows可执行文件...")
    
    # 查找PyInstaller
    pyinstaller_path = find_pyinstaller()
    
    # 准备命令
    if isinstance(pyinstaller_path, list):
        cmd = pyinstaller_path + ['qwen_omni.spec', '--clean']
    elif ' -m ' in pyinstaller_path:
        cmd_parts = pyinstaller_path.split(' -m ')
        cmd = [cmd_parts[0], '-m', cmd_parts[1], 'qwen_omni.spec', '--clean']
    else:
        cmd = [pyinstaller_path, 'qwen_omni.spec', '--clean']
    
    print(f"  执行命令: {' '.join(cmd)}")
    
    try:
        # 设置环境变量以强制使用UTF-8
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'  # 强制Python使用UTF-8模式
        
        # 针对Windows命令行的处理
        if platform.system().lower() == 'windows':
            # 确保当前控制台使用UTF-8编码
            os.system('chcp 65001 > nul')
        
        # 创建临时文件捕获输出
        temp_log_path = None
        result = 1  # 默认为失败状态
        
        try:
            with tempfile.NamedTemporaryFile(delete=False, mode='w+', encoding='utf-8', suffix='.log') as tmp:
                temp_log_path = tmp.name
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1,
                    env=env,
                    encoding='utf-8',
                    errors='replace'
                )
                
                # 实时输出日志
                for line in process.stdout:
                    try:
                        line = line.strip()
                        if line:
                            print(f"  {line}")
                            tmp.write(line + '\n')
                    except UnicodeEncodeError:
                        # 如果无法在控制台显示，仅写入日志文件
                        tmp.write("(non-displayable characters)" + '\n')
                
                # 等待进程完成
                result = process.wait()
        except Exception as e:
            print(f"  PyInstaller runtime error: {e}")
            if temp_log_path and os.path.exists(temp_log_path):
                print(f"  Log saved to: {temp_log_path}")
            return False
        finally:
            # 检查是否成功完成
            if result != 0:
                if temp_log_path and os.path.exists(temp_log_path):
                    print(f"  Build failed (code {result}), log saved to: {temp_log_path}")
                return False
            else:
                # 尝试删除临时文件，但如果删除失败也不影响构建结果
                if temp_log_path and os.path.exists(temp_log_path):
                    try:
                        os.unlink(temp_log_path)
                    except Exception as e:
                        print(f"  Note: Cannot delete temp file: {e}")
                print("  Build completed!")
                
                # 检查dist目录确认是否真的构建成功
                if os.path.exists(os.path.join('dist', 'QwenOmniVoiceAssistant')):
                    return True
                else:
                    print("  Warning: Build output not found")
                    return False
                
    except Exception as e:
        print(f"  Build process error: {str(e).encode('ascii', errors='replace').decode('ascii')}")
        return False

def copy_additional_files():
    """复制其他必要的运行时文件"""
    print("正在复制其他必要文件...")
    success = True
    
    # 检查目标目录是否存在
    target_dir = os.path.join('dist', 'QwenOmniVoiceAssistant')
    if not os.path.exists(target_dir):
        print(f"  错误: 目标目录不存在: {target_dir}")
        return False
    
    # 复制README和其他文档
    if os.path.exists('README.md'):
        try:
            shutil.copy2('README.md', target_dir)
            print("  已复制 README.md")
        except Exception as e:
            print(f"  警告: 复制README失败: {e}")
            success = False
            
    # 确保key.json被复制到正确位置
    if os.path.exists('key.json'):
        try:
            shutil.copy2('key.json', target_dir)
            print("  已复制 key.json 到应用根目录")
        except Exception as e:
            print(f"  警告: 复制key.json失败: {e}")
            success = False
    else:
        print("  警告: 未找到key.json文件，将无法使用API功能")
        
    # 复制版本信息文件
    if os.path.exists('file_version.txt'):
        try:
            shutil.copy2('file_version.txt', target_dir)
            print("  已复制 file_version.txt 到应用根目录")
        except Exception as e:
            print(f"  警告: 复制版本信息文件失败: {e}")
            success = False
    
    return success

def create_shortcut():
    """创建桌面快捷方式脚本"""
    print("创建快捷方式脚本...")
    shortcut_script = '''@echo off
echo 正在创建桌面快捷方式...
powershell "$s=(New-Object -COM WScript.Shell).CreateShortcut('%userprofile%\\Desktop\\Qwen-Omni语音助手.lnk');$s.TargetPath='%~dp0QwenOmniVoiceAssistant\\QwenOmniVoiceAssistant.exe';$s.IconLocation='%~dp0QwenOmniVoiceAssistant\\assets\\Qwen.ico';$s.Save()"
echo 快捷方式已创建!
pause
'''
    
    try:
        with open('dist/创建桌面快捷方式.bat', 'w', encoding='utf-8') as f:
            f.write(shortcut_script)
        print("  已创建快捷方式脚本")
        
        # 创建一个中文名称的快捷方式批处理文件
        cn_batch = '''@echo off
echo 创建"Qwen-Omni语音助手"快捷方式...
cd /d "%~dp0"
if not exist "QwenOmniVoiceAssistant.exe" cd QwenOmniVoiceAssistant
start QwenOmniVoiceAssistant.exe
exit
'''
        with open('dist/QwenOmniVoiceAssistant/启动语音助手.bat', 'w', encoding='utf-8') as f:
            f.write(cn_batch)
        print("  已创建启动批处理文件")
        
        return True
    except Exception as e:
        print(f"  创建快捷方式脚本失败: {e}")
        return False

def rename_dist_folder():
    """将英文目录重命名为中文（可选）"""
    try:
        # 尝试创建一个中文名称的符号链接或快捷方式
        if os.path.exists('dist/QwenOmniVoiceAssistant'):
            print("创建中文名称的启动文件...")
            
            # 创建一个README说明
            readme_content = '''# Qwen-Omni 语音助手

这是Qwen-Omni语音助手的Windows版本。

请双击"启动语音助手.bat"文件来运行应用程序。
或者运行上一级目录中的"创建桌面快捷方式.bat"来创建桌面快捷方式。

注意：由于Windows系统编码限制，应用程序文件夹使用英文名称，但功能与界面仍然是中文的。
'''
            with open('dist/QwenOmniVoiceAssistant/使用说明.txt', 'w', encoding='utf-8') as f:
                f.write(readme_content)
            
            return True
    except Exception as e:
        print(f"  创建中文访问方式失败: {e}")
    return False

def create_version_file():
    """创建版本信息文件"""
    print("创建版本信息文件...")
    version_content = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(0, 0, 1, 0),
    prodvers=(0, 0, 1, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [StringStruct(u'CompanyName', u''),
           StringStruct(u'FileDescription', u'Qwen-Omni Voice Assistant'),
           StringStruct(u'FileVersion', u'0.0.1'),
           StringStruct(u'InternalName', u'QwenOmniVoiceAssistant'),
           StringStruct(u'LegalCopyright', u''),
           StringStruct(u'OriginalFilename', u'QwenOmniVoiceAssistant.exe'),
           StringStruct(u'ProductName', u'Qwen-Omni Voice Assistant'),
           StringStruct(u'ProductVersion', u'Windows 0.0.1')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)"""
    
    try:
        with open('file_version.txt', 'w', encoding='utf-8') as f:
            f.write(version_content)
        print("  已创建版本信息文件")
        return True
    except Exception as e:
        print(f"  创建版本信息文件失败: {e}")
        return False

def main():
    """主函数，运行打包流程"""
    print("==== Qwen-Omni Voice Assistant Windows Build Tool ====")
    success = True
    
    try:
        # 设置stdout和stderr为utf-8模式
        if sys.stdout.encoding.lower() != 'utf-8':
            # Windows命令行默认使用cp936/gbk，需要设置为utf-8
            try:
                import io
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
                sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
                os.environ['PYTHONIOENCODING'] = 'utf-8'
                print("Console encoding set to UTF-8")
            except Exception as e:
                print(f"Warning: Cannot set UTF-8 encoding: {e}")
        
        clean_dist()
        
        # 创建版本信息文件
        create_version_file()
        
        # 检查依赖并安装
        if not check_dependencies():
            if not install_requirements():
                print("Error: Cannot install required dependencies")
                return 1
        
        # 创建spec文件
        if not create_spec_file():
            print("Error: Cannot create spec file")
            return 1
        
        # 构建可执行文件
        build_success = build_executable()
        if not build_success:
            # 即使PyInstaller返回失败，但检查dist目录是否存在结果
            if os.path.exists(os.path.join('dist', 'QwenOmniVoiceAssistant')):
                print("Note: Despite errors, build output found. Continuing.")
                build_success = True
            else:
                print("Error: Build failed, no output found")
                return 1
        
        # 复制额外文件
        copy_additional_files()
        
        # 创建快捷方式脚本
        create_shortcut()
        
        # 创建中文访问方式
        rename_dist_folder()
        
        # 最后检查构建结果
        if os.path.exists(os.path.join('dist', 'QwenOmniVoiceAssistant', 'QwenOmniVoiceAssistant.exe')):
            print("\nBuild successful! Executable at: dist/QwenOmniVoiceAssistant/QwenOmniVoiceAssistant.exe")
            print("You can run 'dist/创建桌面快捷方式.bat' to create desktop shortcut")
            print("Or directly run 'dist/QwenOmniVoiceAssistant/启动语音助手.bat'")
            success = True
        else:
            print("\nWarning: Final executable not found, build may not be complete")
            success = False
            
    except UnicodeEncodeError as e:
        # 特别处理编码错误
        print("Error: Encoding issue caused build failure")
        print("Try the following:")
        print("1. Run 'chcp 65001' in command prompt")
        print("2. Then run this script again")
        return 1
    except Exception as e:
        # 确保异常信息能正确显示
        try:
            error_msg = str(e)
            print(f"Error during build process: {error_msg}")
        except UnicodeEncodeError:
            # 如果无法显示错误消息，使用ascii编码替换不可显示字符
            error_msg = str(e).encode('ascii', errors='replace').decode('ascii')
            print(f"Error during build process: {error_msg}")
        return 1
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main()) 