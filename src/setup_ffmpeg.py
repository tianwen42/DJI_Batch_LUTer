import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

# Windows 下 stdout 被重定向（> log.txt 或管道）时会退化成 GBK，
# 打印 emoji 会直接抛 UnicodeEncodeError，这里显式改成 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 下载源：全部为国内大厂稳定镜像，最后保留一个 GitHub 直连兜底。
#
# 国内源使用 npm 上的 @ffmpeg-installer/win32-x64 包（约 21MB，tgz），
# 实测包含 nvenc / qsv / amf / libx264 / libx265，硬件加速不受影响；
# GitHub 兜底源为 GyanD 的 4.4.1 essentials 完整构建（约 75MB，zip）。
# ---------------------------------------------------------------------------
_NPM_PKG = "@ffmpeg-installer/win32-x64"
_NPM_FILE = "win32-x64-4.1.0.tgz"
FFMPEG_NPM_VERSION = "4.1.0"        # 国内 npm 镜像里的 FFmpeg 版本
FFMPEG_GITHUB_VERSION = "4.4.1"     # GitHub 兜底源的 FFmpeg 版本

FFMPEG_SOURCES = [
    ("腾讯云 npm 镜像",
     f"https://mirrors.cloud.tencent.com/npm/{_NPM_PKG}/-/{_NPM_FILE}", "tgz"),
    ("华为云 npm 镜像",
     f"https://mirrors.huaweicloud.com/repository/npm/{_NPM_PKG}/-/{_NPM_FILE}", "tgz"),
    ("中科大 npm 镜像",
     f"https://npmreg.proxy.ustclug.org/{_NPM_PKG}/-/{_NPM_FILE}", "tgz"),
    ("GitHub 直连",
     f"https://github.com/GyanD/codexffmpeg/releases/download/"
     f"{FFMPEG_GITHUB_VERSION}/ffmpeg-{FFMPEG_GITHUB_VERSION}-essentials_build.zip", "zip"),
]


class DownloadCancelled(Exception):
    """用户取消下载。"""


# ---------------------------------------------------------------------------
# FFmpeg 的落盘位置
#
# 固定安装到:  <运行根目录>/ffmpeg/bin/ffmpeg.exe
# 运行根目录按以下优先级解析 —— 始终跟随用户自己的项目目录，不写死任何绝对路径：
#   1) 显式传入的 base_dir 参数
#   2) 环境变量 DJI_LUTER_HOME
#   3) 打包运行 (PyInstaller) -> EXE 所在目录
#   4) 源码运行            -> 本文件的上两级目录 (即克隆下来的项目根目录)
# ---------------------------------------------------------------------------
def get_base_dir(base_dir=None):
    """解析「运行根目录」。用户把项目克隆到任何位置都能正确适配。"""
    if base_dir:
        return Path(base_dir).expanduser()
    env_home = os.environ.get("DJI_LUTER_HOME")
    if env_home:
        return Path(env_home).expanduser()
    if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
        # 打包后 __file__ 指向临时解包目录，必须用 EXE 自身位置
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_ffmpeg_exe_path(base_dir=None):
    """FFmpeg 的目标安装路径: <运行根目录>/ffmpeg/bin/ffmpeg.exe"""
    return get_base_dir(base_dir) / "ffmpeg" / "bin" / "ffmpeg.exe"


def find_ffmpeg_exe(base_dir=None):
    """返回已安装的 ffmpeg.exe 路径；未安装返回 None。"""
    p = get_ffmpeg_exe_path(base_dir)
    return p if p.exists() else None


def _extract_ffmpeg_exe(archive_path, kind, dest):
    """从 zip / tgz 包里提取 ffmpeg.exe 到 dest。"""
    if kind == "zip":
        with zipfile.ZipFile(archive_path) as z:
            inner = next((n for n in z.namelist() if n.endswith("ffmpeg.exe")), None)
            if not inner:
                raise RuntimeError("压缩包里没有 ffmpeg.exe")
            with z.open(inner) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
    else:  # tgz
        with tarfile.open(archive_path) as t:
            inner = next((n for n in t.getnames() if n.endswith("ffmpeg.exe")), None)
            if not inner:
                raise RuntimeError("压缩包里没有 ffmpeg.exe")
            with t.extractfile(inner) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)


