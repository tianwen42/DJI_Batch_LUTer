import sys
import os
import subprocess
import json
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLineEdit, QLabel, QFileDialog, QTextEdit, 
                             QProgressBar, QMessageBox, QSpinBox, QComboBox, QGroupBox)
from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot, QDateTime
from PyQt6.QtGui import QIcon, QPixmap

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

# 基础目录 (用于存放配置文件、默认导出目录等)
BASE_DIR = get_base_path()
# 资源目录 (用于读取内置的 LUT 滤镜)
RESOURCE_DIR = get_resource_path("")

# 配置文件路径 (始终放在 EXE/脚本同级目录)
CONFIG_FILE = BASE_DIR / "dji_luter_config.json"
# 默认配置目录 (包含所有 LUT)
DEFAULT_CONFIG_DIR = RESOURCE_DIR / "config"
# 默认素材目录
DEFAULT_INPUT_DIR = BASE_DIR / "RAW"
# 默认导出目录
DEFAULT_OUTPUT_DIR = BASE_DIR / "EXPORT"
# 本地 FFmpeg 路径 (优先检查资源目录或基础目录下的 bin)
LOCAL_FFMPEG_PATH = RESOURCE_DIR / "bin" / "ffmpeg.exe"
# 用户自定义 FFmpeg 目录 (项目根目录下的 ffmpeg/bin/ffmpeg.exe)
USER_FFMPEG_PATH = RESOURCE_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"
# Logo 路径
LOGO_PATH = RESOURCE_DIR / "src" / "assets" / "logo_DJI Batch LUTer.jpg"
# Icon 路径 (用于窗口图标和打包图标)
ICON_PATH = RESOURCE_DIR / "src" / "assets" / "icon.ico"

def get_timestamp():
    return QDateTime.currentDateTime().toString("HH:mm:ss")

# 信号类，用于在线程间通信
class WorkerSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal()
    finished = pyqtSignal(str, bool)

