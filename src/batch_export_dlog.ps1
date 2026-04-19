# ================= 配置区域 =================
$InputDir = "C:\Users\YANG\Desktop\DJI\RAW"
$OutputDir = "C:\Users\YANG\Desktop\DJI\EXPORT"
$LutFile = "C:\Users\YANG\Desktop\DJI\DJI OSMO Action 4 D-Log M to Rec.709 V1.cube"
$FfmpegPath = "C:\Program Files\EVCapture\ffmpeg.exe" # 自动检测到的本地 FFmpeg 路径
# ============================================

# 创建输出目录
if (!(Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
    Write-Host "已创建输出目录: $OutputDir" -ForegroundColor Cyan
}

# 获取视频文件 - 使用管道去重避免 Windows 下大小写重复
$Videos = Get-ChildItem -Path $InputDir -Include *.MP4, *.mp4, *.MOV, *.mov -Recurse | Select-Object -Unique FullName, Name, BaseName

if ($Videos.Count -eq 0) {
    Write-Host "未在 $InputDir 中找到视频文件。" -ForegroundColor Yellow
    exit
}

Write-Host "找到 $($Videos.Count) 个视频文件，准备处理..." -ForegroundColor Green

# 转换 LUT 路径中的反斜杠为正斜杠，并转义冒号（FFmpeg 要求）
$LutPathFfmpeg = $LutFile.Replace("\", "/").Replace(":", "\:")

foreach ($Video in $Videos) {
    $OutputFile = Join-Path $OutputDir ($Video.BaseName + "_Rec709.mp4")
    
    Write-Host "正在处理: $($Video.Name)..." -NoNewline
    
    # 构建并运行 FFmpeg 命令
    # 注意：-vf 参数中的路径需要用引号包裹
    & $FfmpegPath -i $Video.FullName `
        -vf "lut3d='$LutPathFfmpeg'" `
        -c:v libx264 -preset fast -crf 18 `
        -c:a copy `
        $OutputFile -y | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host " [完成]" -ForegroundColor Green
    } else {
        Write-Host " [失败]" -ForegroundColor Red
    }
}

Write-Host "`n所有任务已完成！" -ForegroundColor Green
Write-Host "导出文件夹: $OutputDir"