def _download_one(url, dest, progress_cb=None, cancel_flag=None, timeout=30):
    """单源下载。progress_cb(percent, done_mb, total_mb)，total 未知时 percent 为 -1。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel_flag and cancel_flag():
                raise DownloadCancelled()
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress_cb:
                pct = int(done * 100 / total) if total > 0 else -1
                progress_cb(pct, done / 1048576.0, total / 1048576.0)


def download_ffmpeg(base_dir=None, progress_cb=None, log_cb=None, cancel_flag=None):
    """下载 FFmpeg 到 <运行根目录>/ffmpeg/bin/ffmpeg.exe，返回其路径。

    - 安装位置跟随项目目录（见 get_base_dir），不写死绝对路径。
    - 已安装则直接返回（幂等）。
    - 国内镜像依次尝试，全部失败才抛异常。
    - progress_cb(percent, done_mb, total_mb) / log_cb(str) / cancel_flag(): bool
    """
    ffmpeg_exe = get_ffmpeg_exe_path(base_dir)
    bin_dir = ffmpeg_exe.parent
    ffmpeg_dir = bin_dir.parent

    def _log(msg):
        if log_cb:
            log_cb(msg)

    if ffmpeg_exe.exists():
        _log(f"FFmpeg 已存在: {ffmpeg_exe}")
        return ffmpeg_exe

    _log(f"安装目录: {bin_dir}")
    bin_dir.mkdir(parents=True, exist_ok=True)
    archive_path = ffmpeg_dir / "ffmpeg_temp_download"

    last_err = None
    for i, (name, url, kind) in enumerate(FFMPEG_SOURCES, 1):
        try:
            _log(f"开始下载 (源 {i}/{len(FFMPEG_SOURCES)}: {name}) ...")
            _download_one(url, archive_path, progress_cb, cancel_flag)
            _log("下载完成，正在解压 ffmpeg.exe ...")
            _extract_ffmpeg_exe(archive_path, kind, ffmpeg_exe)
            _log(f"FFmpeg 安装完成: {ffmpeg_exe}")
            return ffmpeg_exe
        except DownloadCancelled:
            _log("下载已取消")
            raise
        except Exception as e:
            last_err = e
            _log(f"源「{name}」下载失败: {e}，尝试下一个源 ...")
        finally:
            if archive_path.exists():
                try:
                    os.remove(archive_path)
                except OSError:
                    pass

    raise RuntimeError(f"所有下载源均失败，请检查网络后重试。最后错误: {last_err}")


def setup_ffmpeg():
    """命令行入口 (python src/setup_ffmpeg.py)。"""
    target = get_ffmpeg_exe_path()
    print(f"📁 运行根目录: {get_base_dir()}")
    print(f"🎯 安装目标  : {target}")

    ffmpeg_exe = find_ffmpeg_exe()
    if ffmpeg_exe:
        print(f"✅ FFmpeg 已存在于: {ffmpeg_exe}")
        return ffmpeg_exe

    def progress(pct, done_mb, total_mb):
        if pct >= 0:
            sys.stdout.write(f"\r进度: {pct}% [{done_mb:.1f}MB / {total_mb:.1f}MB]")
        else:
            sys.stdout.write(f"\r已下载: {done_mb:.1f}MB")
        sys.stdout.flush()

    try:
        print("🚀 开始自动下载并配置 FFmpeg (国内镜像加速，最后 GitHub 兜底)...")
        path = download_ffmpeg(progress_cb=progress, log_cb=print)
        print(f"\n✅ FFmpeg 成功安装至: {path}")
        return path
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        print(f"请检查网络连接，或手动下载 FFmpeg 放入: {target.parent}")
        return None


if __name__ == "__main__":
    setup_ffmpeg()
    input("\n按回车退出...")
