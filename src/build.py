import os
import subprocess
import sys
import shutil
import time
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

    # 基础命令
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconsole",           # 隐藏控制台
        "--onefile",             # 生成单文件
        "--name=DJI_Batch_LUTer", # 程序名称
        "--icon=src/assets/icon.ico",    # 程序图标
        "--clean",               # 清理缓存
    ]

    # --- 优化体积: 排除不必要的模块 ---
    excludes = [
        "unittest", "pydoc", "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtPdf", "PyQt6.QtMultimedia", "PyQt6.QtQml", "PyQt6.QtQuick",
        "PyQt6.QtNetwork", "PyQt6.QtSql", "PyQt6.QtTest", "PyQt6.QtXml",
        "tkinter", "matplotlib", "numpy", "sqlite3"
    ]
    for ex in excludes:
        cmd.extend(["--exclude-module", ex])

    # 添加数据目录 (仅保留必要的 UI 资源)
    # 注意: config 和 doc 文件夹很大，我们将其放在 EXE 外部，不再打包进 EXE 内部
    data_dirs = ["src/assets"]
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
        
        # --- 自动生成 Release 压缩包 ---
        print("\n📦 正在准备 Release 压缩包...")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        zip_name = f"DJI_Batch_LUTer_{timestamp}"
        release_dir = Path(f"release_{timestamp}")
        
        if release_dir.exists():
            shutil.rmtree(release_dir)
        release_dir.mkdir()
        
        # 复制必要文件
        shutil.copy2("dist/DJI_Batch_LUTer.exe", release_dir)
        shutil.copy2("README.md", release_dir)
        shutil.copy2("config.example.json", release_dir)
        
        # 复制必要目录
        for d in ["config", "doc", "ffmpeg"]:
            if os.path.exists(d):
                shutil.copytree(d, release_dir / d)
        
        # 创建空的 RAW 和 EXPORT 文件夹
        (release_dir / "RAW").mkdir(exist_ok=True)
        (release_dir / "EXPORT").mkdir(exist_ok=True)
        
        # 压缩
        shutil.make_archive(zip_name, 'zip', release_dir)
        
        # 清理临时目录
        shutil.rmtree(release_dir)
        
        print(f"🏆 Release 压缩包已生成: {zip_name}.zip")
        
    except subprocess.CalledProcessError:
        print("\n❌ 打包失败，请检查上方日志。")
    except Exception as e:
        print(f"\n❌ 生成压缩包时出错: {str(e)}")

if __name__ == "__main__":
    build()
