# ESP32 固件批量烧录工具（PyQt6）

面向产线与批量场景的 **ESP32 系列多端口并行烧录** 桌面工具。界面基于 **PyQt6**，在大量日志、长时间运行时保持流畅，并便于复制、导出与追溯。

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)](https://www.riverbankcomputing.com/software/pyqt/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)](https://www.microsoft.com/windows)

---
[English](README-en.md) | [中文](README.md)
---
## 感谢您的 star
 - 如果喜欢本工具，请来个 Star ⭐

## 功能概览

- **多串口并行烧录**：最多 **8 路** 同时烧录，独立进度与日志。
- **自动芯片识别**：根据 esptool 检测结果匹配 ESP32 / S2 / S3 / C2 / C3 / C6 / H2 / H4 / P4 / 8266 等目标参数。
- **多固件分区**：多组 `.bin` 与烧录地址可配置，适应 bootloader、分区表、应用等常见布局。
- **自动烧录模式**：设备就绪后自动开始，适合流水线插拔。
- **擦除 Flash**：可选全片擦除后再写入。
- **多波特率可选**：支持至 **2000000** 等档位（视 USB 与线材而定）。
- **配置持久化**：固件路径、波特率、选项等自动保存，下次打开即用。
- **独立端口日志**：每路串口单独日志窗口；可关闭窗口取消该路任务并释放串口；关闭主窗口可结束全部烧录。
- **烧录统计与导出**：成功/失败计数；支持导出 **CSV**（含时间、端口、芯片、MAC、状态、错误信息）。

---

## 亮点

### 界面

- **深色主题 + QSS**：护眼色、暗色背景、分组区域描边、自定义滚动条，分区清晰，长时间盯屏更舒适。
- **Fusion 样式**：在 Windows 上与样式表配合稳定，避免主窗口控件绘制残缺、留白异常。
- **主窗口与端口日志采用只读文本区**：支持拖选、**Ctrl+C** 复制整段日志，便于粘贴到工单或问题反馈。
- **端口日志窗口级联排布**：按打开顺序在主窗口旁阶梯偏移，减少完全重叠。
- **按钮与控件**：针对 Windows 下样式表与原生按钮的交互做了适配（如实心底色、避免仅显示边框线）。

### 程序界面截图
![ESP32-main](pic/main.png)
![ESP32-all](pic/all.png)
![ESP32-export](pic/export.png)

### 打包与运行

- **单文件 exe（PyInstaller onefile）友好**：专用入口 **`__ESP32_PYQT_ESPTOOL__`**，子进程只跑 esptool 命令行，**不会**再拉起第二个图形主窗口。
- **源码调试**时仍可使用 `python -m esptool`，与日常开发习惯一致。
- **Windows 下子进程**：可为 esptool 使用无控制台创建标志，减少多余黑窗（具体表现依系统策略而定）。

### 配置与图标

- **配置位置**：打包为 exe 时，`config.json` 写在 **exe 同目录**，不写临时解压目录，避免每次运行配置丢失。
- **图标**：优先加载同目录或打包资源中的 `app_exe.ico` 等；必要时在 Windows 上可从 **exe 自身** 回退读取 Shell 图标，并在首帧后再次应用，改善标题栏与任务栏显示。

### 记录与排障

- **CSV 导出**：**UTF-8 带 BOM**，Excel 可直接打开；失败记录包含 **错误信息** 列。
- **失败详情**：esptool 非零退出时，将 **控制台输出尾部若干行** 写入错误说明，便于对照导出表排查，而非仅显示数字退出码。

### 其它

- **高 DPI**：启用 `HighDpiScaleFactorRoundingPolicy.PassThrough`，减轻多显示器缩放下的模糊与错位（依系统/Qt 版本而定）。
- **一键打包脚本 `build.bat`**：使用 **UTF-8 BOM**、**CRLF**、正确的 `pip` 引号与 `DisableDelayedExpansion`，避免双击批处理时出现乱码或命令被拆行。

---

## 支持的芯片

与 **esptool** 官方支持范围一致，包括但不限于：

| 芯片型号                        | 说明                |
|-----------------------------|-------------------|
| ESP32 / ESP32-S2 / ESP32-S3 | 常用                |
| ESP32-C2 / C3 / C6          | RISC-V 系列等        |
| ESP32-H2 / ESP32-P4 等       | 以实际检测与 esptool 为准 |
| ESP8266                     | 其它                |
---

## 快速开始

### 环境要求

- Python **3.8+**
- Windows（打包脚本与图标策略主要针对 Windows；源码可在其它系统上尝试运行）

### 安装依赖

```bash
cd esp32-flash-tool-pyqt
pip install -r requirements.txt
```

### 运行（源码）

```bash
python main.py
```

### 打包为 exe

1. 将 **`app_exe.ico`** 置于工程目录（与 `build.bat` 中 `ICON_PATH` 一致）。
2. 运行 **`build.bat`**（批处理建议保存为 **UTF-8 带 BOM**、换行 **CRLF**）。
3. 输出：`dist\esp32_flasher_pyqt.exe`

打包命令会为 onefile 附加 `--icon` 与 `--add-data`，便于运行时解析图标资源。

---

## 项目结构（简要）

```
esp32-flash-tool-pyqt/
├── main.py              # 程序入口与界面/业务逻辑
├── requirements.txt     # 依赖
├── build.bat            # PyInstaller 一键打包
├── app_exe.ico          # 图标（需自备）
├── config.json          # 运行后生成（勿打入 exe）
└── README.md            # 本说明
```

---

## 依赖库

| 库名 | 用途 |
|------|------|
| PyQt6 | 图形界面 |
| esptool | 烧录与设备通信 |
| pyserial | 串口枚举与释放 |
| pyinstaller | 打包（可选，由 build.bat 安装） |


---

## 故障排除

| 现象 | 建议 |
|------|------|
| 双击 `build.bat` 乱码、命令被拆碎 | 将 `build.bat` 存为 **UTF-8 带 BOM**，换行 **CRLF** |
| 打包后出现第二个主窗口 | 保留程序内专用 esptool 子进程入口，勿改为用同一 GUI 可执行文件直接执行 `python -m esptool` 拉起界面 |
| 串口仍被占用 | 关闭对应端口日志窗口或主窗口，必要时重新插拔设备 |

---

## 许可证

**MIT License**（若本目录提供 `LICENSE` 文件，以该文件为准）。

---

## 致谢

- [esptool](https://github.com/espressif/esptool)  

- [PyQt](https://www.riverbankcomputing.com/software/pyqt/)  

- [PyInstaller](https://pyinstaller.org/)


---

**说明**：文档内容与当前 `main.py` 实现同步；若程序有更新而未改文档，以代码为准。
