# YOLO Vision Mouse Control Lab

这是一个模块化的 Windows 实时视觉控制实验项目，将屏幕采集、YOLO 推理、ByteTrack 跟踪、目标选择、运动预测、控制器和输出后端拆分为可独立测试的模块。

## 下载 Windows 版

不需要配置 Python 的用户，请从 [GitHub Releases](https://github.com/Atlastwe/yolo-vision-mouse-control-lab/releases/latest) 下载 `YoloVisionControl-*-windows-x64.7z`，完整解压后运行 `YoloVisionControl.exe`。

GitHub 的 **Code → Download ZIP** 下载的是源码，不包含可运行 EXE。Windows 成品、版本说明和 SHA-256 校验文件统一放在 Releases 页面。

仓库仅包含应用源码、测试、依赖清单和使用文档。模型、数据集、运行输出、第三方 DLL、驱动文件以及本地 IDE 配置均不会上传。

本项目用于离线实验，以及你拥有的软件中的无障碍或相机控制功能。接入自制游戏时，推荐把控制器输出连接到游戏原生 Camera Controller，而不是系统级鼠标接口。

## 功能

- 只保留最新画面的低延迟采集流水线
- Ultralytics YOLO 目标检测
- 可选 ByteTrack 身份跟踪
- 目标锁定和切换迟滞
- 匀速 Kalman 预测
- 根据目标距离动态调整速度
- 接近目标后的停止半径
- DXCam 和 OBS 采集路径
- OpenCV 识别预览窗口
- PyAutoGUI 与可选 IbInputSimulator 输出后端
- 跟踪、目标选择和运动控制单元测试

## 两种运行模式

这个入口同时支持**独立运行**和**作为 OBS Python 脚本运行**，OBS 不是独立运行模式的必需依赖。

```text
直接执行 mymainproject.py
  └─ 找不到 obspython
     └─ 使用 DXCam 获取主显示器画面

通过 OBS 加载 mymainproject.py
  └─ OBS 提供 obspython
     └─ 读取用户指定的 OBS Source 画面
```

程序会根据 `obspython` 是否存在自动选择模式，不需要手动修改源码。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.10 或更高版本
- 支持 Ultralytics 的 PyTorch 环境
- NVIDIA GPU 为可选项；TensorRT `.engine` 模型需要匹配的 NVIDIA、CUDA 和 TensorRT 环境

## 安装

克隆仓库并进入项目目录：

```powershell
git clone https://github.com/Atlastwe/yolo-vision-mouse-control-lab.git
cd yolo-vision-mouse-control-lab
```

创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

如果只需要加载 YOLO 模型进行普通推理，安装 Ultralytics 即可：

```powershell
python -m pip install ultralytics
```

运行本仓库的完整实时程序，还需要屏幕采集、鼠标输出、Win32 按键检测和跟踪相关依赖：

```powershell
python -m pip install -r requirements.txt
```

`numpy`、`opencv-python` 和 PyTorch 会作为 Ultralytics 的依赖安装，因此没有在本仓库中重复声明。`dxcam`、`pyautogui` 和 `pywin32` 是本项目外围功能使用的直接依赖；`lap` 用于启用 ByteTrack 数据关联。

创建模型目录：

```powershell
New-Item -ItemType Directory -Force models
```

## 配置识别模型

模型配置位于 `mymain_app/config.py` 的 `DetectionConfig`：

```python
@dataclass(slots=True)
class DetectionConfig:
    model_path: Path = PROJECT_ROOT / "models" / "best.engine"
    class_priority: dict[str, int] = field(
        default_factory=lambda: {"Head": 0, "Enemy": 1}
    )
    image_size: int = 640
    confidence: float = 0.5
```

### 使用 PyTorch 模型

把模型放到 `models` 目录，例如：

```text
models/best.pt
```

然后修改模型路径：

```python
model_path: Path = PROJECT_ROOT / "models" / "best.pt"
```

### 使用 TensorRT 模型

把引擎放到：

```text
models/best.engine
```

并保持：

```python
model_path: Path = PROJECT_ROOT / "models" / "best.engine"
```

TensorRT 引擎通常与导出它的 GPU 架构、TensorRT 版本、CUDA 版本和输入尺寸相关。在另一台电脑上无法加载时，应当使用原始 `.pt` 模型在目标电脑上重新导出 `.engine`，不要直接复用不兼容的引擎。

### 修改识别类别

程序只选择 `class_priority` 中列出的类别。字典键必须与模型内部的类别名称完全一致，包括大小写。

例如模型类别为：

```python
{0: "person", 1: "head"}
```

配置应改为：

```python
class_priority: dict[str, int] = field(
    default_factory=lambda: {"head": 0, "person": 1}
)
```

数字越小，类别优先级越高。查看 `.pt` 模型类别名称可以运行：

```powershell
python -c "from ultralytics import YOLO; print(YOLO('models/best.pt').names)"
```

如果模型可以画出检测框，但程序始终没有选中目标，应首先检查 `class_priority` 是否与模型类别名称一致。

### 调整识别参数

常用参数都在 `DetectionConfig` 中：

```python
image_size: int = 640
confidence: float = 0.5
locked_target_confidence: float = 0.25
tracking_enabled: bool = True
tracker_config: str = "bytetrack.yaml"
tracker_input_confidence: float = 0.1
```

- `image_size`：YOLO 推理尺寸。数值增大可能改善小目标识别，但会增加延迟。
- `confidence`：新目标最低置信度。误检较多时提高，漏检较多时适当降低。
- `locked_target_confidence`：已锁定目标允许维持的最低置信度。
- `tracking_enabled`：是否启用 ByteTrack。
- `tracker_input_confidence`：送入跟踪器的最低置信度，通常不应高于 `confidence`。

更换模型后先执行完整检查：

```powershell
python mymainproject.py --check --no-elevate
```

出现以下输出表示依赖和模型均可加载：

```text
Dependency check passed, including model loading.
```

模型权重和推理引擎已被 `.gitignore` 排除，因此替换本地模型不会被普通的 `git add .` 上传到 GitHub。

## 修改操纵方式

操纵方式配置位于 `mymain_app/config.py` 的 `MouseConfig`。项目实现了统一的相对移动接口，上层控制器始终输出 `dx, dy`，再由所选后端发送。

### 使用 PyAutoGUI

PyAutoGUI 是不需要额外 DLL 的备用输出方式。需要使用时，将配置改为：

```python
mode: str = "pyautogui"
pyautogui_pause_s: float = 0.0
pyautogui_failsafe: bool = True
```

如果只安装了 `ultralytics`，还需要补装 PyAutoGUI 和 Win32 支持：

```powershell
python -m pip install pyautogui pywin32
```

### 使用 IbInputSimulator

IbInputSimulator 不是 PyPI 包，不能通过 `pip install`安装，因此没有把它写进 `requirements.txt`。

发布版默认使用 IbInputSimulator，并默认以鼠标右键作为激活键：

```python
mode: str = "ib"
activation_key: int = 0x02
```

- 项目主页：[Chaoses-Ib/IbInputSimulator](https://github.com/Chaoses-Ib/IbInputSimulator)
- 下载页面：[IbInputSimulator Releases](https://github.com/Chaoses-Ib/IbInputSimulator/releases)

下载并解压后，可以放到仓库根目录。以 `0.4.1` 为例：

```text
yolo-vision-mouse-control-lab/
├─ IbInputSimulator-0.4.1/
│  └─ Binding.AHK2/
│     └─ IbInputSimulator.dll
├─ mymain_app/
└─ mymainproject.py
```

源码运行时应确认 `MouseConfig` 中的路径与实际 DLL 位置一致：

```python
mode: str = "ib"
dll_path: Path = (
    PROJECT_ROOT
    / "IbInputSimulator-0.4.1"
    / "Binding.AHK2"
    / "IbInputSimulator.dll"
)
preferred_send_type: int = 6  # LogitechGHubNew
fallback_send_type: int = 1   # Windows SendInput
```

桌面控制面板可以直接选择具体发送类型：

- `LogitechGHubNew`：适用于较新的 G HUB 虚拟设备；
- `LogitechLegacy`：使用旧版 Logitech 5 字节鼠标报告；
- `SendInput`：仍通过 IbInputSimulator API 调用，但底层使用 Windows SendInput。

某些 G HUB 版本会出现“初始化成功，但设备移动没有实际效果”。此时程序无法仅根据初始化返回值自动判断，应由用户在控制面板中依次尝试 `LogitechLegacy` 和 `SendInput`。启动后右上角显示的是最终实际启用的后端。

调试日志会记录以下关键状态：

```text
[debug] activation key pressed
[debug] mouse command: dx=12 dy=-4 accepted=True
```

`accepted=True` 只表示 IbInputSimulator 接受了调用；如果光标或游戏视角仍未移动，问题位于所选发送类型与当前 G HUB/目标程序的兼容路径，而不是右键检测或控制器没有发出命令。

### 调节移动速度

桌面控制面板提供 `0.10x` 到 `3.00x` 的移动速度倍率，默认值为 `1.00x`。滑条和数值框可以在流水线运行时实时调节，不需要停止程序。

速度倍率作用于控制器命令，并继续经过加速度、加加速度和最大速度限制，因此不会绕过原有的平滑移动逻辑。接近目标时的动态减速和进入停止半径后停止移动也保持不变。

源码默认值位于 `ControlConfig`：

```python
speed_multiplier: float = 1.0
```

如果下载的版本目录不是 `IbInputSimulator-0.4.1`，应把 `dll_path` 中的目录名改成实际名称。启动日志会显示最终启用的后端：

```text
IbMouseInput/LogitechGHubNew
```

如果首选后端初始化失败，程序会尝试 `fallback_send_type`。看到下面的日志表示已经退回 Windows SendInput：

```text
IbMouseInput/SendInput
```

IbInputSimulator 目录和 DLL 已被 `.gitignore` 排除，不会随普通 Git 提交上传。

### 修改激活按键

`activation_key` 使用 Windows Virtual-Key 键码。默认值 `0x02` 是鼠标右键，程序只在按住该键时执行控制输出：

```python
activation_key: int = 0x02
```

常用键码：

| 按键 | 键码 |
| --- | --- |
| 鼠标左键 | `0x01` |
| 鼠标右键 | `0x02` |
| 鼠标中键 | `0x04` |
| 鼠标侧键 1 | `0x05` |
| 鼠标侧键 2 | `0x06` |
| Shift | `0x10` |
| Ctrl | `0x11` |
| Alt | `0x12` |

例如改为按住鼠标侧键 1 时启用：

```python
activation_key: int = 0x05
```

## 独立运行

独立运行不需要安装或启动 OBS。程序使用 DXCam 获取主显示器画面，再按照 `DetectionConfig` 中的 `crop_width_ratio` 和 `crop_height_ratio` 截取屏幕中心区域进行推理。

在仓库根目录打开 PowerShell，激活安装过依赖的 Python 环境，然后检查环境和模型：

```powershell
python mymainproject.py --check --no-elevate
```

检查通过后直接启动：

```powershell
python mymainproject.py --no-elevate
```

不显示 OpenCV 预览窗口：

```powershell
python mymainproject.py --no-preview --no-elevate
```

独立模式的调用路径为：

```text
Python入口 → DXCam桌面采集 → YOLO/ByteTrack → 控制器 → 所选输出后端
```

操作方式：

- 按住鼠标右键：启用控制输出
- `F8`：显示或隐藏识别预览窗口
- 预览窗口中按 `Q`：关闭程序
- 无预览运行时按 `Ctrl+C`：停止程序

省略 `--no-elevate` 时，程序会尝试请求管理员权限。

## 作为 OBS 脚本运行

OBS 模式不使用 DXCam，而是从 OBS 中读取一个已存在的 Source。入口脚本必须和 `mymain_app` 文件夹保持当前相对位置，不能只把单独一个 `mymainproject.py` 复制到别处。

目录应保持为：

```text
yolo-vision-mouse-control-lab/
├─ mymain_app/
├─ models/
│  └─ best.engine
└─ mymainproject.py
```

### 1. 配置 OBS 的 Python 环境

OBS 只能加载其当前版本支持的 Python 版本。准备一个兼容的 Python 安装，并使用该解释器安装项目依赖：

```powershell
C:\Path\To\Python\python.exe -m pip install -r requirements.txt
```

然后在 OBS 中打开：

```text
工具 → 脚本 → Python 设置
```

把 Python 安装路径设置为上一步解释器所在目录。依赖必须安装到 OBS 实际使用的这个 Python 中；仅安装到另一个 Conda 或虚拟环境不会自动被 OBS 看见。

### 2. 准备 OBS Source

在 OBS 的“来源”面板中创建一个来源，例如“游戏采集”“窗口采集”或“显示器采集”，并记住它在来源面板中的**完整名称**。

### 3. 加载脚本

打开：

```text
工具 → 脚本 → Python 脚本
```

点击 `+`，选择仓库根目录中的 `mymainproject.py`。脚本成功加载后会显示这些属性：

- `OBS source name`：填写上一步的来源名称，必须完全一致
- `Auto start`：加载脚本后自动启动
- `Enable recognition inspector`：启用识别预览
- `Show inspector at startup`：启动时显示预览窗口
- `Inspector window width`：预览窗口宽度
- `Start`：手动启动
- `Stop`：手动停止

建议第一次使用时不要勾选 `Auto start`，先填写并确认 `OBS source name`，再点击 `Start`。如果名称为空或拼写不一致，日志会显示 `OBS source not found`。

OBS 模式的调用路径为：

```text
OBS Source → OBS纹理读取 → YOLO/ByteTrack → 控制器 → 所选输出后端
```

在 OBS 模式中不要再从 PowerShell执行 `python mymainproject.py`；脚本的加载、启动、停止和卸载都由 OBS 调用。

## 打包为 EXE

EXE 只支持独立 DXCam 模式，不能作为 OBS Python 脚本加载。OBS 模式仍应使用 `mymainproject.py`；要制作可由 OBS 直接安装的二进制组件，需要另行开发原生 OBS 插件。

本项目使用 PyInstaller 的 `onedir`模式。Torch、CUDA、TensorRT 和 Ultralytics 包含大量动态库，目录模式比单文件模式更容易验证和排查。

### 1. 安装构建依赖

在能够正常运行项目的 Python 环境中执行：

```powershell
python -m pip install -r requirements-build.txt
```

### 2. 执行构建脚本

只构建程序，不复制模型和 IbInput：

```powershell
.\build_exe.ps1 -Python "python"
```

构建并复制 TensorRT 模型：

```powershell
.\build_exe.ps1 `
  -Python "D:\anaconda\envs\yolo\python.exe" `
  -ModelPath "D:\path\to\best.engine"
```

同时复制 IbInput DLL：

```powershell
.\build_exe.ps1 `
  -Python "D:\anaconda\envs\yolo\python.exe" `
  -ModelPath "D:\path\to\best.engine" `
  -IbInputDllPath "D:\path\to\IbInputSimulator.dll"
```

脚本会依次运行单元测试、执行 PyInstaller、补齐 Conda MKL 运行库，并将外部资源放到程序预期目录。

### 3. 验证成品

构建结果位于：

```text
dist/YoloVisionControl/
```

双击 `YoloVisionControl.exe`，或从 PowerShell 启动：

```powershell
.\dist\YoloVisionControl\YoloVisionControl.exe
```

程序会打开常驻控制面板，不再依赖命令行窗口。界面中可以：

- 浏览并切换 `.engine`、`.pt` 或 `.onnx` 模型；
- 切换 `pyautogui` 与 `ib` 输出方式；
- 选择激活按键，并控制是否显示识别预览；
- 点击“检查环境”验证依赖和模型是否能加载；
- 点击“启动”或“停止”控制后台流水线；
- 在“运行日志”中查看初始化进度、当前鼠标后端和错误堆栈。

建议首次运行先点“检查环境”，显示“检查通过”后再启动。即使初始化失败，控制面板也会保持打开，并在日志区显示原因。

### 4. 分发目录

必须分发整个 `dist/YoloVisionControl`目录，不能只复制 `YoloVisionControl.exe`。推荐结构：

```text
YoloVisionControl/
├─ YoloVisionControl.exe
├─ _internal/
├─ models/
│  └─ best.engine
└─ IbInputSimulator-0.4.1/
   └─ Binding.AHK2/
      └─ IbInputSimulator.dll
```

模型和 IbInput DLL 保持外置，替换它们时不需要重新构建 EXE。CUDA 版 PyTorch 和 TensorRT 会使目录体积达到数 GB，这是 GPU 运行库造成的。

需要使用命令行参数时，仍可通过源码入口 `python mymainproject.py ...` 运行；打包后的 EXE 是桌面面板入口，不解析源码入口的命令行参数。

### 5. 制作 GitHub Release 附件

不要把 `dist` 目录提交到 Git。完成构建后，用 7-Zip 生成一个便于下载的发布包：

```powershell
.\package_release.ps1 -Version "0.1.0"
```

输出位于 `release/`：

```text
YoloVisionControl-v0.1.0-windows-x64.7z
YoloVisionControl-v0.1.0-windows-x64.7z.sha256
```

压缩包内只有一个顶层 `YoloVisionControl` 文件夹。下载者解压后直接运行其中的 `YoloVisionControl.exe`；`_internal` 是程序运行库，不能单独删除。发布包和校验文件应上传到 GitHub 的 **Releases**，而不是放在仓库源码文件列表中。

## 测试

```powershell
python -m unittest discover -s tests -v
```

## 常见问题

### `YOLO model not found`

检查 `model_path` 是否指向实际存在的文件，并确认路径相对于仓库根目录。

### 更换模型后没有目标

检查模型的 `names`，并让 `class_priority` 的键与类别名称完全一致。同时确认 `confidence` 没有设置过高。

### `.engine` 无法加载

先使用 `.pt` 模型验证代码。如果 `.pt` 正常而 `.engine` 失败，通常是 TensorRT、CUDA、GPU 架构或固定输入尺寸不兼容，应在当前电脑重新导出引擎。

### 启用跟踪后提示缺少 `lap`

重新安装依赖：

```powershell
python -m pip install -r requirements.txt
```

### OBS 加载脚本时提示缺少模块

这通常表示依赖安装到了另一个 Python 环境。确认 OBS“Python 设置”中的路径，然后使用该目录下的 `python.exe -m pip install -r requirements.txt`重新安装。

### `OBS source not found`

确认 `OBS source name` 与 OBS“来源”面板中的名称逐字一致，并且该来源尚未被删除。

## 目录结构

- `mymain_app/config.py`：所有运行参数
- `mymain_app/capture.py`：画面采集后端
- `mymain_app/detector.py`：YOLO 推理与目标选择
- `mymain_app/motion.py`：预测与视觉伺服控制器
- `mymain_app/mouse_input.py`：可切换输出后端
- `mymain_app/pipeline.py`：采集、推理和控制工作线程
- `mymain_app/preview.py`：识别预览窗口
- `mymainproject.py`：命令行与 OBS 兼容入口
- `tests/`：单元测试

