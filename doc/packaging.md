# DJI Batch LUTer 打包指南

为了方便在没有 Python 环境的电脑上运行，你可以使用 `PyInstaller` 将本项目打包成独立的 `.exe` 可执行文件。

## 1. 安装打包工具

首先，确保安装了 `pyinstaller`：

```bash
pip install pyinstaller
```

## 2. 一键打包脚本

我已经在 `src/` 目录下为你准备了 `build.py`。你只需要运行它，它会自动处理资源路径并生成 exe。

```bash
python src/build.py
```

## 3. 手动打包命令

如果你想手动控制打包过程，可以使用以下命令：

```bash
pyinstaller --noconsole --onefile --name "DJI_Batch_LUTer" \
--add-data "config;config" \
--add-data "bin;bin" \
--add-data "ffmpeg;ffmpeg" \
src/DJI_Batch_LUTer.py
```

### 参数说明：
- `--noconsole`: 运行时不显示黑色的控制台窗口。
- `--onefile`: 将所有内容打包进一个单独的 `.exe` 文件中（注意：这会增加启动时间，因为每次运行都要解压）。
- `--add-data`: 关键步骤！必须包含 `config`（滤镜）和 `bin`（FFmpeg）目录，否则打包后的程序无法正常工作。

## 4. 打包后的结果

打包完成后，你会在项目目录下看到两个新文件夹：
- **build/**: 打包过程中的临时文件（可以删除）。
- **dist/**: 存放最终生成的 **DJI_Batch_LUTer.exe**。

## ⚠️ 注意事项

1. **FFmpeg**: 请确保在打包前，`bin/ffmpeg.exe` 已经存在。
2. **图标**: 如果你想给 exe 加个图标，可以增加 `--icon=assets/icon.ico` 参数。
3. **防病毒软件**: 有些杀毒软件可能会误报打包后的单文件 exe，建议在运行前将其加入白名单。
