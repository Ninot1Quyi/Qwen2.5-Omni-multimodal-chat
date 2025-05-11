import os
import time
import threading
import base64
from openai import OpenAI
from core_pipeline import ProcessorBase, Frame, FrameType, frames_to_wav_base64
from config import (
    API_KEY, BASE_URL, CHANNELS, AUDIO_FORMAT, RATE, CHUNK, DEBUG
)
import pyaudio

class AIProcessor(ProcessorBase):
    """AI处理器 - 负责调用AI API并处理响应"""
    def __init__(self, name="ai_processor"):
        super().__init__(name)
        
        if not API_KEY:
            raise ValueError("API密钥未设置")
            
        # 初始化OpenAI客户端
        self.client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
        )
        print(f"[AIProcessor] 初始化完成，使用base_url: {BASE_URL}")
        print(f"[AIProcessor] API密钥前8位: {API_KEY[:8]}...")
        
        # 对话历史
        self.messages = []
        self.full_transcript = ""
        
        # 当前响应任务
        self.current_response = None
        self.response_thread = None
        self.response_lock = threading.RLock()
        
        # 状态标志
        self.is_generating = False
        
        # 跟踪API请求
        self.current_request_id = None
        self.completed_request_ids = set()  # 存储已完成或已打断的请求ID
        self.request_id_lock = threading.RLock()
    
    def process_frame(self, frame):
        """处理帧"""
        if frame.type == FrameType.SYSTEM:
            event = frame.data.get("event")
            
            if event == "user_interrupt":
                print("[AIProcessor] 收到用户打断请求")
                # 中断当前响应
                self._interrupt_response()
                
                # 检查是否需要清空管道
                if frame.data.get("command") == "clear_pipeline":
                    print("[AIProcessor] 收到清空管道命令，清空当前处理队列")
                    # 清空输入队列
                    self.input_queue.clear()
                    # 向下游发送清空命令
                    self.send_downstream(Frame(
                        FrameType.SYSTEM,
                        {"command": "clear_pipeline", "event": "user_interrupt"}
                    ))
            
            # 处理语音就绪事件
            elif event == "speech_ready":
                # 获取音频数据
                audio_base64 = frame.data.get("audio_base64")
                if not audio_base64:
                    print("[AIProcessor] 未收到有效的音频数据")
                    return
                
                print(f"[AIProcessor] 收到语音就绪事件，音频数据长度: {len(audio_base64)} 字符")
                
                # 创建用户消息
                user_message = {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:audio/wav;base64,{audio_base64}",
                                "format": "wav",
                            },
                        }
                    ],
                }
                
                # 添加到对话历史
                self.messages.append(user_message)
                print(f"[AIProcessor] 当前对话历史长度: {len(self.messages)}")
                
                # 发送开始响应事件
                self.send_upstream(Frame(
                    FrameType.SYSTEM,
                    {"event": "ai_response_started"}
                ))
                
                print("[AIProcessor] 开始处理AI响应")
                
                # 启动响应线程
                self._start_response_thread()
                
        elif frame.type == FrameType.DATA:
            # 处理DATA类型的帧
            data_type = frame.data.get("type")
            
            # 处理音频数据
            if data_type == "audio_data":
                # 获取音频数据
                audio_base64 = frame.data.get("audio_base64")
                if not audio_base64:
                    print("[AIProcessor] 未收到有效的音频数据")
                    return
                
                print(f"[AIProcessor] 收到语音数据，长度: {len(audio_base64)} 字符")
                
                # 创建用户消息
                user_message = {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:audio/wav;base64,{audio_base64}",
                                "format": "wav",
                            },
                        }
                    ],
                }
                
                # 添加到对话历史
                self.messages.append(user_message)
                print(f"[AIProcessor] 当前对话历史长度: {len(self.messages)}")
                
                # 发送开始响应事件
                self.send_upstream(Frame(
                    FrameType.SYSTEM,
                    {"event": "ai_response_started"}
                ))
                
                print("[AIProcessor] 开始处理AI响应")
                
                # 启动响应线程
                self._start_response_thread()
    
    def _start_response_thread(self):
        """启动响应处理线程"""
        with self.response_lock:
            if self.is_generating:
                print("[AIProcessor] 已有响应正在生成，忽略请求")
                return
                
            self.is_generating = True
            self.response_thread = threading.Thread(target=self._generate_response)
            self.response_thread.daemon = True
            self.response_thread.start()
            print("[AIProcessor] 响应线程已启动")
    
    def _interrupt_response(self):
        """中断当前响应"""
        with self.response_lock:
            self.is_generating = False
            
            # 将当前请求ID添加到完成集合中
            with self.request_id_lock:
                if self.current_request_id:
                    print(f"[AIProcessor] 将请求ID {self.current_request_id} 标记为已打断")
                    self.completed_request_ids.add(self.current_request_id)
            
            # 调用处理器会自动处理后续的清理工作
            self.send_downstream(Frame(
                FrameType.SYSTEM,
                {"command": "stop"}
            ))
            print("[AIProcessor] 已发送停止命令")
    
    def _generate_response(self):
        """生成AI响应的线程函数"""
        try:
            response_data = {
                "ai_text": "",
                "has_audio": False,
                "current_transcript": "",
                "interrupted": False
            }
            
            # 准备保存AI音频，仅在DEBUG模式下
            ai_audio_buffer = bytearray() if DEBUG else None
            
            print("[AIProcessor] 开始创建API请求")
            print(f"[AIProcessor] 请求参数: model=qwen-omni-turbo, modalities=['text', 'audio'], voice=Chelsie")
            
            # 创建API请求
            try:
                completion = self.client.chat.completions.create(
                    model="qwen-omni-turbo",
                    messages=self.messages,
                    modalities=["text", "audio"],
                    audio={"voice": "Chelsie", "format": "wav"},
                    stream=True,
                    stream_options={"include_usage": True},
                )
                print("[AIProcessor] API请求创建成功，开始处理响应流")
                
                # 获取并保存请求ID
                request_id = None
                
            except Exception as e:
                print(f"[AIProcessor] API请求创建失败: {str(e)}")
                raise
            
            # 处理流式响应
            chunk_count = 0
            for chunk in completion:
                chunk_count += 1
                
                # 获取请求ID (通常在第一个chunk中)
                if chunk_count == 1 and hasattr(chunk, "id"):
                    request_id = chunk.id
                    with self.request_id_lock:
                        self.current_request_id = request_id
                        print(f"[AIProcessor] 获取到请求ID: {request_id}")
                
                # 检查请求是否已被标记为完成/打断
                with self.request_id_lock:
                    if request_id and request_id in self.completed_request_ids:
                        print(f"[AIProcessor] 请求ID {request_id} 已被标记为完成/打断，停止处理")
                        response_data["interrupted"] = True
                        break
                
                # 检查是否应该继续处理
                if not self.is_generating or (self.context and self.context.is_cancelled()):
                    response_data["interrupted"] = True
                    # 将当前请求ID添加到完成集合
                    with self.request_id_lock:
                        if request_id:
                            self.completed_request_ids.add(request_id)
                            print(f"[AIProcessor] 请求ID {request_id} 已被标记为中断")
                    print("[AIProcessor] 响应被中断")
                    break
                    
                # 处理内容
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    
                    if hasattr(delta, "content") and delta.content:
                        response_data["ai_text"] += delta.content
                        print(f"[AIProcessor] 收到文本响应 (chunk {chunk_count}): {delta.content}", end="", flush=True)
                    
                    if hasattr(delta, "audio") and delta.audio:
                        response_data["has_audio"] = True
                        print(f"[AIProcessor] 收到音频响应 (chunk {chunk_count})")
                        
                        if "transcript" in delta.audio:
                            transcript = delta.audio["transcript"]
                            if transcript:
                                response_data["current_transcript"] += transcript
                                print(f"[AIProcessor] 收到转写文本: {transcript}")
                        
                        if "data" in delta.audio:
                            # 再次检查请求是否已被标记为完成/打断
                            with self.request_id_lock:
                                if request_id and request_id in self.completed_request_ids:
                                    print(f"[AIProcessor] 请求ID {request_id} 已被标记为完成/打断，停止处理音频")
                                    break
                            
                            # 再次检查是否应该继续处理
                            if not self.is_generating or (self.context and self.context.is_cancelled()):
                                break
                            
                            # 解码音频数据
                            audio_data = delta.audio["data"]
                            print(f"[AIProcessor] 收到音频数据 (chunk {chunk_count}), 长度: {len(audio_data)} 字符")
                            
                            # 收集音频数据用于调试
                            if DEBUG and ai_audio_buffer is not None:
                                try:
                                    audio_bytes = base64.b64decode(audio_data)
                                    ai_audio_buffer.extend(audio_bytes)
                                    print(f"[AIProcessor] 已收集音频数据: {len(ai_audio_buffer)} 字节")
                                except Exception as e:
                                    print(f"[AIProcessor] 收集音频数据时出错: {e}")
                            
                            # 发送音频数据到输出处理器
                            try:
                                self.send_downstream(Frame(
                                    FrameType.SYSTEM,
                                    {"event": "play_audio", "audio_data": audio_data}
                                ))
                                print("[AIProcessor] 音频数据已成功发送到输出处理器")
                            except Exception as e:
                                print(f"[AIProcessor] 发送音频数据到输出处理器失败: {e}")
            
            print(f"[AIProcessor] 共处理了 {chunk_count} 个响应块")
            
            # 将当前请求ID添加到完成集合
            with self.request_id_lock:
                if request_id:
                    self.completed_request_ids.add(request_id)
                    print(f"[AIProcessor] 请求ID {request_id} 已被标记为完成")
            
            # 如果处理完成且未中断，添加到消息历史
            if not response_data["interrupted"]:
                if response_data["current_transcript"]:
                    self.full_transcript += response_data["current_transcript"] + " "
                    assistant_message = {
                        "role": "assistant",
                        "content": [{"type": "text", "text": response_data["current_transcript"]}]
                    }
                    self.messages.append(assistant_message)
                    print(f"[AIProcessor] 添加助手消息到历史: {response_data['current_transcript']}")
                elif response_data["ai_text"]:
                    assistant_message = {
                        "role": "assistant",
                        "content": [{"type": "text", "text": response_data["ai_text"]}]
                    }
                    self.messages.append(assistant_message)
                    print(f"[AIProcessor] 添加助手消息到历史: {response_data['ai_text']}")
                    
            # 通知AI响应结束
            self.send_upstream(Frame(
                FrameType.SYSTEM,
                {"event": "ai_response_ended"}
            ))
            
            print(f"\n[AIProcessor] AI响应生成结束，状态: {'已中断' if response_data['interrupted'] else '完成'}")
            print(f"[AIProcessor] 响应统计: 文本长度={len(response_data['ai_text'])}, 转写长度={len(response_data['current_transcript'])}, 收到音频={response_data['has_audio']}")
            
        except Exception as e:
            print(f"[AIProcessor] 生成响应时出错: {str(e)}")
            import traceback
            print(f"[AIProcessor] 错误详情:\n{traceback.format_exc()}")
            
            # 确保通知AI响应结束
            self.send_upstream(Frame(
                FrameType.SYSTEM,
                {"event": "ai_response_ended", "error": str(e)}
            ))
            
        finally:
            # 重置状态
            with self.response_lock:
                self.is_generating = False
                self.current_request_id = None
                self.response_thread = None
                print("[AIProcessor] 响应线程已结束，状态已重置")
            
            # 定期清理已完成请求ID集合，防止无限增长
            with self.request_id_lock:
                if len(self.completed_request_ids) > 100:  # 设置一个合理的阈值
                    print(f"[AIProcessor] 清理已完成请求ID集合，当前大小: {len(self.completed_request_ids)}")
                    # 只保留最近的50个
                    self.completed_request_ids = set(list(self.completed_request_ids)[-50:])

