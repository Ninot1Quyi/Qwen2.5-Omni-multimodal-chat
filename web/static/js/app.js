document.addEventListener('DOMContentLoaded', () => {
    // 获取DOM元素
    const startBtn = document.getElementById('start-btn');
    const pauseBtn = document.getElementById('pause-btn');
    const shareBtn = document.getElementById('share-btn');
    const idleView = document.getElementById('idle-view');
    const activeView = document.getElementById('active-view');
    const audioWaveContainer = document.querySelector('.audio-wave-container');
    const conversationStatus = document.getElementById('conversation-status');
    const connectionStatus = document.getElementById('connection-status');
    const waveBars = document.querySelectorAll('.wave-bar');
    
    // 初始状态
    let isConversationActive = false;
    let currentStatus = 'idle'; // idle, listening, speaking
    let animationFrameId = null;
    
    // 波浪动画控制
    const waveConfig = {
        listening: {
            minHeight: 2,
            maxHeight: 16,
            smoothing: 0.2,
            updateInterval: 70
        },
        speaking: {
            minHeight: 1,
            maxHeight: 12,
            smoothing: 0.3,
            updateInterval: 60
        },
        idle: {
            minHeight: 1,
            maxHeight: 2,
            smoothing: 0.15,
            updateInterval: 200
        }
    };
    
    // 当前波形高度值
    let currentHeights = Array(waveBars.length).fill(2);
    let targetHeights = Array(waveBars.length).fill(2);
    
    // 设置初始状态
    audioWaveContainer.classList.add('idle');
    
    // 更新波形高度
    function updateWaveHeights() {
        let config;
        
        if (currentStatus === 'listening') {
            config = waveConfig.listening;
        } else if (currentStatus === 'speaking') {
            config = waveConfig.speaking;
        } else {
            config = waveConfig.idle;
        }
        
        // 生成新的目标高度
        targetHeights = generateWavePattern(config.minHeight, config.maxHeight);
        
        // 平滑过渡到新高度
        function animateToTargetHeights() {
            let needsUpdate = false;
            
            currentHeights = currentHeights.map((current, index) => {
                const target = targetHeights[index];
                
                if (Math.abs(current - target) < 0.5) {
                    return target;
                }
                
                needsUpdate = true;
                return current + (target - current) * config.smoothing;
            });
            
            // 更新DOM
            waveBars.forEach((bar, index) => {
                bar.style.height = `${currentHeights[index]}px`;
            });
            
            if (needsUpdate) {
                animationFrameId = requestAnimationFrame(animateToTargetHeights);
            } else {
                setTimeout(updateWaveHeights, config.updateInterval);
            }
        }
        
        animateToTargetHeights();
    }
    
    // 生成波浪形模式，创建更自然的波形效果
    function generateWavePattern(minHeight, maxHeight) {
        const numBars = waveBars.length;
        const wavePattern = [];
        
        // 根据不同状态调整波形生成逻辑
        if (currentStatus === 'idle') {
            // 空闲状态：生成非常小的随机波形
            for (let i = 0; i < numBars; i++) {
                wavePattern.push(minHeight + Math.random() * (maxHeight - minHeight) * 0.2);
            }
        } else {
            // 使用正弦波生成基础波形
            const cycles = currentStatus === 'listening' ? 2.5 : 2; // 监听状态波形更密集
            const phase = Math.random() * Math.PI * 2; // 随机相位
            
            for (let i = 0; i < numBars; i++) {
                const x = (i / numBars) * Math.PI * 2 * cycles + phase;
                const sinValue = Math.sin(x);
                
                // 将-1到1的值映射到目标高度范围
                const normalized = (sinValue + 1) / 2; // 0到1
                let height = minHeight + normalized * (maxHeight - minHeight);
                
                // 添加一些随机变化，但保持相对平滑
                const randomFactor = Math.random() * 1.5 - 0.75;
                
                // 监听状态下，随机因素更明显，表现更活跃的波动
                const randomMultiplier = currentStatus === 'listening' ? 2 : 1.5;
                height = Math.max(minHeight, Math.min(maxHeight, height + randomFactor * randomMultiplier));
                
                wavePattern.push(height);
            }
        }
        
        return wavePattern;
    }
    
    // 停止动画
    function stopAnimation() {
        if (animationFrameId) {
            cancelAnimationFrame(animationFrameId);
            animationFrameId = null;
        }
        
        // 重置为默认高度
        waveBars.forEach(bar => {
            bar.style.height = '2px';
        });
        
        currentHeights = Array(waveBars.length).fill(2);
        targetHeights = Array(waveBars.length).fill(2);
    }

    // 更新UI状态
    function updateUIStatus(status) {
        if (currentStatus === status) return;
        
        currentStatus = status;
        
        // 移除所有状态类
        audioWaveContainer.classList.remove('idle', 'listening', 'speaking');
        
        // 添加当前状态类
        audioWaveContainer.classList.add(status);
        
        // 停止当前动画
        stopAnimation();
        
        // 如果是active状态，显示active视图
        if (status !== 'idle') {
            idleView.style.display = 'none';
            activeView.style.display = 'flex';
            updateWaveHeights(); // 开始波形动画
        } else {
            idleView.style.display = 'flex';
            activeView.style.display = 'none';
            
            // 即使在idle状态，当显示在active视图中时也需要非常低的波形
            if (activeView.style.display === 'flex') {
                updateWaveHeights();
            }
        }
    }

    // 开始会话
    function startConversation() {
        isConversationActive = true;
        conversationStatus.textContent = '会话进行中';
        
        // 向Python后端发送开始会话的消息
        pywebview.api.start_conversation().then(result => {
            console.log('会话开始: ', result);
            updateUIStatus('listening');
        }).catch(error => {
            console.error('启动会话失败: ', error);
            endConversation();
        });
    }

    // 结束会话
    function endConversation() {
        isConversationActive = false;
        conversationStatus.textContent = '会话未开始';
        updateUIStatus('idle');
        
        // 向Python后端发送结束会话的消息
        pywebview.api.stop_conversation().catch(error => {
            console.error('结束会话出错: ', error);
        });
    }

    // 注册按钮点击事件
    startBtn.addEventListener('click', startConversation);
    pauseBtn.addEventListener('click', endConversation);
    
    // 分享屏幕按钮 (功能性占位，不实际实现)
    shareBtn.addEventListener('click', () => {
        alert('分享屏幕功能暂未实现');
    });

    // 从Python后端接收状态更新
    window.updateStatus = function(status) {
        updateUIStatus(status);
    };
    
    // 接收音量数据更新（从后端发送）
    window.updateVolumeData = function(volumeData) {
        if (!isConversationActive || currentStatus === 'idle') return;
        
        if (Array.isArray(volumeData) && volumeData.length > 0) {
            // 如果后端提供了音量数据数组，直接使用
            const normalizedData = volumeData.map(vol => {
                // 将音量值映射到高度范围
                const config = currentStatus === 'listening' 
                    ? waveConfig.listening 
                    : waveConfig.speaking;
                return Math.min(config.maxHeight, Math.max(config.minHeight, vol * config.maxHeight));
            });
            
            // 如果数据点不够，通过插值补充
            while (normalizedData.length < waveBars.length) {
                normalizedData.push(normalizedData[normalizedData.length % volumeData.length]);
            }
            
            // 更新目标高度
            targetHeights = normalizedData.slice(0, waveBars.length);
        }
    };
    
    // 初始连接状态检查
    pywebview.api.check_connection().then(result => {
        if (result.success) {
            connectionStatus.textContent = '已连接到后端';
        } else {
            connectionStatus.textContent = '未连接到后端';
            connectionStatus.style.color = 'red';
        }
    }).catch(() => {
        connectionStatus.textContent = '连接后端失败';
        connectionStatus.style.color = 'red';
    });
    
    // 开始初始状态下的低波形动画
    updateWaveHeights();
}); 