import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP_NAME = "DJI_Batch_LUTer"
# 最终产物目录：dist/ 直接就是完整项目
#   dist/DJI_Batch_LUTer.exe   <- 双击即可运行
#   dist/_internal/            <- 运行时依赖（目录模式）
#   dist/config/  dist/doc/    <- 运行时资源
DIST_DIR = Path("dist")


def _exe_locked(path):
    """检测目标 EXE 是否正在运行（Windows 下运行中的 EXE 无法被覆盖）。"""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "ab"):
            pass
        return False
    except OSError:
        return True


def _deploy_to_dist(staging_root, onedir):
    """把 PyInstaller 产物内容平铺到 dist/，使 dist 直接就是完整项目。

    PyInstaller 目录模式固定会生成 distpath/<name>/ 这一层，
    这里先打到临时目录，再把内容搬进 dist/，从而去掉多余的一层。

    **用户数据保护**：RAW / EXPORT 是素材与导出目录，永不覆盖 ——
    替换前先把它们从旧 dist 原样搬回，保证里面用户的视频不丢。

    返回旧 dist 的备份目录（供最后统一清理）；不做删除，
    以免某些环境的删除保护中断后续步骤。
    若 RAW/EXPORT 未能恢复，则返回 None（拒绝删除备份，保住用户素材）。
    """
    stamped = time.strftime("%Y%m%d_%H%M%S")

    # 1) 旧 dist 让位（改名，不删除；同盘改名不受删除保护影响）
    backup = None
    if DIST_DIR.exists():
        candidate = Path(f"_dist_old_{stamped}")
        try:
            DIST_DIR.rename(candidate)
            backup = candidate
            print(f"📦 旧 dist 已让位 -> {candidate}/")
        except OSError as e:
            print(f"⚠️ 旧 dist 改名失败({e})，改为逐项覆盖。")
            backup = None

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 2) 平铺产物内容（只含程序自身文件，不碰用户数据目录）
    if onedir:
        staged_app = staging_root / APP_NAME          # 目录: exe + _internal
        items = list(staged_app.iterdir())
    else:
        items = [staging_root / f"{APP_NAME}.exe"]

    # 旧 dist 已整体让位时 dist 是空的，可直接 move（最快）；
    # 否则就地覆盖，且全程不做删除（避免触发删除保护导致中断）。
    use_move = backup is not None
    for item in items:
        target = DIST_DIR / item.name
        if use_move:
            shutil.move(str(item), str(target))
        elif item.is_dir():
            shutil.copytree(str(item), str(target), dirs_exist_ok=True)
        else:
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                pass
            shutil.copy2(str(item), str(target))

    # 2.5) 清理历史遗留的旧结构 dist/<APP_NAME>/（若存在）
    legacy = DIST_DIR / APP_NAME
    if legacy.is_dir():
        try:
            shutil.rmtree(legacy)
            print(f"🧹 已移除旧结构 {legacy}/")
        except OSError as e:
            print(f"⚠️ 旧结构 {legacy}/ 无法自动删除：{e}")

    # 3) 用户数据永不覆盖：优先从旧 dist 原样搬回
    #    RAW/EXPORT 是素材与导出目录；dji_luter_config.json 是用户设置
    safe_to_cleanup = True
    for name in ("RAW", "EXPORT", "dji_luter_config.json"):
        target = DIST_DIR / name
        if target.exists():
            continue                                   # 已存在（兜底分支）→ 保持不动

        kept = (backup / name) if backup else None
        if kept is not None and kept.exists():
            try:
                shutil.move(str(kept), str(target))    # 同盘改名，瞬时完成，不复制素材
                print(f"♻️ 保留原有 {name}（用户数据未被覆盖）")
                continue
            except OSError as e:
                safe_to_cleanup = False
                print(f"❌ 无法恢复 {name}：{e}")
                print(f"   ⚠️ 为避免丢失用户数据，旧目录 {backup}/ 将【保留不删】，请手动处理。")

        if name in ("RAW", "EXPORT"):
            target.mkdir(exist_ok=True)

    return backup if safe_to_cleanup else None


def _cleanup(*paths):
    """删除过渡产物（改名后的旧 dist、临时打包目录）。

    放在整个流程的最后执行：这些只是中间产物，
    即便被外部删除保护拦截，也绝不影响 dist/ 与发布包。
    """
    for p in paths:
        if not p:
            continue
        p = Path(p)
        if not p.exists():
            continue
        try:
            shutil.rmtree(p)
            print(f"🧹 已清理 {p}/")
        except OSError as e:
            print(f"⚠️ 无法自动删除 {p}/（可能被系统删除保护拦截）：{e}")
            print("   它只是过渡产物，可手动删除，不影响本次产物。")


def _sync_runtime_assets(target_dir):
    """把 config/ doc/ 同步到 dist/（EXE 以自身所在目录为运行根）。"""
    for d in ["config", "doc"]:
        src_d = Path(d)
        dst_d = Path(target_dir) / d
        if not src_d.exists():
            print(f"⚠️ 未找到 {d}/，跳过同步。")
            continue
        print(f"📋 同步 {d}/ -> {dst_d}/ ...")
        try:
            if dst_d.exists():
                shutil.rmtree(dst_d)
            shutil.copytree(src_d, dst_d)
        except OSError as e:
            print(f"⚠️ 同步 {d}/ 失败(可能被占用): {e}")
            print("   请关闭正在运行的程序后重新打包。")