class EventProcessor(ProcessorBase):
    """事件处理器 - 负责处理系统事件并更新状态"""
    def __init__(self, name="event_processor", on_state_change=None):
        super().__init__(name)
        self.current_state = "idle"
        self.on_state_change = on_state_change
    
    def process_frame(self, frame):
        """处理事件帧"""
        if frame.type == FrameType.SYSTEM:
            event = frame.data.get("event")
            
            if event == "speech_started":
                self._update_state("user_speaking")
                
            elif event == "speech_ended":
                self._update_state("listening")
                
            elif event == "ai_response_started":
                self._update_state("speaking")
                
            elif event == "ai_response_ended":
                self._update_state("listening")
                
            elif event == "user_interrupt":
                self._update_state("interrupted")
                time.sleep(0.05)  # 短暂延迟以确保UI能显示中断状态
                self._update_state("user_speaking")
                
            elif event == "ai_response_interrupted":
                self._update_state("interrupted")
                time.sleep(0.1)  # 短暂延迟以确保UI能显示中断状态
                self._update_state("listening")
    
    def _update_state(self, new_state):
        """更新状态并通知监听器"""
        if new_state != self.current_state:
            print(f"[EventProcessor] 状态变化: {self.current_state} -> {new_state}")
            self.current_state = new_state
            
            # 通知外部回调
            if self.on_state_change:
                try:
                    self.on_state_change(new_state)
                except Exception as e:
                    print(f"[EventProcessor] 状态变化回调出错: {e}") 