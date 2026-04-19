import os
import subprocess
from pathlib import Path

# ================= 配置区域 =================
# 输入视频文件夹 (包含 Action 4 的 D-Log M 素材)
INPUT_DIR = Path(r"C:\Users\YANG\Desktop\DJI\RAW")

# 输出视频文件夹
OUTPUT_DIR = Path(r"C:\Users\YANG\Desktop\DJI\EXPORT")

# 大疆官方 LUT 文件路径
LUT_FILE = Path(r"C:\Users\YANG\Desktop\DJI\DJI OSMO Action 4 D-Log M to Rec.709 V1.cube")

# FFMPEG 路径 (如果已添加到环境变量，可保持 "ffmpeg")
FFMPEG_PATH = r"C:\Program Files\EVCapture\ffmpeg.exe"
# ============================================

def batch_process():
    # 1. 检查 LUT 文件是否存在
    if not LUT_FILE.exists():
        print(f"错误: 找不到 LUT 文件: {LUT_FILE}")
        return

    # 2. 创建输出目录
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True)
        print(f"已创建输出目录: {OUTPUT_DIR}")

    # 3. 获取所有视频文件 (.MP4, .MOV) - 使用 set 避免 Windows 下大小写重复匹配
    extensions = ["*.MP4", "*.mp4", "*.MOV", "*.mov"]
    video_files_set = set()
    for ext in extensions:
        video_files_set.update(INPUT_DIR.glob(ext))
    
    video_files = sorted(list(video_files_set))
    
    if not video_files:
        print(f"未在 {INPUT_DIR} 中找到视频文件。")
        return

    print(f"找到 {len(video_files)} 个视频文件，准备开始批量应用 LUT 并导出...")

    # 处理 ffmpeg 路径中的反斜杠 (ffmpeg 的 lut3d 滤镜需要正斜杠和对冒号的转义)
    lut_path_ffmpeg = str(LUT_FILE.absolute()).replace("\\", "/").replace(":", "\\:")

    for i, video in enumerate(video_files, 1):
        output_file = OUTPUT_DIR / f"{video.stem}_Rec709.mp4"
        
        print(f"[{i}/{len(video_files)}] 正在处理: {video.name}")
        
        # 构建 ffmpeg 命令
        # -vf "lut3d='path/to/lut.cube'" 应用 3D LUT
        # -c:v libx264 使用 H.264 编码
        # -preset fast 编码速度预设
        # -crf 18 恒定质量因子 (18-23 是高质量，越小质量越高)
        # -c:a copy 复制原始音频流
        cmd = [
            FFMPEG_PATH,
            "-i", str(video.absolute()),
            "-vf", f"lut3d='{lut_path_ffmpeg}'",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "copy",
            str(output_file.absolute()),
            "-y"
        ]
        
        try:
            # 运行命令
            # subprocess.run 在命令完成后返回
            process = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
            
            if process.returncode == 0:
                print(f"   ✅ 成功导出: {output_file.name}")
            else:
                print(f"   ❌ 处理失败: {video.name}")
                print(f"   报错信息: {process.stderr}")
                
        except FileNotFoundError:
            print("\n错误: 未找到 ffmpeg。")
            print("请从 https://ffmpeg.org/ 下载并安装，或将 ffmpeg.exe 放在此脚本同目录下。")
            return
        except Exception as e:
            print(f"   ❌ 发生意外错误: {e}")

    print("\n所有任务已完成！")
    print(f"导出文件位于: {OUTPUT_DIR}")

if __name__ == "__main__":
    batch_process()
