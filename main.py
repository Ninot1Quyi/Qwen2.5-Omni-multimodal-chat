from voice_chat import QwenVoiceChat

def main():
    try:
        voice_chat = QwenVoiceChat()
        voice_chat.start_conversation()
    except Exception as e:
        print(f"错误: {e}")
    finally:
        voice_chat.close()

if __name__ == "__main__":
    main() 