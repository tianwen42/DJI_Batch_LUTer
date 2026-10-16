import sys
import os
import subprocess
import json
import threading
import time
import shutil
import re
import fnmatch
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLineEdit, QLabel, QFileDialog, QTextEdit,
                             QProgressBar, QMessageBox, QSpinBox, QComboBox, QGroupBox,
                             QProgressDialog)
from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot, QDateTime, QTimer
from PyQt6.QtGui import QIcon, QPixmap

# FFmpeg 一键下载（国内镜像，见 setup_ffmpeg.py）
from setup_ffmpeg import find_ffmpeg_exe, download_ffmpeg, get_ffmpeg_exe_path, DownloadCancelled

# 路径处理逻辑：兼容脚本运行与 PyInstaller 打包
def get_base_path():
    """获取程序运行的基础目录 (EXE 所在目录或脚本所在目录)"""
    if hasattr(sys, '_MEIPASS'):
        # 打包后的 EXE 运行环境，sys.executable 是 EXE 路径
        return Path(sys.executable).parent
    return Path(__file__).parent.parent

def get_resource_path(relative_path):
    """获取资源文件路径 (兼容打包后的临时目录)"""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).parent.parent / relative_path

def _asset_roots():
    """可能存放资源文件的根目录，按优先级排序（去重）。"""
    roots = []
    if hasattr(sys, '_MEIPASS'):
        # onedir -> <exe目录>\_internal ；onefile -> %TEMP%\_MEIxxxx
        roots.append(Path(sys._MEIPASS))
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        roots += [exe_dir / "_internal", exe_dir, exe_dir.parent]
    roots.append(Path(__file__).parent.parent)   # 源码运行: 项目根目录
    seen, uniq = set(), []
    for r in roots:
        r = Path(r)
        if str(r) not in seen:
            seen.add(str(r))
            uniq.append(r)
    return uniq

def find_asset(relative_path):
    """在多个候选根目录中查找资源文件，返回第一个存在的路径。

    兼容三种布局：
      源码运行        -> <项目根>/src/assets/...
      onedir (目录模式) -> <exe目录>/_internal/src/assets/...
      onefile (单文件)  -> <%TEMP%/_MEIxxxx>/src/assets/...
    """
    roots = _asset_roots()
    for root in roots:
        p = root / relative_path
        if p.exists():
            return p
    return roots[0] / relative_path

def ffmpeg_spawn_kwargs():
    """启动 ffmpeg 子进程时的通用参数（Windows 关键）。

    本程序用 --noconsole 打包后属于 GUI 进程，自身没有控制台。直接拉起 ffmpeg
    这类控制台程序时，Windows 需要临时创建 conhost 控制台会话，这一步在部分机器
    上会失败并报 0x800700e8（“管道正在被关闭”），表现为程序启动时弹错误框。

    统一加 CREATE_NO_WINDOW（不新建控制台）+ STARTF_USESHOWWINDOW（不弹窗），
    并把 stdin 指向 DEVNULL，让子进程完全不碰控制台与标准输入。
    """
    kw = {"stdin": subprocess.DEVNULL}
    if os.name == 'nt':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kw

# 基础目录 (用于存放配置文件、默认导出目录等)
BASE_DIR = get_base_path()
# 资源目录 (用于读取内置的 LUT 滤镜)
RESOURCE_DIR = get_resource_path("")

# 配置文件路径 (始终放在 EXE/脚本同级目录)
CONFIG_FILE = BASE_DIR / "dji_luter_config.json"
# 默认配置目录 (包含所有 LUT，优先使用外部目录)
DEFAULT_CONFIG_DIR = BASE_DIR / "config"
# 如果外部目录不存在，尝试使用内置资源目录 (兼容旧版或特殊打包)
if not DEFAULT_CONFIG_DIR.exists():
    DEFAULT_CONFIG_DIR = RESOURCE_DIR / "config"
# 默认素材目录
DEFAULT_INPUT_DIR = BASE_DIR / "RAW"
# 默认导出目录
DEFAULT_OUTPUT_DIR = BASE_DIR / "EXPORT"
# 本地 FFmpeg 路径 (优先检查资源目录或基础目录下的 bin)
LOCAL_FFMPEG_PATH = RESOURCE_DIR / "bin" / "ffmpeg.exe"
# 用户自定义 FFmpeg 目录 (项目根目录下的 ffmpeg/bin/ffmpeg.exe)
# 注意：在打包环境下，ffmpeg 目录是外部放置的，应该相对于 BASE_DIR (EXE 所在目录)
# 与「下载 FFmpeg」按钮的目标路径共用同一处解析 (setup_ffmpeg.get_ffmpeg_exe_path)
USER_FFMPEG_PATH = get_ffmpeg_exe_path(BASE_DIR)
# Logo 路径 (多布局兜底查找)
LOGO_PATH = find_asset("src/assets/logo_DJI Batch LUTer.jpg")
# Icon 路径 (窗口图标；打包图标由 build.py 的 --icon 指定)
ICON_PATH = find_asset("src/assets/icon.ico")
# 编码器标识
CPU_ENCODER = "CPU (libx264)"
# 窗口显示后延迟多少毫秒再开始 FFmpeg 探测
# （探测会启动多个 ffmpeg 子进程，放在窗口显示后执行，避免拖慢启动）
FFMPEG_PROBE_DELAY_MS = 80

# 画质档位 -> (GPU 固定码率, CPU preset, CPU CRF)
QUALITY_PRESETS = {
    "原画质": ("150M", "slow", "14"),
    "高质量": ("80M", "medium", "16"),
    "极速": ("15M", "ultrafast", "24"),
}
DEFAULT_QUALITY_PRESET = ("40M", "medium", "20")


def get_quality_preset(quality_mode):
    """按画质档位取 (GPU 码率, CPU preset, CPU CRF)，未匹配则按标准档处理。"""
    for key, preset in QUALITY_PRESETS.items():
        if key in quality_mode:
            return preset
    return DEFAULT_QUALITY_PRESET
# ---------------- 滤镜效果提示 ----------------
# 说明只用于界面提示，不会修改滤镜名称本身。
# 想改成自己的话术，编辑 config/lut_descriptions.json（见同目录下的文件说明）。
DESCRIPTION_FILE = DEFAULT_CONFIG_DIR / "lut_descriptions.json"

LUT_TYPE_HINTS = {
    "Normalization": "色彩还原滤镜：把 D-Log / D-Log M 灰片还原成标准 Rec.709 色彩，是后续调色的基础",
    "Color Grading": "风格化调色滤镜：在画面上叠加官方风格，直接得到成品观感",
    "通用 (General)": "该设备目录下的官方滤镜（未按还原 / 调色分组）",
}

# 文件名关键词 -> 效果提示（按顺序匹配，先命中先用）
LUT_STYLE_HINTS = (
    ("forest", "森林风格：浓郁自然、偏青绿，适合山林植被等户外场景"),
    ("ice", "冰蓝风格：冷调清透，适合雪景、水面与冷色场景"),
    ("nature", "自然风格：通透清新，接近肉眼观感"),
    ("spring", "春季风格：清透明亮、偏嫩绿，适合花草与新绿"),
    ("summer", "夏季风格：明亮高饱和，适合阳光、海滩等热烈场景"),
    ("autumn", "秋季风格：暖调金黄，适合落叶、暖阳场景"),
    ("winter", "冬季风格：冷调低饱和，适合雪景与清冷氛围"),
)