# 单个视频处理任务
class ExportWorker(QRunnable):
    def __init__(self, video_path, output_dir, lut_path_ffmpeg, ffmpeg_path, encoder_type):
        super().__init__()
        self.video_path = Path(video_path)
        self.output_dir = Path(output_dir)
        self.lut_path_ffmpeg = lut_path_ffmpeg
        self.ffmpeg_path = ffmpeg_path
        self.encoder_type = encoder_type
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        output_file = self.output_dir / f"{self.video_path.stem}_Rec709.mp4"
        self.signals.log.emit(f"[{get_timestamp()}] <b style='color: #0078d4;'>[处理中]</b> {self.video_path.name}")
        
        cmd = [self.ffmpeg_path]
        cmd += ["-i", str(self.video_path.absolute())]
        
        # FFmpeg 滤镜路径转义逻辑 (Windows 特殊处理)
        # 1. 统一使用正斜杠
        # 2. 冒号需要转义，例如 C\:
        # 3. 路径两端使用单引号包裹
        abs_path = str(Path(self.lut_path_ffmpeg).absolute()).replace("\\", "/")
        safe_lut_path = abs_path.replace(":", "\\:")
        cmd += ["-vf", f"format=yuv420p,lut3d='{safe_lut_path}'"]

        if self.encoder_type == "NVIDIA (h264_nvenc)":
            cmd += ["-c:v", "h264_nvenc", "-preset", "fast", "-b:v", "20M"]
        elif self.encoder_type == "Intel (h264_qsv)":
            cmd += ["-c:v", "h264_qsv", "-preset", "fast", "-b:v", "20M"]
        elif self.encoder_type == "AMD (h264_amf)":
            cmd += ["-c:v", "h264_amf", "-b:v", "20M"]
        else: # CPU
            cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]

        cmd += ["-c:a", "copy", str(output_file.absolute()), "-y"]
        
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            process = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', startupinfo=startupinfo)
            
            if process.returncode == 0:
                self.signals.log.emit(f"<span style='color: #28a745;'>   ✅ 成功导出: {output_file.name}</span>")
                self.signals.finished.emit(self.video_path.name, True)
            else:
                error_msg = process.stderr if process.stderr else "未知错误"
                self.signals.log.emit(f"<span style='color: #dc3545;'>   ❌ 失败: {self.video_path.name}</span>")
                self.signals.log.emit(f"<small style='color: #666;'>      原因: {error_msg.strip()}</small>")
                self.signals.finished.emit(self.video_path.name, False)
        except Exception as e:
            self.signals.log.emit(f"<span style='color: #dc3545;'>   ❌ 意外错误: {str(e)}</span>")
            self.signals.finished.emit(self.video_path.name, False)
        
        self.signals.progress.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DJI Batch LUTer")
        self.setMinimumWidth(850)
        self.setMinimumHeight(750)
        
        self.threadpool = QThreadPool()
        self.cpu_count = os.cpu_count() or 2
        
        # LUT 数据结构: {设备名: {类型: [文件列表]}}
        self.lut_data = {}
        self.scan_luts()
        
        self.init_ui()
        self.load_config()
        self.auto_find_ffmpeg()
        
        # 检查 FFmpeg 是否可用
        if not self.is_ffmpeg_valid(self.ffmpeg_edit.text()):
            QMessageBox.warning(self, "FFmpeg 缺失", 
                "未检测到可用的 FFmpeg！\n\n"
                "1. 请运行项目根目录下的 'setup_ffmpeg.py' 自动下载配置。\n"
                "2. 或手动将 ffmpeg.exe 放入 ffmpeg/bin 目录下。\n"
                "3. 或在设置中手动指定 FFmpeg 路径。")
        
        # 如果配置文件不存在，立即保存一份默认配置
        if not CONFIG_FILE.exists():
            self.save_config()
        
        self.total_tasks = 0
        self.completed_tasks = 0

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
        input_btn = QPushButton("选择素材目录")
        input_btn.clicked.connect(lambda: self.select_dir(self.input_edit))
        input_layout.addWidget(QLabel("素材目录:"))
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(input_btn)
        dir_layout.addLayout(input_layout)

        # 导出目录
        output_layout = QHBoxLayout()
        self.output_edit = QLineEdit(str(DEFAULT_OUTPUT_DIR))
        output_btn = QPushButton("选择导出目录")
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
        self.device_combo.addItems(sorted(self.lut_data.keys()))
        self.device_combo.currentTextChanged.connect(self.on_device_changed)
        
        self.lut_type_combo = QComboBox()
        self.lut_type_combo.currentTextChanged.connect(self.on_lut_type_changed)
        
        self.lut_file_combo = QComboBox()
        self.lut_file_combo.currentTextChanged.connect(self.on_lut_file_combo_changed)
        
        selector_layout.addWidget(QLabel("设备:"))
        selector_layout.addWidget(self.device_combo)
        selector_layout.addSpacing(10)
        selector_layout.addWidget(QLabel("类型:"))
        selector_layout.addWidget(self.lut_type_combo)
        selector_layout.addSpacing(10)
        selector_layout.addWidget(QLabel("滤镜列表:"))
        selector_layout.addWidget(self.lut_file_combo, 1)
        
        lut_v_layout.addLayout(selector_layout)

        # 手动选择/显示路径
        path_layout = QHBoxLayout()
        self.lut_path_edit = QLineEdit()
        self.lut_path_edit.setPlaceholderText("当前选中的 LUT 路径...")
        lut_browse_btn = QPushButton("手动选择 LUT...")
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
        perf_layout.addWidget(QLabel("并行任务数:"))
        perf_layout.addWidget(self.concurrency_spin)
        
        perf_layout.addSpacing(20)
        
        # 设置 FFmpeg 默认显示路径 (优先项目自定义目录，其次内置 bin)
        default_ffmpeg = "ffmpeg"
        if USER_FFMPEG_PATH.exists():
            default_ffmpeg = str(USER_FFMPEG_PATH)
        elif LOCAL_FFMPEG_PATH.exists():
            default_ffmpeg = str(LOCAL_FFMPEG_PATH)
            
        self.ffmpeg_edit = QLineEdit(default_ffmpeg)
        ffmpeg_browse_btn = QPushButton("选择 FFmpeg...")
        ffmpeg_browse_btn.clicked.connect(self.select_ffmpeg_manually)
        perf_layout.addWidget(QLabel("FFmpeg 路径:"))
        perf_layout.addWidget(self.ffmpeg_edit)
        perf_layout.addWidget(ffmpeg_browse_btn)
        
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

    def on_lut_file_combo_changed(self, index):
        path = self.lut_file_combo.currentData()
        if path:
            self.lut_path_edit.setText(path)

    def select_lut_manually(self):
        start_dir = str(DEFAULT_CONFIG_DIR) if DEFAULT_CONFIG_DIR.exists() else str(BASE_DIR)
        file_path, _ = QFileDialog.getOpenFileName(self, "手动选择 LUT 文件", start_dir, "LUT Files (*.cube)")
        if file_path:
            self.lut_path_edit.setText(file_path)
            self.save_config()

    def select_ffmpeg_manually(self):
        start_dir = str(BASE_DIR)
        file_path, _ = QFileDialog.getOpenFileName(self, "手动选择 FFmpeg", start_dir, "FFmpeg (ffmpeg.exe);;All Files (*)")
        if file_path:
            self.ffmpeg_edit.setText(file_path)
            self.save_config()
            self.detect_available_encoders(file_path)

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
        """检查 FFmpeg 路径是否有效且可运行"""
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            res = subprocess.run([path, "-version"], capture_output=True, text=True, startupinfo=startupinfo)
            return res.returncode == 0
        except Exception:
            return False

    def auto_find_ffmpeg(self):
        # 1. 优先检查用户自定义的 ffmpeg 目录
        if USER_FFMPEG_PATH.exists() and self.is_ffmpeg_valid(str(USER_FFMPEG_PATH)):
            self.ffmpeg_edit.setText(str(USER_FFMPEG_PATH))
            self.log_display.append(f"✅ 使用本地自定义 FFmpeg: {USER_FFMPEG_PATH}")
            self.detect_available_encoders(str(USER_FFMPEG_PATH))
            return

        # 2. 检查本项目内置 bin 目录
        if LOCAL_FFMPEG_PATH.exists() and self.is_ffmpeg_valid(str(LOCAL_FFMPEG_PATH)):
            self.ffmpeg_edit.setText(str(LOCAL_FFMPEG_PATH))
            self.log_display.append(f"✅ 使用项目内置 FFmpeg: {LOCAL_FFMPEG_PATH}")
            self.detect_available_encoders(str(LOCAL_FFMPEG_PATH))
            return

        # 2. 尝试从配置文件恢复
        current_path = self.ffmpeg_edit.text()
        if current_path and current_path != "ffmpeg" and os.path.exists(current_path) and self.is_ffmpeg_valid(current_path):
            self.log_display.append(f"🔍 使用配置记录的 FFmpeg: {current_path}")
            self.detect_available_encoders(current_path)
            return

        # 3. 尝试其他可能路径 (优先尝试常见软件自带的稳定版)
        paths = [
            r"C:\Program Files\EVCapture\ffmpeg.exe",
            "ffmpeg",  # 系统 PATH
        ]
        for p in paths:
            if self.is_ffmpeg_valid(p):
                self.ffmpeg_edit.setText(p)
                self.log_display.append(f"🔍 自动找到可用 FFmpeg: {p}")
                self.detect_available_encoders(p)
                return
        
        self.log_display.append("<span style='color: #dc3545;'>❌ 未找到可用的 FFmpeg，请手动指定路径。</span>")

    def detect_available_encoders(self, ffmpeg_path):
        try:
            res = subprocess.run([ffmpeg_path, "-encoders"], capture_output=True, text=True)
            if "nvenc" in res.stdout:
                self.encoder_combo.setCurrentText("NVIDIA (h264_nvenc)")
            elif "qsv" in res.stdout:
                self.encoder_combo.setCurrentText("Intel (h264_qsv)")
            elif "amf" in res.stdout:
                self.encoder_combo.setCurrentText("AMD (h264_amf)")
        except:
            pass

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    # 检查路径是否存在，不存在则使用默认值
                    input_dir = config.get("input_dir")
                    if input_dir and os.path.exists(input_dir):
                        self.input_edit.setText(input_dir)
                    else:
                        self.input_edit.setText(str(DEFAULT_INPUT_DIR))

                    output_dir = config.get("output_dir")
                    if output_dir and os.path.exists(output_dir):
                        self.output_edit.setText(output_dir)
                    else:
                        self.output_edit.setText(str(DEFAULT_OUTPUT_DIR))
                    
                    # 恢复设备和类型选择
                    device = config.get("device")
                    if device: self.device_combo.setCurrentText(device)
                    ltype = config.get("lut_type")
                    if ltype: self.lut_type_combo.setCurrentText(ltype)
                    
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
                    
                    self.concurrency_spin.setValue(config.get("concurrency", 2))
                    
                    # FFmpeg 路径检查
                    ffmpeg_path = config.get("ffmpeg_path")
                    if ffmpeg_path and self.is_ffmpeg_valid(ffmpeg_path):
                        self.ffmpeg_edit.setText(ffmpeg_path)
            except:
                pass

    def save_config(self):
        config = {
            "input_dir": self.input_edit.text(),
            "output_dir": self.output_edit.text(),
            "device": self.device_combo.currentText(),
            "lut_type": self.lut_type_combo.currentText(),
            "lut_path": self.lut_path_edit.text(),
            "encoder": self.encoder_combo.currentText(),
            "concurrency": self.concurrency_spin.value(),
            "ffmpeg_path": self.ffmpeg_edit.text()
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def stop_tasks(self):
        self.threadpool.clear()
        self.log_display.append("\n🛑 任务已取消，正在等待当前视频完成...")
        self.stop_btn.setEnabled(False)

    def update_progress(self):
        self.completed_tasks += 1
        val = int((self.completed_tasks / self.total_tasks) * 100)
        self.progress_bar.setValue(val)
        
        if self.completed_tasks == self.total_tasks:
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.log_display.append("<br><b style='color: #28a745; font-size: 14px;'>🏆 批量转换任务全部完成！</b>")
            self.log_display.append(f"项目已保存在: <a href='file:///{self.output_edit.text()}'>{self.output_edit.text()}</a>")
            QMessageBox.information(self, "完成", f"已成功处理 {self.total_tasks} 个视频。")

    def start_export(self):
        self.save_config()
        input_dir = Path(self.input_edit.text())
        output_dir = Path(self.output_edit.text())
        lut_path = self.lut_path_edit.text()
        ffmpeg_path = self.ffmpeg_edit.text()
        encoder_type = self.encoder_combo.currentText()
        max_threads = self.concurrency_spin.value()

        if not all([input_dir, output_dir, lut_path]):
            QMessageBox.warning(self, "提示", "请检查路径填写是否完整。")
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
        self.progress_bar.setValue(0)
        self.log_display.clear()
        
        # 打印友好的启动信息
        self.log_display.append(f"<b style='font-size: 14px; color: #0078d4;'>🚀 批量转换任务启动</b>")
        self.log_display.append(f"📅 启动时间: {QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')}")
        self.log_display.append(f"🎬 使用滤镜: {Path(lut_path).name}")
        self.log_display.append(f"📦 待处理视频: {self.total_tasks} 个")
        self.log_display.append(f"🛠️ 编码器: {encoder_type}")
        self.log_display.append(f"⚙️ 并行数: {max_threads}")
        self.log_display.append("<hr>")

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.threadpool.setMaxThreadCount(max_threads)

        # 将原始路径传给 Worker，在 Worker 内部处理转义
        for video in video_files:
            worker = ExportWorker(video, output_dir, lut_path, ffmpeg_path, encoder_type)
            worker.signals.log.connect(self.log_display.append)
            worker.signals.progress.connect(self.update_progress)
            self.threadpool.start(worker)

    def closeEvent(self, event):
        self.save_config()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
