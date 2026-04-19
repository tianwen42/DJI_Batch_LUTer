import os
import subprocess
import sys

def build():
    print("🚀 开始打包 DJI Batch LUTer...")
    
    # 检查依赖
    try:
        import PyInstaller
    except ImportError:
        print("❌ 错误: 未安装 pyinstaller。正在尝试为你安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 基础命令
    cmd = [
        "pyinstaller",
        "--noconsole",           # 隐藏控制台
        "--onefile",             # 生成单文件
        "--name=DJI_Batch_LUTer", # 程序名称
        "--clean",               # 清理缓存
    ]

    # 添加数据目录 (Windows 格式: source;dest)
    # 注意: 即使目录为空也要包含，否则代码中 Path.exists() 会失败
    cmd.extend(["--add-data", "config;config"])
    cmd.extend(["--add-data", "bin;bin"])
    cmd.extend(["--add-data", "doc;doc"])

    # 主脚本路径
    cmd.append("src/DJI_Batch_LUTer.py")

    print(f"执行命令: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
        print("\n" + "="*30)
        print("✅ 打包成功！")
        print("最终可执行文件位于: dist/DJI_Batch_LUTer.exe")
        print("="*30)
    except subprocess.CalledProcessError:
        print("\n❌ 打包失败，请检查上方日志。")

if __name__ == "__main__":
    build()
