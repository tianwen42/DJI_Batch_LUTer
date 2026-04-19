import os
import sys
import zipfile
import urllib.request
from pathlib import Path

def setup_ffmpeg():
    print("🚀 开始自动下载并配置 FFmpeg 基础版...")
    
    # 基础目录配置 (脚本在 src/ 下，项目根目录为 parent)
    base_dir = Path(__file__).parent.parent
    ffmpeg_dir = base_dir / "ffmpeg"
    bin_dir = ffmpeg_dir / "bin"
    zip_path = ffmpeg_dir / "ffmpeg_temp.zip"
    
    # 创建目录
    ffmpeg_dir.mkdir(exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    
    # 检查是否已存在
    ffmpeg_exe = bin_dir / "ffmpeg.exe"
    if ffmpeg_exe.exists():
        print(f"✅ FFmpeg 已存在于: {ffmpeg_exe}")
        return

    # FFmpeg Essentials 下载链接 (由 gyan.dev 提供，较轻量)
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    
    try:
        print(f"正在从 {url} 下载...")
        
        # 定义下载进度回调
        def progress(count, block_size, total_size):
            percent = int(count * block_size * 100 / total_size)
            sys.stdout.write(f"\r进度: {percent}% [{count * block_size / 1024 / 1024:.1f}MB / {total_size / 1024 / 1024:.1f}MB]")
            sys.stdout.flush()

        urllib.request.urlretrieve(url, zip_path, reporthook=progress)
        print("\n\n下载完成，正在解压...")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # 找到内部的 ffmpeg.exe 路径
            exe_internal_path = None
            for name in zip_ref.namelist():
                if name.endswith('bin/ffmpeg.exe'):
                    exe_internal_path = name
                    break
            
            if exe_internal_path:
                # 提取并重命名
                with zip_ref.open(exe_internal_path) as source, open(ffmpeg_exe, 'wb') as target:
                    target.write(source.read())
                print(f"✅ FFmpeg 成功安装至: {ffmpeg_exe}")
            else:
                print("❌ 错误：在压缩包中未找到 ffmpeg.exe")
                
    except Exception as e:
        print(f"\n❌ 发生错误: {str(e)}")
        print("请检查网络连接，或手动下载 FFmpeg 放入 ffmpeg/bin 目录。")
    finally:
        if zip_path.exists():
            os.remove(zip_path)

if __name__ == "__main__":
    setup_ffmpeg()
    input("\n按任意键退出...")