# 大疆 Action 5 Pro 官方「梅兰竹菊」系列
LUT_CJK_STYLE_HINTS = {"ju": "菊", "lan": "兰", "mei": "梅", "zhu": "竹"}


def _load_custom_descriptions():
    """读取 config/lut_descriptions.json（按修改时间缓存，方便边改边看）。"""
    try:
        mtime = DESCRIPTION_FILE.stat().st_mtime
    except OSError:
        return {}
    cached = _load_custom_descriptions.cache
    if cached and cached[0] == mtime:
        return cached[1]
    table = {}
    try:
        with open(DESCRIPTION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            table = {k: str(v) for k, v in data.items() if not str(k).startswith("_")}
    except Exception:
        table = {}
    _load_custom_descriptions.cache = (mtime, table)
    return table


_load_custom_descriptions.cache = None


def _lookup_custom_description(candidates):
    table = _load_custom_descriptions()
    if not table:
        return None
    for key in candidates:
        if key in table:
            return table[key]
    for pattern, text in table.items():
        if any(ch in pattern for ch in "*?[") and any(fnmatch.fnmatch(c, pattern) for c in candidates):
            return text
    return None


def _derive_lut_description(name, ltype=""):
    """按文件名 / 类型推断效果提示（规则兜底，滤镜名不会被改写）。"""
    low = name.lower()

    # 还原类：识别 "D-Log M to Rec.709" 这类方向
    if re.search(r"d-?\s?log\s?m?\s*(?:to|->|=>|→)\s*rec\.?709", low):
        source = "D-Log M" if re.search(r"d-?log\s*m", low) else "D-Log"
        if "vivid" in low:
            return (f"{source} → Rec.709 鲜艳版：在标准还原的基础上提高饱和度与对比度，"
                    "画面更通透讨喜")
        return f"{source} → Rec.709 标准还原，色彩中性，适合作为后续调色的起点"

    for keyword, text in LUT_STYLE_HINTS:
        if keyword in low:
            return text

    cjk = re.search(r"\b(ju|lan|mei|zhu)\b", low)
    if cjk:
        return (f"大疆官方「梅兰竹菊」系列调色滤镜（{LUT_CJK_STYLE_HINTS[cjk.group(1)]}）："
                "偏中式氛围感，建议先拿小段素材试套再批量导出")

    if ltype in LUT_TYPE_HINTS:
        return LUT_TYPE_HINTS[ltype]
    return "未收录说明的滤镜，可在 config/lut_descriptions.json 中补充它的效果描述"


def describe_lut(lut_path, device="", ltype=""):
    """返回滤镜的效果提示（用于界面显示，不改动滤镜名称）。"""
    if not lut_path:
        return ""
    name = os.path.basename(str(lut_path))
    stem = os.path.splitext(name)[0]
    candidates = []
    for key in (name, stem):
        if device and ltype:
            candidates.append(f"{device}/{ltype}/{key}")
        if device:
            candidates.append(f"{device}/{key}")
        candidates.append(key)
    return _lookup_custom_description(candidates) or _derive_lut_description(name, ltype)

def get_timestamp():
    return QDateTime.currentDateTime().toString("HH:mm:ss")

# 信号类，用于线程间通信
class WorkerSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int)  # 携带 run_id，便于丢弃已取消任务的回调


class JobRegistry:
    """登记正在运行的 FFmpeg 进程，使「停止」能真正终止任务。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._procs = set()
        self._cancelled = False

    def reset(self):
        """开始新一轮任务前清空状态。"""
        with self._lock:
            self._procs.clear()
            self._cancelled = False

    @property
    def cancelled(self):
        with self._lock:
            return self._cancelled

    def cancel(self):
        """标记取消，并终止所有正在运行的 FFmpeg 进程。"""
        with self._lock:
            self._cancelled = True
            procs = list(self._procs)
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass

    def run(self, cmd):
        """执行 ffmpeg 并等待结束，返回 (returncode, stderr, cancelled)。

        进程登记在案，因此 cancel() 可以随时终止它。
        """
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore',
            **ffmpeg_spawn_kwargs(),
        )
        with self._lock:
            cancelled = self._cancelled
            if not cancelled:
                self._procs.add(proc)
        if cancelled:
            # 用户已经点了停止，不必再跑
            try:
                proc.terminate()
            except Exception:
                pass

        _, stderr = proc.communicate()
        with self._lock:
            self._procs.discard(proc)
            cancelled = cancelled or self._cancelled
        if cancelled:
            return None, stderr or "", True
        return proc.returncode, stderr or "", False
# 单个视频处理任务
class ExportWorker(QRunnable):
    def __init__(self, video_path, output_dir, lut_path, ffmpeg_path, encoder_type, quality_mode,
                 registry, run_id):
        super().__init__()
        self.video_path = Path(video_path)
        self.output_dir = Path(output_dir)
        self.lut_path = lut_path
        self.ffmpeg_path = ffmpeg_path
        self.encoder_type = encoder_type
        self.quality_mode = quality_mode
        self.registry = registry
        self.run_id = run_id
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            self._encode()
        except Exception as e:
            self.signals.log.emit(f"<span style='color: #dc3545;'>   ❌ 意外错误: {str(e)}</span>")
        finally:
            # 成功 / 失败 / 被取消都要上报一次，便于任务计数收敛
            self.signals.progress.emit(self.run_id)

    def _encode(self):
        if self.registry.cancelled:
            return

        output_file = self._make_output_path()
        self.signals.log.emit(
            f"[{get_timestamp()}] <b style='color: #0078d4;'>[处理中]</b> {self.video_path.name}")

        last_error = ""
        for index, (encoder, audio_mode) in enumerate(self._attempt_plan()):
            returncode, stderr, cancelled = self.registry.run(
                self._build_cmd(encoder, audio_mode, output_file))
            if cancelled:
                self.signals.log.emit(
                    f"<span style='color: #ffc107;'>   ⏹️ 已取消: {self.video_path.name}</span>")
                return
            if returncode == 0:
                self.signals.log.emit(
                    f"<span style='color: #28a745;'>   ✅ 成功导出: {output_file.name}</span>")
                if index > 0:
                    self.signals.log.emit(
                        f"<small style='color: #666;'>      实际使用: {encoder} / 音轨 {audio_mode}</small>")
                return

            last_error = stderr
            if index == 0:
                self.signals.log.emit(
                    "<span style='color: #ffc107;'>   ⚠️ 本次尝试失败，正在自动降级重试 (CPU / AAC)...</span>")

        self.signals.log.emit(f"<span style='color: #dc3545;'>   ❌ 失败: {self.video_path.name}</span>")
        self.signals.log.emit(f"<small style='color: #666;'>      原因: {self._trim_error(last_error)}</small>")

    def _attempt_plan(self):
        """返回依次尝试的 (编码器, 音轨模式) 列表，实现自动降级。

        硬件编码失败时一律回退 CPU，不再靠 stderr 关键字判断 —— 常见的
        "Cannot load nvcuda.dll"、"Unknown encoder 'h264_nvenc'" 都不含编码器关键字。
        部分素材音轨无法直接封装进 MP4（如 MOV 里的 PCM），最后再用 AAC 重编码兜底。
        """
        plan = []
        if self.encoder_type != CPU_ENCODER:
            plan.append((self.encoder_type, "copy"))
        plan.append((CPU_ENCODER, "copy"))
        plan.append((CPU_ENCODER, "aac"))
        return plan

    def _build_cmd(self, encoder, audio_mode, output_file):
        cmd = [self.ffmpeg_path, "-i", str(self.video_path.absolute())]

        # FFmpeg 滤镜里的 Windows 路径转义：
        # 盘符冒号必须转义为 \: 且只能用单引号包裹。用双引号时滤镜图解析器会先剥掉
        # 引号，再把 "D:" 的冒号当成选项分隔符，导致 LUT 永远加载失败 (No such file)。
        lut_arg = str(Path(self.lut_path).absolute()).replace("\\", "/").replace(":", "\\:")
        lut_arg = lut_arg.replace("'", "\\'")
        # 先套 LUT（FFmpeg 会自动升到 rgb48 做插值）再落到 8-bit 4:2:0，
        # 避免在已经抽样的色度上做色彩映射
        cmd += ["-vf", f"lut3d='{lut_arg}',format=yuv420p"]

        gpu_bitrate, cpu_preset, cpu_crf = get_quality_preset(self.quality_mode)

        if encoder == "NVIDIA (h264_nvenc)":
            cmd += ["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", gpu_bitrate]  # p4 为平衡预设
        elif encoder == "Intel (h264_qsv)":
            cmd += ["-c:v", "h264_qsv", "-preset", "balanced", "-b:v", gpu_bitrate]
        elif encoder == "AMD (h264_amf)":
            cmd += ["-c:v", "h264_amf", "-b:v", gpu_bitrate]
        else:  # CPU
            cmd += ["-c:v", "libx264", "-preset", cpu_preset, "-crf", cpu_crf]

        if audio_mode == "aac":
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c:a", "copy"]

        cmd += [str(output_file.absolute()), "-y"]
        return cmd

    def _make_output_path(self):
        """生成不会覆盖已有文件的输出路径（同名时追加递增序号）。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = self.output_dir / f"{self.video_path.stem}_{stamp}_Rec709"
        candidate = base.with_suffix(".mp4")
        index = 1
        while candidate.exists():
            candidate = self.output_dir / f"{base.name}_{index}.mp4"
            index += 1
        return candidate

    @staticmethod
    def _trim_error(stderr):
        """只保留报错尾部，避免把整段 FFmpeg 日志刷进界面。"""
        text = (stderr or "").strip()
        if not text:
            return "未知错误"
        tail = "\n".join([line for line in text.splitlines() if line.strip()][-8:])
        return tail[-800:]
