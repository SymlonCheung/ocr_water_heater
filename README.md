# OCR Water Heater

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

通过摄像头 OCR 识别热水器面板温度，并通过红外/继电器控制热水器。

## Description (对应 docs-high-level-description)
这个集成使用 `ddddocr` 识别摄像头画面中的 LED 数字... (此处填写详细描述)

## Installation (对应 docs-installation-instructions)
1. 安装 HACS。
2. 在 HACS 中添加自定义存储库：`你的Github仓库地址`。
3. 搜索 "OCR Water Heater" 并下载。
4. 重启 Home Assistant。

## Configuration (对应 docs-actions)
1. 前往 **设置** > **设备与服务**。
2. 点击 **添加集成**，搜索 "OCR Water Heater"。
3. 输入视频流 URL 和相关坐标参数。

## Removal (对应 docs-removal-instructions)
1. 在集成页面删除设备条目。
2. 在 HACS 中卸载组件。
3. 重启 Home Assistant。