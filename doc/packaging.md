# DJI Batch LUTer 打包指南

为了方便在没有 Python 环境的电脑上运行，你可以使用 `PyInstaller` 将本项目打包成独立的 `.exe` 可执行文件。

## 1. 安装打包工具

首先，确保安装了 `pyinstaller`：

```bash
pip install pyinstaller
```

## 2. 一键打包脚本

我已经在 `src/` 目录下为你准备了 `build.py`。你只需要运行它，它会自动处理资源路径并生成可执行文件。

```bash
python src/build.py              # 目录模式 (默认, 启动快) -> dist/
python src/build.py --onefile    # 单文件模式 (启动慢, 便于携带) -> dist/DJI_Batch_LUTer.exe
```

### 两种模式的区别

| 模式 | 产物 | 启动速度 | 原理 |
| :--- | :--- | :--- | :--- |
| 目录模式 (默认) | `dist/`（整个文件夹即完整项目，含 `_internal/`） | 快 | 依赖以文件形式存在，启动直接加载 |
| 单文件 `--onefile` | `dist/DJI_Batch_LUTer.exe` | 慢 | 每次启动都把约 38MB 内容解压到 `%TEMP%` 再运行 |

> 目录模式打完后 **`dist/` 直接就是可运行的项目**，不再多套一层 `dist/DJI_Batch_LUTer/`：
>
> ```text
> dist/
> ├── DJI_Batch_LUTer.exe
> ├── _internal/
> ├── config/
> ├── doc/
> ├── RAW/
> ├── EXPORT/
> └── dji_luter_config.json
> ```
>
> 🔒 **用户数据永不覆盖**：重新打包会先保留 `RAW/`、`EXPORT/` 和 `dji_luter_config.json` 的原有内容，再替换程序文件，因此素材与设置不会因编译丢失。若因文件占用导致恢复失败，脚本会**保留旧目录不删**并给出提示，确保素材不丢。`config/`、`doc/` 属程序资源，每次打包刷新。
>
> 两种模式的 EXE 路径统一为 `dist/DJI_Batch_LUTer.exe`，重新打包会整体替换 `dist/`（除上述受保护项）。

> 如果用户反馈「打开很慢」，优先给目录模式的包。

## 3. 手动打包命令

如果你想手动控制打包过程，可以使用以下命令：

```bash
pyinstaller --noconsole --name "DJI_Batch_LUTer" \
--add-data "src/assets;src/assets" \
--icon=src/assets/icon.ico \
src/DJI_Batch_LUTer.py
```

### 参数说明：
- `--noconsole`: 运行时不显示黑色的控制台窗口。
- `--onefile`: 打包成单个 `.exe`（不加则是目录模式，启动更快）。
- `--add-data`: 关键步骤！必须包含 `src/assets`（图标资源）。`config`（滤镜库）不打包进 EXE，由脚本在打包后复制到 EXE 同级目录。

## 4. 运行环境配置 (重要)

FFmpeg 体积较大（约 148MB），**不打包进 EXE，也不放进发布包**。发布包只包含 EXE + `config/` + `doc/`，因此非常小。

```text
📁 发布目录/
├── DJI_Batch_LUTer.exe
├── 📁 config/            # 滤镜库 (必需)
└── 📁 doc/               # 说明文档
```

用户首次运行后，点界面上的 **「下载 FFmpeg」** 按钮即可自动下载到 `ffmpeg/bin/ffmpeg.exe`。
程序启动时也会自动检测同级目录下的 `ffmpeg/bin/ffmpeg.exe`，若系统 PATH 里已有 FFmpeg 则直接使用。

## ⚠️ 注意事项

1. **FFmpeg**: 无需预先准备。程序会自动检测，缺失时可一键从国内镜像下载（约 20MB）。
2. **图标**: 如果你想给 exe 加个图标，可以增加 `--icon=assets/icon.ico` 参数。
3. **防病毒软件**: 有些杀毒软件可能会误报打包后的单文件 exe，建议在运行前将其加入白名单。
4. **打包前先关闭正在运行的程序**: 否则 `dist/DJI_Batch_LUTer.exe` 被占用会直接打包失败（`build.py` 已内置检测并给出提示）。
