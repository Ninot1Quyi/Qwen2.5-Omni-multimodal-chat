"""
运行基于AutoGen-Core的Agent系统
"""

import asyncio
import os
import argparse
import sys
from typing import Optional

import autogen_core
from Agent import AgentSystem, AgentState


async def run_agent_system(recording_mode: str = "dynamic", recording_seconds: int = 5) -> None:
    """
    运行Agent系统
    
    Args:
        recording_mode: 录音模式，"dynamic"或"fixed"
        recording_seconds: 固定录音时长，默认5秒
    """
    print("正在启动Agent系统...")
    
    # 创建Agent系统
    agent_system = AgentSystem("实时语音交互系统")
    
    # 初始化并启动系统
    await agent_system.initialize()
    await agent_system.start()
    
    # 设置录音模式
    await agent_system.set_recording_mode(recording_mode, recording_seconds)
    
    # 显示系统信息
    print("\n===== 系统信息 =====")
    mics = await agent_system.get_available_microphones()
    print("\n可用麦克风:")
    for i, mic in enumerate(mics):
        print(f"{i+1}. 设备ID: {mic['index']} - {mic['name']} (通道数: {mic['channels']})")
    
    print(f"\n录音模式: {'固定时长' if recording_mode == 'fixed' else '动态'}")
    if recording_mode == 'fixed':
        print(f"录音时长: {recording_seconds}秒")
    
    print("\n您可以在AI说话时按Enter键打断它")
    print("检测到静音时将自动停止录音")
    print("===================\n")
    
    # 预先处理一些消息
    await agent_system.process_messages(200)
    
    # 直接启动监听，无需等待用户按下Enter键
    print("自动启动语音监听模式...")
    await agent_system.start_listening()
    await agent_system.process_messages(200)  # 处理开始监听的消息
    
    # 开始监听用户输入
    try:
        # 初始提示
        print("系统已准备好，可以开始说话...(按Enter键停止/打断，按Ctrl+C退出)")
        
        retry_count = 0
        max_retries = 3
        
        while True:
            try:
                # 等待用户按下Enter键打断
                user_input = await asyncio.to_thread(input, "")
                
                # 检查Agent状态并执行相应操作
                if agent_system.state == AgentState.SPEAKING:
                    # 如果Agent正在说话，则打断
                    print("打断AI...")
                    await agent_system.interrupt(reason="manual", smooth=True)
                elif agent_system.state == AgentState.IDLE:
                    # 如果Agent空闲，则重新开始监听
                    print("重新开始监听...")
                    await agent_system.start_listening()
                else:
                    print(f"Agent当前状态: {agent_system.state.name}，请等待...")
                
                # 处理多条消息
                print("[AgentSystem][DEBUG] 开始处理消息（Enter键按下后）...")
                await agent_system.process_messages(20)  # 增加处理消息数量
                await asyncio.sleep(1)  # 等待更长时间，确保所有异步操作完成
                
                # 重置重试计数
                retry_count = 0
            
            except EOFError:
                # 处理EOF错误（通常是用户按下Ctrl+D）
                print("\n检测到EOF，退出对话...")
                break
                
            except Exception as e:
                # 处理其他错误，尝试恢复
                retry_count += 1
                print(f"操作过程中出错 ({retry_count}/{max_retries}): {e}")
                import traceback
                traceback.print_exc()
                
                if retry_count >= max_retries:
                    print(f"错误次数过多，尝试重置系统状态...")
                    # 尝试重置系统状态
                    agent_system.state = AgentState.IDLE
                    await asyncio.sleep(2)  # 给系统一些时间来平稳恢复
                    retry_count = 0
    
    except KeyboardInterrupt:
        print("\n检测到键盘中断，正在结束对话...")
    except Exception as e:
        print(f"运行出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 停止Agent系统
        print("\n正在关闭Agent系统...")
        await agent_system.close()
        print("Agent系统已关闭")


def main():
    """命令行入口点"""
    parser = argparse.ArgumentParser(description="运行基于AutoGen-Core的Agent系统")
    parser.add_argument(
        "--mode", 
        choices=["dynamic", "fixed"], 
        default="dynamic",
        help="录音模式: dynamic(动态)或fixed(固定时长)"
    )
    parser.add_argument(
        "--seconds", 
        type=int, 
        default=5,
        help="固定录音模式的时长(秒)"
    )
    
    args = parser.parse_args()
    
    try:
        # 运行Agent系统
        asyncio.run(run_agent_system(
            recording_mode=args.mode,
            recording_seconds=args.seconds
        ))
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序运行出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