def _make_release(onedir, out_exe, runtime_dir):
    """生成 Release 压缩包（解压后是 DJI_Batch_LUTer/ 文件夹，内含 EXE）。

    注意：dist/ 本身已是完整项目，压缩包内再套一层同名文件夹，
    是为了解压时不会把文件散落到用户当前目录。
    """
    print("\n📦 正在准备 Release 压缩包...")
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    zip_name = f"DJI_Batch_LUTer_{timestamp}"
    release_dir = Path(f"release_{timestamp}")

    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir()

    app_dir = release_dir / APP_NAME
    if onedir:
        shutil.copytree(runtime_dir, app_dir)
    else:
        app_dir.mkdir()
        shutil.copy2(out_exe, app_dir)
        for d in ["config", "doc"]:
            if (Path(runtime_dir) / d).exists():
                shutil.copytree(Path(runtime_dir) / d, app_dir / d)

    shutil.copy2("README.md", app_dir)
    if os.path.exists("config.example.json"):
        shutil.copy2("config.example.json", app_dir)
    else:
        print("⚠️ 未找到 config.example.json，发布包将不含配置模板。")
        print("   在旧版仓库中该文件曾被 .gitignore 的 *.json 规则误伤，请 git pull 后再打包。")

    # 创建空的 RAW 和 EXPORT 文件夹
    (app_dir / "RAW").mkdir(exist_ok=True)
    (app_dir / "EXPORT").mkdir(exist_ok=True)

    shutil.make_archive(zip_name, "zip", release_dir)
    shutil.rmtree(release_dir)

    print(f"🏆 Release 压缩包已生成: {zip_name}.zip")
    print("ℹ️ 发布包不含 FFmpeg，用户首次使用时点界面上的「下载 FFmpeg」即可（国内镜像，约 20MB）。")


def build(mode="onedir"):
    """mode: 'onedir'(默认, 启动快) | 'onefile'(单文件, 分发方便)"""
    root_dir = Path(__file__).parent.parent
    os.chdir(root_dir)

    onedir = (mode != "onefile")
    out_exe = DIST_DIR / f"{APP_NAME}.exe"        # 两种模式的产物路径一致

    # PyInstaller 固定输出到 distpath/<name>/，这里打到带时间戳的临时目录，
    # 既避免覆盖旧产物，也避免触发目录删除保护。
    stamp = time.strftime("%Y%m%d_%H%M%S")
    staging = Path(f"_build_dist_{stamp}")

    print("=" * 50)
    print(f"🚀 开始打包 DJI Batch LUTer ({'目录模式 onedir' if onedir else '单文件模式 onefile'})")
    print(f"   根目录: {root_dir}")
    print(f"   产物  : {out_exe}     (dist/ 直接就是完整项目)")
    print("=" * 50)

    # 检查依赖
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("❌ 错误: 未安装 pyinstaller。正在尝试为你安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 检查目标 EXE 是否正在运行 (运行中会被占用，打包必然失败)
    if _exe_locked(out_exe):
        print(f"❌ 打包失败: {out_exe} 正在运行，文件被占用、无法覆盖。")
        print("   👉 请先关闭已经打开的程序窗口，然后再重新打包。")
        return

    # 基础命令
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconsole",                      # 隐藏控制台
        f"--name={APP_NAME}",               # 程序名称
        "--icon=src/assets/icon.ico",       # 程序图标
        "--clean",                          # 清理缓存
        "--noconfirm",                      # 输出目录已存在时直接覆盖
        "--noupx",                          # 不使用 UPX（压缩后极易被杀软误报）
        f"--distpath={staging}",            # 先打到临时目录，稍后平铺进 dist/
    ]
    if not onedir:
        # 单文件模式：把所有依赖塞进一个 exe，代价是每次启动都要解压到 %TEMP% (启动慢)
        cmd.append("--onefile")

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
        subprocess.run(cmd, check=True)

        # --- 把临时产物平铺到 dist/ ---
        backup = _deploy_to_dist(staging, onedir)

        print("\n" + "=" * 30)
        print("✅ 打包成功！")
        print(f"产物目录: {DIST_DIR.resolve()}")
        print(f"可执行文件: {out_exe}")
        print("=" * 30)

        # --- 同步运行时资源到 dist/ ---
        # EXE 运行时以自身所在目录为根查找 config/，
        # 不同步的话直接运行 dist 下的 EXE 时，设备/滤镜下拉会是空的。
        _sync_runtime_assets(DIST_DIR)

        # --- 自动生成 Release 压缩包 ---
        _make_release(onedir, out_exe, DIST_DIR)

        # --- 最后清理过渡产物（放最后，避免删除保护中断前面的步骤）---
        _cleanup(backup, staging)

    except subprocess.CalledProcessError:
        print("\n❌ 打包失败，请检查上方日志。")
    except Exception as e:
        print(f"\n❌ 生成产物时出错: {str(e)}")


if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]]
    if "--onefile" in args or "-1" in args:
        build("onefile")
    else:
        build("onedir")
