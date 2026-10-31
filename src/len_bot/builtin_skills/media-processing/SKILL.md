---
name: media-processing
description: 用 FFmpeg 转换、裁剪、合并或检查音频、视频和图片媒体，按执行环境里实际的编码器和滤镜组织命令。
---

# 媒体处理

用 `ffmpeg` 完成具体的媒体变换。先用 `ffprobe`（`command -v ffprobe` 确认存在）或 `ffmpeg -i` 读取源文件的流信息，用 `ffmpeg -encoders`、`ffmpeg -filters` 查看实际的编码器与滤镜，再据此组织命令。

- 按请求确定保留的源流、时间范围、目标格式、尺寸、帧率和音频处理。源文件保持原样，输出写到 `/workspace/out` 下的新路径。
- 命令里写明 `-map` 和编码参数；运行后检查退出状态与输出，再读取时长、尺寸、声道，并查看有代表性的画面或短片段，确认结果包含请求的剪辑。
- 字幕和文字叠加使用系统中文字体（`fc-list :lang=zh` 查看字体名）；在样例帧上核对字体和位置。需要的编码器或滤镜不存在时，在结果里写明名称，并改用现有的等价方案。
- 用 `deliver_file(path, name, note)` 登记核对过的输出。