# FFmpeg 一键下载任务（后台线程 + 进度/取消回调）
class FFmpegDownloadWorker(QRunnable):
    class _Signals(QObject):
        progress = pyqtSignal(int, float, float)   # percent(未知为-1), done_mb, total_mb
        log = pyqtSignal(str)
        done = pyqtSignal(str)
        fail = pyqtSignal(str)

    def __init__(self, base_dir, cancel_flag):
        super().__init__()
        self.base_dir = base_dir
        self.cancel_flag = cancel_flag
        self.signals = self._Signals()

    @pyqtSlot()
    def run(self):
        try:
            path = download_ffmpeg(
                base_dir=self.base_dir,
                progress_cb=lambda p, d, t: self.signals.progress.emit(p, d, t),
                log_cb=lambda msg: self.signals.log.emit(msg),
                cancel_flag=self.cancel_flag,
            )
            self.signals.done.emit(str(path))
        except DownloadCancelled:
            self.signals.fail.emit("__cancelled__")
        except Exception as e:
            self.signals.fail.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DJI Batch LUTer")
        self.setMinimumWidth(850)
        self.setMinimumHeight(750)
        
        self.threadpool = QThreadPool()
        self.cpu_count = os.cpu_count() or 2

        # 日志批量处理
        self._log_buffer = []
        self._log_timer = QTimer()
        self._log_timer.timeout.connect(self._flush_log_buffer)
        self._log_timer.setInterval(200)  # 每 200ms 刷新一次

        # 确保默认素材和导出目录存在 (防止在克隆后文件夹缺失)
        DEFAULT_INPUT_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # LUT 数据结构: {设备名: {类型: [文件列表]}}
        self.lut_data = {}
        self.scan_luts()

        # 这两个状态必须在 load_config() 之前初始化：
        # load_config 会依据配置文件把它们改写，若之后又赋默认值会把读到的值冲掉。
        self._encoder_from_config = False  # 用户是否显式保存过编码器偏好
        self._encoder_cache = {}           # 编码器探测结果缓存 {fingerprint, encoder}

        self.init_ui()
        self.load_config()

        # 如果配置文件不存在，立即保存一份默认配置
        if not CONFIG_FILE.exists():
            self.save_config()

        # FFmpeg 探测会依次启动 ffmpeg 子进程（-version / -encoders / 硬件试编码，
        # 在本机实测合计约 2.5s），若放在这里会全部发生在窗口显示之前。
        # 改为窗口显示后再跑，让界面秒开。
        QTimer.singleShot(FFMPEG_PROBE_DELAY_MS, self._deferred_ffmpeg_setup)
        
        self.total_tasks = 0
        self.completed_tasks = 0
        self._progress_lock = threading.Lock()
        self._is_running = False  # 任务运行标志，用于停止控制

        self._run_id = 0           # 每轮任务自增，用于丢弃已取消任务的进度回调
        self.jobs = JobRegistry()  # 正在运行的 FFmpeg 进程登记表

    def scan_luts(self):
        """扫描 config 目录并按设备系列和类型建立映射"""
        if not DEFAULT_CONFIG_DIR.exists():
            return

        self.lut_data = {}
        
        # 1. 扫描子目录 (如 config/Action 4)
        for device_dir in DEFAULT_CONFIG_DIR.iterdir():
            if device_dir.is_dir():
                device_name = device_dir.name
                self.lut_data[device_name] = {}
                
                # 遍历类型目录 (如 Normalization, Color Grading)
                for type_dir in device_dir.iterdir():
                    if type_dir.is_dir():
                        type_name = type_dir.name
                        luts = list(type_dir.glob("*.cube"))
                        if luts:
                            self.lut_data[device_name][type_name] = sorted(luts)
                
                # 如果该设备下直接有 cube 文件，存入 "通用 (General)"
                direct_luts = list(device_dir.glob("*.cube"))
                if direct_luts:
                    self.lut_data[device_name]["通用 (General)"] = sorted(direct_luts)
                
                # 如果该设备下最终没有任何 LUT，删除该设备项
                if not self.lut_data[device_name]:
                    del self.lut_data[device_name]
        
        # 2. 扫描根目录下的 cube 文件 (归类为 "其他/未分类")
        root_luts = list(DEFAULT_CONFIG_DIR.glob("*.cube"))
        if root_luts:
            others_name = "其他设备 (Others)"
            if others_name not in self.lut_data:
                self.lut_data[others_name] = {}
            self.lut_data[others_name]["通用 (General)"] = sorted(root_luts)

    def init_ui(self):
        # 设置窗口图标
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        elif LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # 0. Logo 显示 (保持高清晰度)
        if LOGO_PATH.exists():
            logo_label = QLabel()
            pixmap = QPixmap(str(LOGO_PATH))
            
            # 针对 High DPI 屏幕优化清晰度
            # 增加高度到 120，并确保使用高质量缩放
            target_height = 120
            scaled_pixmap = pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
            
            # 设置设备像素比，防止在高分屏下模糊
            if hasattr(scaled_pixmap, 'setDevicePixelRatio'):
                # 尝试获取系统的缩放倍率 (简单处理，通常为 1.0, 1.5, 2.0 等)
                dpr = self.devicePixelRatioF()
                if dpr > 1.0:
                    # 如果是高分屏，我们需要一个更大尺寸的图片然后缩小显示
                    high_res_pixmap = pixmap.scaledToHeight(int(target_height * dpr), Qt.TransformationMode.SmoothTransformation)
                    high_res_pixmap.setDevicePixelRatio(dpr)
                    logo_label.setPixmap(high_res_pixmap)
                else:
                    logo_label.setPixmap(scaled_pixmap)
            else:
                logo_label.setPixmap(scaled_pixmap)
                
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # 适当增加边距
            logo_label.setContentsMargins(0, 10, 0, 10)
            layout.addWidget(logo_label)

        # 1. 目录配置
        dir_group = QGroupBox("目录配置")
        dir_layout = QVBoxLayout()
        
        # 导入目录
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit(str(DEFAULT_INPUT_DIR))
        self.input_edit.setToolTip("待处理的视频所在目录，支持 MP4/MOV 格式")
        input_btn = QPushButton("选择素材目录")
        input_btn.setToolTip("点击选择包含待处理视频的目录")
        input_btn.clicked.connect(lambda: self.select_dir(self.input_edit))
        input_layout.addWidget(QLabel("素材目录:"))
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(input_btn)
        dir_layout.addLayout(input_layout)

        # 导出目录
        output_layout = QHBoxLayout()
        self.output_edit = QLineEdit(str(DEFAULT_OUTPUT_DIR))
        self.output_edit.setToolTip("转换后的视频输出目录")
        output_btn = QPushButton("选择导出目录")
        output_btn.setToolTip("点击选择转换后的视频保存目录")
        output_btn.clicked.connect(lambda: self.select_dir(self.output_edit))
        output_layout.addWidget(QLabel("导出目录:"))
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(output_btn)
        dir_layout.addLayout(output_layout)
        
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        # 2. 滤镜选择 (全系列支持)
        lut_group = QGroupBox("滤镜选择 (DJI 全系列支持)")
        lut_v_layout = QVBoxLayout()

        # 设备与类型选择
        selector_layout = QHBoxLayout()

        self.device_combo = QComboBox()
        self.device_combo.setToolTip("选择你的大疆设备型号，不同设备使用不同的 LUT 文件")
        self.device_combo.addItems(sorted(self.lut_data.keys()))
        self.device_combo.currentTextChanged.connect(self.on_device_changed)
        
        self.lut_type_combo = QComboBox()
        self.lut_type_combo.setToolTip("Normalization=色彩还原（Log转Rec.709），Color Grading=风格化调色")
        self.lut_type_combo.currentTextChanged.connect(self.on_lut_type_changed)
        self.lut_type_combo.view().setMouseTracking(True)
        
        self.lut_file_combo = QComboBox()
        self.lut_file_combo.setToolTip("选择具体的 LUT 滤镜文件，鼠标悬停在下拉项上可查看效果提示")
        self.lut_file_combo.currentTextChanged.connect(self.on_lut_file_combo_changed)
        # 展开下拉时悬停显示每一项的效果提示
        self.lut_file_combo.view().setMouseTracking(True)
        
        selector_layout.addWidget(QLabel("设备:"))
        selector_layout.addWidget(self.device_combo)
        selector_layout.addSpacing(10)
        selector_layout.addWidget(QLabel("类型:"))
        selector_layout.addWidget(self.lut_type_combo)
        selector_layout.addSpacing(10)
        selector_layout.addWidget(QLabel("滤镜列表:"))
        selector_layout.addWidget(self.lut_file_combo, 1)
        
        lut_v_layout.addLayout(selector_layout)

        # 滤镜效果提示（与滤镜名称分离，名称保持原样，说明单独显示）
        self.lut_desc_label = QLabel()
        self.lut_desc_label.setWordWrap(True)
        self.lut_desc_label.setTextFormat(Qt.TextFormat.RichText)
        self.lut_desc_label.setStyleSheet("color: #444444; font-size: 10pt; padding: 2px 2px 6px 2px;")
        self.lut_desc_label.setToolTip("提示文案可以在 config/lut_descriptions.json 中自定义")
        lut_v_layout.addWidget(self.lut_desc_label)

        # 手动选择/显示路径
        path_layout = QHBoxLayout()
        self.lut_path_edit = QLineEdit()
        self.lut_path_edit.setPlaceholderText("当前选中的 LUT 路径...")
        self.lut_path_edit.setToolTip("当前选中的 LUT 文件完整路径")
        self.lut_path_edit.textChanged.connect(lambda _: self.update_lut_description())
        lut_browse_btn = QPushButton("手动选择 LUT...")
        lut_browse_btn.setToolTip("手动选择任意 .cube 格式的 LUT 文件")
        lut_browse_btn.clicked.connect(self.select_lut_manually)
        
        path_layout.addWidget(QLabel("LUT 路径:"))
        path_layout.addWidget(self.lut_path_edit)
        path_layout.addWidget(lut_browse_btn)
        lut_v_layout.addLayout(path_layout)
        
        lut_group.setLayout(lut_v_layout)
        layout.addWidget(lut_group)

        # 3. 性能设置
        perf_group = QGroupBox("性能与编码设置")
        perf_layout = QHBoxLayout()
        
        self.encoder_combo = QComboBox()
        self.encoder_combo.setToolTip("NVIDIA/Intel/AMD 使用显卡加速，CPU 使用纯CPU解码\n自动检测可用编码器，失败时会自动回退到CPU模式")
        self.encoder_combo.addItems([
            "NVIDIA (h264_nvenc)",
            "Intel (h264_qsv)",
            "AMD (h264_amf)",
            "CPU (libx264)"
        ])
        perf_layout.addWidget(QLabel("编码器:"))
        perf_layout.addWidget(self.encoder_combo)
        
        perf_layout.addSpacing(20)
        
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, self.cpu_count)
        self.concurrency_spin.setValue(2)
        self.concurrency_spin.setToolTip(f"同时处理的任务数量，建议：\n• 显卡加速时 3-7\n• CPU 模式可设为 {self.cpu_count}（充分利用多核）")
        perf_layout.addWidget(QLabel("并行任务数:"))
        perf_layout.addWidget(self.concurrency_spin)
        
        perf_layout.addSpacing(20)

        # 新增画质选择
        self.quality_combo = QComboBox()
        self.quality_combo.setToolTip("原画质：150M码率/CRF14，视觉无损\n高质量：80M码率/CRF16，适合分享\n标准：40M码率/CRF20，平衡大小与画质\n极速：15M码率/CRF24，最小体积")
        self.quality_combo.addItems([
            "原画质 (Original Quality)",
            "高质量 (High Quality)",
            "标准 (Standard)",
            "极速 (Fastest)"
        ])
        self.quality_combo.setCurrentIndex(0) # 默认原画质
        perf_layout.addWidget(QLabel("画质:"))
        perf_layout.addWidget(self.quality_combo)
        
        perf_layout.addSpacing(20)
        
        # 设置 FFmpeg 默认显示路径 (优先项目自定义目录，其次内置 bin)
        default_ffmpeg = "ffmpeg"
        if USER_FFMPEG_PATH.exists():
            default_ffmpeg = str(USER_FFMPEG_PATH)
        elif LOCAL_FFMPEG_PATH.exists():
            default_ffmpeg = str(LOCAL_FFMPEG_PATH)
            
        self.ffmpeg_edit = QLineEdit(default_ffmpeg)
        self.ffmpeg_edit.setToolTip("FFmpeg 可执行文件路径\n程序会自动检测 ffmpeg/bin/ 目录下的内置版本")
        ffmpeg_browse_btn = QPushButton("选择 FFmpeg...")
        ffmpeg_browse_btn.setToolTip("手动选择 FFmpeg 可执行文件")
        ffmpeg_browse_btn.clicked.connect(self.select_ffmpeg_manually)
        perf_layout.addWidget(QLabel("FFmpeg 路径:"))
        perf_layout.addWidget(self.ffmpeg_edit)
        perf_layout.addWidget(ffmpeg_browse_btn)

        self.ffmpeg_dl_btn = QPushButton("下载 FFmpeg")
        self.ffmpeg_dl_btn.setToolTip(
            "本地没有 FFmpeg 时，通过国内镜像一键下载并自动配置\n"
            "（已安装则提示，不会重复下载）")
        self.ffmpeg_dl_btn.clicked.connect(self.on_download_ffmpeg)
        perf_layout.addWidget(self.ffmpeg_dl_btn)
        
        perf_group.setLayout(perf_layout)
        layout.addWidget(perf_group)

        # 4. 日志显示
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setPlaceholderText("运行日志...")
        self.log_display.textChanged.connect(lambda: self.log_display.ensureCursorVisible())
        layout.addWidget(self.log_display)

        # 5. 进度条
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # 6. 按钮行
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("🚀 开始导出")
        self.start_btn.setFixedHeight(50)
        self.start_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; font-size: 14px; border-radius: 5px;")
        self.start_btn.clicked.connect(self.start_export)
        
        self.stop_btn = QPushButton("🛑 停止")
        self.stop_btn.setFixedHeight(50)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; font-size: 14px; border-radius: 5px;")
        self.stop_btn.clicked.connect(self.stop_tasks)

        self.open_folder_btn = QPushButton("📁 打开输出目录")
        self.open_folder_btn.setFixedHeight(50)
        self.open_folder_btn.clicked.connect(self.open_output_folder)

        btn_layout.addWidget(self.start_btn, 2)
        btn_layout.addWidget(self.stop_btn, 1)
        btn_layout.addWidget(self.open_folder_btn, 1)
        layout.addLayout(btn_layout)

        # 7. 底部信息与仓库链接
        footer_layout = QHBoxLayout()
        info_label = QLabel(
            "<span style='color: #666; font-size: 10pt;'>"
            "<b>DJI Batch LUTer</b> - 大疆全系列视频批量色彩还原工具<br>"
            "支持 D-Log / D-Log M 还原与官方风格化调色滤镜"
            "</span>"
        )
        
        repo_url = "https://github.com/tianwen42/DJI_Batch_LUTer"
        repo_label = QLabel(f'<a href="{repo_url}" style="color: #0078d4; text-decoration: none; font-size: 10pt; font-weight: bold;">📦 开源主页 & 提交反馈</a>')
        repo_label.setOpenExternalLinks(True)
        repo_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        footer_layout.addWidget(info_label)
        footer_layout.addStretch()
        footer_layout.addWidget(repo_label)
        layout.addSpacing(10)
        layout.addLayout(footer_layout)

        # 初始化下拉框内容 (默认选中 Action 4 的还原配置)
        if self.device_combo.count() > 0:
            # 优先尝试选中 Action 4
            index = self.device_combo.findText("Action 4")
            if index >= 0:
                self.device_combo.setCurrentIndex(index)
            
            self.on_device_changed(self.device_combo.currentText())
            
            # 优先尝试选中 Normalization
            index = self.lut_type_combo.findText("Normalization")
            if index >= 0:
                self.lut_type_combo.setCurrentIndex(index)
                self.on_lut_type_changed(self.lut_type_combo.currentText())

    def on_device_changed(self, device):
        self.lut_type_combo.clear()
        if device in self.lut_data:
            self.lut_type_combo.addItems(sorted(self.lut_data[device].keys()))
            # 类型下拉同样给出悬停说明，帮助区分「还原」与「风格化调色」
            for i in range(self.lut_type_combo.count()):
                hint = LUT_TYPE_HINTS.get(self.lut_type_combo.itemText(i))
                if hint:
                    self.lut_type_combo.setItemData(i, hint, Qt.ItemDataRole.ToolTipRole)
        self.update_lut_files()

    def on_lut_type_changed(self, ltype):
        self.update_lut_files()

    def update_lut_files(self):
        device = self.device_combo.currentText()
        ltype = self.lut_type_combo.currentText()

        self.lut_file_combo.clear()
        if device in self.lut_data and ltype in self.lut_data[device]:
            files = self.lut_data[device][ltype]
            for f in files:
                self.lut_file_combo.addItem(f.name, str(f.absolute()))
            # 给下拉列表里的每一项挂上「效果提示」，
            # 鼠标悬停到某个滤镜上即可看到说明（滤镜名称保持原样，不改写）
            self._apply_lut_item_tooltips(device, ltype)
        self.update_lut_description()

    def _apply_lut_item_tooltips(self, device, ltype):
        """为滤镜下拉列表的每一项设置悬停提示（内容来自 lut_descriptions.json）。"""
        for i in range(self.lut_file_combo.count()):
            path = self.lut_file_combo.itemData(i)
            if not path:
                continue
            desc = describe_lut(path, device, ltype)
            tip = f"{Path(path).name}\n\n💡 效果提示：{desc}"
            self.lut_file_combo.setItemData(i, tip, Qt.ItemDataRole.ToolTipRole)

    def on_lut_file_combo_changed(self, index):
        path = self.lut_file_combo.currentData()
        if path:
            self.lut_path_edit.setText(path)
        self.update_lut_description()

    def update_lut_description(self):
        """把当前滤镜的效果提示显示在名称下方（不修改滤镜名称）。"""
        path = self.lut_path_edit.text().strip()
        device = self.device_combo.currentText()
        ltype = self.lut_type_combo.currentText()
        if not path:
            self.lut_desc_label.setText(
                "<b style='color: #0078d4;'>💡 效果提示：</b>"
                "<span style='color: #888888;'>请先选择滤镜</span>")
            self.lut_file_combo.setToolTip("选择具体的 LUT 滤镜文件")
            return

        desc = describe_lut(path, device, ltype)
        self.lut_desc_label.setText(f"<b style='color: #0078d4;'>💡 效果提示：</b>{desc}")
        self.lut_file_combo.setToolTip(f"{os.path.basename(path)}\n\n{desc}")
        self.lut_path_edit.setToolTip(f"{path}\n\n{desc}")
    def select_lut_manually(self):
        start_dir = str(DEFAULT_CONFIG_DIR) if DEFAULT_CONFIG_DIR.exists() else str(BASE_DIR)
        file_path, _ = QFileDialog.getOpenFileName(self, "手动选择 LUT 文件", start_dir, "LUT Files (*.cube)")
        if file_path:
            self.lut_path_edit.setText(file_path)
            self.save_config()

    # ---------------- FFmpeg 一键下载 ----------------
    def on_download_ffmpeg(self):
        """已有 FFmpeg 则提示；否则通过国内镜像一键下载并自动配置。"""
        current = self.ffmpeg_edit.text().strip()
        if current and self.is_ffmpeg_valid(current):
            QMessageBox.information(
                self, "FFmpeg 已就绪",
                f"当前 FFmpeg 可正常使用，无需重复下载：\n{current}")
            return
        installed = find_ffmpeg_exe(BASE_DIR)
        if installed:
            self.ffmpeg_edit.setText(str(installed))
            self.detect_available_encoders(str(installed), respect_user_choice=False)
            self.save_config()
            QMessageBox.information(
                self, "FFmpeg 已下载",
                f"检测到已下载的 FFmpeg，已自动填入路径：\n{installed}")
            return

        ret = QMessageBox.question(
            self, "下载 FFmpeg",
            "未检测到可用的 FFmpeg。\n\n"
            "将通过国内镜像（腾讯云 / 华为云 / 中科大，GitHub 兜底）下载 FFmpeg"
            "（约 20MB，含 NVIDIA/Intel/AMD 硬件加速编码器），\n"
            f"安装到：{get_ffmpeg_exe_path(BASE_DIR)}\n\n是否开始下载？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if ret != QMessageBox.StandardButton.Yes:
            return

        self._ffmpeg_cancel = threading.Event()
        self._ffmpeg_dlg = QProgressDialog("正在准备下载...", "取消", 0, 100, self)
        self._ffmpeg_dlg.setWindowTitle("下载 FFmpeg")
        self._ffmpeg_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._ffmpeg_dlg.setMinimumDuration(0)
        self._ffmpeg_dlg.setAutoClose(False)
        self._ffmpeg_dlg.setAutoReset(False)
        self._ffmpeg_dlg.canceled.connect(self._ffmpeg_cancel.set)
        self._ffmpeg_dlg.show()

        self.ffmpeg_dl_btn.setEnabled(False)
        self.log_display.append(
            f"[{get_timestamp()}] ⬇️ 开始下载 FFmpeg（国内镜像：腾讯云 → 华为云 → 中科大 → GitHub）...")

        worker = FFmpegDownloadWorker(BASE_DIR, self._ffmpeg_cancel.is_set)
        worker.signals.progress.connect(self._on_ffmpeg_download_progress)
        worker.signals.log.connect(self._on_ffmpeg_download_log)
        worker.signals.done.connect(self._on_ffmpeg_download_done)
        worker.signals.fail.connect(self._on_ffmpeg_download_fail)
        QThreadPool.globalInstance().start(worker)

    def _on_ffmpeg_download_log(self, msg):
        self.log_display.append(f"[{get_timestamp()}] {msg}")

    def _on_ffmpeg_download_progress(self, percent, done_mb, total_mb):
        dlg = getattr(self, "_ffmpeg_dlg", None)
        if dlg is None:
            return
        if percent >= 0:
            dlg.setMaximum(100)
            dlg.setValue(percent)
            dlg.setLabelText(
                f"正在下载 FFmpeg...  {percent}%  ({done_mb:.1f} / {total_mb:.1f} MB)")
        else:
            dlg.setMaximum(0)   # 总大小未知 -> 忙碌指示
            dlg.setLabelText(f"正在下载 FFmpeg...  已下载 {done_mb:.1f} MB")

    def _on_ffmpeg_download_done(self, path):
        self._close_ffmpeg_dialog()
        self.ffmpeg_dl_btn.setEnabled(True)
        self.ffmpeg_edit.setText(path)
        self.detect_available_encoders(path, respect_user_choice=False)
        self.save_config()
        self.log_display.append(f"[{get_timestamp()}] ✅ FFmpeg 下载完成: {path}")
        QMessageBox.information(self, "下载完成",
                                f"FFmpeg 下载完成并已自动配置：\n{path}")

    def _on_ffmpeg_download_fail(self, msg):
        self._close_ffmpeg_dialog()
        self.ffmpeg_dl_btn.setEnabled(True)
        if msg == "__cancelled__":
            self.log_display.append(f"[{get_timestamp()}] ⏹️ 已取消 FFmpeg 下载")
            return
        self.log_display.append(f"[{get_timestamp()}] ❌ FFmpeg 下载失败: {msg}")
        QMessageBox.warning(
            self, "下载失败",
            f"FFmpeg 下载失败：\n{msg}\n\n"
            "可稍后重试；也可以手动下载后用「选择 FFmpeg...」指定路径。")

    def _close_ffmpeg_dialog(self):
        dlg = getattr(self, "_ffmpeg_dlg", None)
        if dlg is not None:
            dlg.close()
            self._ffmpeg_dlg = None

    def select_ffmpeg_manually(self):
        start_dir = str(BASE_DIR)
        file_path, _ = QFileDialog.getOpenFileName(self, "手动选择 FFmpeg", start_dir, "FFmpeg (ffmpeg.exe);;All Files (*)")
        if file_path:
            self.ffmpeg_edit.setText(file_path)
            self.save_config()
            self.detect_available_encoders(file_path, respect_user_choice=False)

    def select_dir(self, line_edit):
        start_dir = line_edit.text() if line_edit.text() else str(BASE_DIR)
        dir_path = QFileDialog.getExistingDirectory(self, "选择目录", start_dir)
        if dir_path:
            line_edit.setText(dir_path)
            self.save_config()

    def open_output_folder(self):
        output_dir = self.output_edit.text()
        if os.path.exists(output_dir):
            os.startfile(output_dir)
        else:
            QMessageBox.warning(self, "提示", "输出目录不存在。")

    def is_ffmpeg_valid(self, path):
        """检查 FFmpeg 是否可用（支持绝对路径或 PATH 中的命令名，带超时）"""
        if not path:
            return False
        exe = path
        if not os.path.exists(path):
            # 不是文件路径，就当作命令名去 PATH 里找
            exe = shutil.which(path)
            if not exe:
                return False
        try:
            res = subprocess.run([exe, "-version"], capture_output=True, text=True,
                                 timeout=5, **ffmpeg_spawn_kwargs())
            return res.returncode == 0
        except Exception:
            return False
    def _deferred_ffmpeg_setup(self):
        """窗口显示后再做 FFmpeg 探测。

        这里会依次启动 ffmpeg 子进程（-version / -encoders / 硬件试编码），
        全部是同步阻塞调用，所以必须放在窗口显示之后，否则界面要等它跑完才出现。
        探测过程一律捕获异常，避免任何意外以弹窗形式打断用户。
        """
        if self.windowIcon().isNull():
            self.log_display.append(
                "<span style='color: #ffc107;'>⚠️ 未加载到窗口图标（不影响使用）</span>")
        try:
            if self.auto_find_ffmpeg():
                return
        except Exception as e:
            self.log_display.append(
                f"<span style='color: #ffc107;'>⚠️ FFmpeg 初始化异常: {e}</span>")
        QMessageBox.warning(self, "FFmpeg 缺失",
            "未检测到可用的 FFmpeg！\n\n"
            "1. 点界面上的「下载 FFmpeg」按钮一键下载（国内镜像）。\n"
            "2. 或手动将 ffmpeg.exe 放入 ffmpeg/bin 目录下。\n"
            "3. 或在设置中手动指定 FFmpeg 路径。")

    def _ffmpeg_search_list(self):
        """项目内部的 ffmpeg 候选路径（按优先级）。系统 PATH 永远排在最后。"""
        cands = [("程序目录", USER_FFMPEG_PATH)]
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
            # 目录模式产物在 dist/DJI_Batch_LUTer/ 下，也认项目根的 ffmpeg/bin
            cands.append(("项目根目录", exe_dir.parent / "ffmpeg" / "bin" / "ffmpeg.exe"))
            cands.append(("程序内置", LOCAL_FFMPEG_PATH))
        else:
            cands.append(("项目根目录", Path(__file__).parent.parent / "ffmpeg" / "bin" / "ffmpeg.exe"))
        return cands

    def auto_find_ffmpeg(self):
        """自动定位可用的 FFmpeg 并检测硬件编码器。找到返回 True。

        查找顺序：项目内部（程序目录 → 项目根目录 → 程序内置）
                  → 配置里记录的路径（用户手动指定过的）
                  → 系统 PATH（最后兜底）
        """
        # 1. 项目内部（优先）
        for label, path in self._ffmpeg_search_list():
            if path.exists() and self.is_ffmpeg_valid(str(path)):
                self.ffmpeg_edit.setText(str(path))
                self.log_display.append(f"✅ 使用项目内的 FFmpeg（{label}）: {path}")
                self.detect_available_encoders(str(path))
                return True

        # 2. 从配置文件恢复
        current_path = self.ffmpeg_edit.text().strip()
        if current_path and current_path != "ffmpeg" and self.is_ffmpeg_valid(current_path):
            self.log_display.append(f"🔍 使用配置记录的 FFmpeg: {current_path}")
            self.detect_available_encoders(current_path)
            return True

        # 3. 系统 PATH 中的 ffmpeg（兜底）
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg and self.is_ffmpeg_valid(system_ffmpeg):
            self.ffmpeg_edit.setText(system_ffmpeg)
            self.log_display.append(f"🔍 使用系统 PATH 中的 FFmpeg: {system_ffmpeg}")
            self.detect_available_encoders(system_ffmpeg)
            return True

        self.log_display.append("<span style='color: #dc3545;'>❌ 未找到可用的 FFmpeg，请点「下载 FFmpeg」或手动指定路径。</span>")
        return False
    # 候选硬件编码器：(下拉框文本, FFmpeg 编码器名, -encoders 里的关键字)
    ENCODER_CANDIDATES = (
        ("NVIDIA (h264_nvenc)", "h264_nvenc", "nvenc"),
        ("Intel (h264_qsv)", "h264_qsv", "qsv"),
        ("AMD (h264_amf)", "h264_amf", "amf"),
    )

    def detect_available_encoders(self, ffmpeg_path, respect_user_choice=True):
        """检测本机真正可用的硬件编码器并选中第一个。

        只看 -encoders 只能说明该 FFmpeg 编译时启用了对应编码器，不代表本机
        硬件/驱动可用，因此这里会实际试编码一次。

        探测结果（含编码器名 + FFmpeg 指纹）会缓存进配置文件：同一份 FFmpeg
        下次启动直接命中缓存、跳过 1~4 秒的试编码；FFmpeg 换了就自动失效重测。
        """
        if respect_user_choice and getattr(self, "_encoder_from_config", False):
            return

        # 0. 先查缓存：同一份 FFmpeg 已测过就直接用，省去全部子进程开销
        cached = self._load_encoder_cache(ffmpeg_path)
        if cached:
            self.encoder_combo.setCurrentText(cached)
            self.log_display.append(f"⚡ 使用缓存的编码器检测结果: {cached}")
            return

        try:
            res = subprocess.run([ffmpeg_path, "-loglevel", "quiet", "-encoders"],
                                 capture_output=True, text=True, timeout=8,
                                 **ffmpeg_spawn_kwargs())
            listed = res.stdout or ""
        except Exception as e:
            self.log_display.append(
                f"<span style='color: #ffc107;'>⚠️ 无法执行 FFmpeg 编码器检测: {e}</span>")
            return

        for label, encoder, keyword in self.ENCODER_CANDIDATES:
            if keyword not in listed:
                continue  # 这个 FFmpeg 构建根本没编进去
            if self._probe_encoder(ffmpeg_path, encoder):
                self.encoder_combo.setCurrentText(label)
                self.log_display.append(f"🔍 检测到可用硬件编码器: {label}")
                self._store_encoder_cache(ffmpeg_path, label)
                return
        self.log_display.append("ℹ️ 未检测到可用硬件编码器，使用 CPU 编码。")
        self._store_encoder_cache(ffmpeg_path, CPU_ENCODER)

    @staticmethod
    def _ffmpeg_fingerprint(ffmpeg_path):
        """FFmpeg 指纹（绝对路径 + 大小 + 修改时间）。任一项变化即视为不同版本。"""
        try:
            p = Path(ffmpeg_path).resolve()
            st = p.stat()
            return f"{p}|{st.st_size}|{int(st.st_mtime)}"
        except OSError:
            return None

    def _load_encoder_cache(self, ffmpeg_path):
        """命中缓存则返回编码器名（字符串），否则 None。"""
        cache = getattr(self, "_encoder_cache", None)
        if not cache:
            return None
        fp = self._ffmpeg_fingerprint(ffmpeg_path)
        if not fp or cache.get("fingerprint") != fp:
            return None
        label = cache.get("encoder")
        # 编码器名必须仍是下拉框里的合法选项，避免旧配置残留脏值
        if label and self.encoder_combo.findText(label) >= 0:
            return label
        return None

    def _store_encoder_cache(self, ffmpeg_path, label):
        """记录探测结果并落盘（失败时静默，不影响主流程）。"""
        fp = self._ffmpeg_fingerprint(ffmpeg_path)
        if not fp:
            return
        self._encoder_cache = {"fingerprint": fp, "encoder": label}
        try:
            self.save_config()
        except Exception:
            pass

    @staticmethod
    def _probe_encoder(ffmpeg_path, encoder):
        """真实试编码一小段画面，确认编码器在本机可用。

        注意探测尺寸别太小：NVENC 有最小帧尺寸限制，用 64x64 会被误判为不可用。
        """
        try:
            res = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.2", "-frames:v", "1",
                 "-c:v", encoder, "-f", "null", "-"],
                capture_output=True, text=True, timeout=20, **ffmpeg_spawn_kwargs())
            return res.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _resolve_saved_dir(saved):
        """把配置里保存的目录解析成可用的绝对路径；不可用则返回 None。

        - 相对路径按 BASE_DIR（EXE / 脚本所在目录）解析，
          避免从其它工作目录启动时被解析到错误位置。
        - 目录不存在时返回 None，由调用方回落到默认目录。
        """
        if not saved:
            return None
        p = Path(saved)
        if not p.is_absolute():
            p = BASE_DIR / p
        try:
            if p.is_dir():
                return str(p)
        except OSError:
            pass
        return None

    def load_config(self):
        if not CONFIG_FILE.exists():
            return
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 记录用户是否显式保存过编码器偏好（保存过就不被自动检测覆盖）
            self._encoder_from_config = bool(config.get("encoder"))

            # 恢复编码器探测缓存（避免每次启动都重新试编码）
            self._encoder_cache = config.get("encoder_cache") or {}

            # 检查路径是否存在，不存在则使用默认值
            # 相对路径统一按程序所在目录(BASE_DIR)解析，避免从别的工作目录启动时指错
            input_dir = self._resolve_saved_dir(config.get("input_dir"))
            self.input_edit.setText(input_dir if input_dir else str(DEFAULT_INPUT_DIR))

            output_dir = self._resolve_saved_dir(config.get("output_dir"))
            self.output_edit.setText(output_dir if output_dir else str(DEFAULT_OUTPUT_DIR))

            # 恢复设备和类型选择
            device = config.get("device")
            if device:
                self.device_combo.setCurrentText(device)
            ltype = config.get("lut_type")
            if ltype:
                self.lut_type_combo.setCurrentText(ltype)

            # 恢复 LUT 路径 (检查是否存在)
            lut_path = config.get("lut_path")
            if lut_path and os.path.exists(lut_path):
                self.lut_path_edit.setText(lut_path)
                # 如果在下拉框里，也选中它
                index = self.lut_file_combo.findData(lut_path)
                if index >= 0:
                    self.lut_file_combo.setCurrentIndex(index)

            if config.get("encoder"):
                self.encoder_combo.setCurrentText(config.get("encoder"))

            if config.get("quality"):
                self.quality_combo.setCurrentText(config.get("quality"))

            self.concurrency_spin.setValue(config.get("concurrency", 2))

            # FFmpeg 路径检查
            ffmpeg_path = config.get("ffmpeg_path")
            if ffmpeg_path and self.is_ffmpeg_valid(ffmpeg_path):
                self.ffmpeg_edit.setText(ffmpeg_path)
        except Exception as e:
            self.log_display.append(
                f"<span style='color: #dc3545;'>⚠️ 配置读取失败，已使用默认设置: {e}</span>")
    def save_config(self):
        # 目录统一存绝对路径：相对路径按 BASE_DIR 展开，避免下次从别处启动时解析错位
        def _abs(text):
            text = (text or "").strip()
            if not text:
                return text
            p = Path(text)
            return str(p if p.is_absolute() else BASE_DIR / p)

        config = {
            "input_dir": _abs(self.input_edit.text()),
            "output_dir": _abs(self.output_edit.text()),
            "device": self.device_combo.currentText(),
            "lut_type": self.lut_type_combo.currentText(),
            "lut_path": self.lut_path_edit.text(),
            "encoder": self.encoder_combo.currentText(),
            "quality": self.quality_combo.currentText(),
            "concurrency": self.concurrency_spin.value(),
            "ffmpeg_path": self.ffmpeg_edit.text()
        }
        # 编码器探测缓存：仅在有结果时写入，避免覆盖已有缓存
        if getattr(self, "_encoder_cache", None):
            config["encoder_cache"] = self._encoder_cache
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def stop_tasks(self):
        """停止：清空排队任务，并真正终止正在运行的 FFmpeg 进程。"""
        self._is_running = False
        self.threadpool.clear()
        self.jobs.cancel()
        self._log_timer.stop()
        self._flush_log_buffer()
        self.log_display.append("<br>🛑 任务已取消")
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def update_progress(self, run_id):
        with self._progress_lock:
            self.completed_tasks += 1
            completed = self.completed_tasks

        # 已取消的任务、或上一轮遗留的回调，不再影响界面
        if not self._is_running or run_id != self._run_id:
            return

        if self.total_tasks > 0:
            self.progress_bar.setValue(int(completed / self.total_tasks * 100))

        if completed >= self.total_tasks:
            self._log_timer.stop()
            self._flush_log_buffer()
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._is_running = False
            self.log_display.append(
                "<br><b style='color: #28a745; font-size: 14px;'>🏆 批量转换任务全部完成！</b>")
            self.log_display.append(
                f"项目已保存在: <a href='file:///{self.output_edit.text()}'>{self.output_edit.text()}</a>")
            QMessageBox.information(self, "完成", f"已成功处理 {self.total_tasks} 个视频。")
    def start_export(self):
        self.save_config()
        input_dir = Path(self.input_edit.text().strip())
        output_dir = Path(self.output_edit.text().strip())
        lut_path = self.lut_path_edit.text().strip()
        ffmpeg_path = self.ffmpeg_edit.text().strip()
        encoder_type = self.encoder_combo.currentText()
        max_threads = self.concurrency_spin.value()
        quality_mode = self.quality_combo.currentText()

        if not self.input_edit.text().strip() or not self.output_edit.text().strip() or not lut_path:
            QMessageBox.warning(self, "提示", "请检查路径填写是否完整。")
            return

        if not input_dir.is_dir():
            QMessageBox.warning(self, "提示", f"素材目录不存在：\n{input_dir}")
            return

        if not Path(lut_path).is_file():
            QMessageBox.warning(self, "提示", f"LUT 文件不存在：\n{lut_path}")
            return

        if not self.is_ffmpeg_valid(ffmpeg_path):
            QMessageBox.warning(self, "提示",
                                f"FFmpeg 不可用：\n{ffmpeg_path}\n\n"
                                "请运行 src/setup_ffmpeg.py 自动下载，或手动指定 ffmpeg.exe。")
            return
        extensions = ["*.MP4", "*.mp4", "*.MOV", "*.mov"]
        video_files = set()
        for ext in extensions:
            video_files.update(input_dir.glob(ext))
        video_files = sorted(list(video_files))

        if not video_files:
            QMessageBox.information(self, "提示", "未找到视频文件。")
            return

        if not output_dir.exists():
            output_dir.mkdir(parents=True)
            
        self.total_tasks = len(video_files)
        self.completed_tasks = 0
        self._run_id += 1        # 新一轮任务，旧任务的进度回调会被忽略
        self.jobs.reset()
        self.threadpool.clear()
        self.progress_bar.setValue(0)
        self.log_display.clear()
        self._log_buffer.clear()

        # 打印友好的启动信息
        self.log_display.append("<b style='font-size: 14px; color: #0078d4;'>🚀 批量转换任务启动</b>")
        self.log_display.append(f"📅 启动时间: {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')}")
        self.log_display.append(f"🎬 使用滤镜: {Path(lut_path).name}")
        self.log_display.append(
            "💡 效果提示: " + describe_lut(lut_path, self.device_combo.currentText(),
                                           self.lut_type_combo.currentText()))
        self.log_display.append(f"📦 待处理视频: {self.total_tasks} 个")
        self.log_display.append(f"🛠️ 编码器: {encoder_type}")
        self.log_display.append(f"✨ 画质模式: {quality_mode}")
        self.log_display.append(f"⚙️ 并行数: {max_threads}")
        self.log_display.append("<hr>")
        self._log_timer.start()
        self._is_running = True  # 标记任务开始运行

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.threadpool.setMaxThreadCount(max_threads)

        # 将原始路径传给 Worker，在 Worker 内部处理转义
        for video in video_files:
            worker = ExportWorker(video, output_dir, lut_path, ffmpeg_path, encoder_type,
                                  quality_mode, self.jobs, self._run_id)
            worker.signals.log.connect(self._append_log_buffer)
            worker.signals.progress.connect(self.update_progress)
            self.threadpool.start(worker)
    def _append_log_buffer(self, text):
        """将日志加入缓冲区，由定时器批量刷新（减少界面重绘）。"""
        self._log_buffer.append(text)
        if not self._log_timer.isActive():
            # 定时器已停止（例如任务被取消时），立即刷新，避免日志丢失
            self._flush_log_buffer()

    def _flush_log_buffer(self):
        """批量刷新日志缓冲区"""
        if self._log_buffer:
            self.log_display.append("".join(self._log_buffer))
            self._log_buffer.clear()
    def closeEvent(self, event):
        self._log_timer.stop()
        # 关闭窗口时别留下后台 ffmpeg 进程
        self.threadpool.clear()
        self.jobs.cancel()
        self.save_config()
        event.accept()
def _set_windows_app_id():
    """Windows 任务栏图标修复：显式设置 AppUserModelID。

    否则打包后的 EXE 任务栏按钮无法与 EXE 内嵌图标关联，
    会出现「任务栏看不到图标」或显示成 python 图标的情况。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "DJI.Batch.LUTer")
    except Exception:
        pass


if __name__ == "__main__":
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("DJI Batch LUTer")
    app.setWindowIcon(QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
