import os
import subprocess
import sys

from pathlib import Path

def build():
    # 切换到项目根目录执行打包 (脚本在 src/ 下)
    root_dir = Path(__file__).parent.parent
    os.chdir(root_dir)
    
    print(f"🚀 开始打包 DJI Batch LUTer (根目录: {root_dir})...")
    
    # 检查依赖
    try:
        import PyInstaller
    except ImportError:
        print("❌ 错误: 未安装 pyinstaller。正在尝试为你安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 基础命令 (使用 sys.executable -m PyInstaller 确保能找到命令)
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconsole",           # 隐藏控制台
        "--onefile",             # 生成单文件
        "--name=DJI_Batch_LUTer", # 程序名称
        "--icon=src/assets/icon.ico",    # 程序图标
        "--clean",               # 清理缓存
    ]

    # 添加数据目录 (仅当目录存在时添加)
    # 注意: Windows 格式为 source;dest
    # FFmpeg 目录不建议打入 EXE 内部，否则每次运行都要解压，且路径难以管理
    data_dirs = ["config", "doc", "src/assets"]
    for d in data_dirs:
        if os.path.exists(d):
            cmd.extend(["--add-data", f"{d};{d}"])

    # 主脚本路径
    cmd.append("src/DJI_Batch_LUTer.py")

    print(f"执行命令: {' '.join(cmd)}")
    
    try:
        # 使用列表形式调用，不再需要 shell=True
        subprocess.run(cmd, check=True)
        print("\n" + "="*30)
        print("✅ 打包成功！")
        print("最终可执行文件位于: dist/DJI_Batch_LUTer.exe")
        print("="*30)
    except subprocess.CalledProcessError:
        print("\n❌ 打包失败，请检查上方日志。")

if __name__ == "__main__":
    build()
