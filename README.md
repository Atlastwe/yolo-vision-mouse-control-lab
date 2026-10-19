# YOLO Vision Mouse Control Lab

这是一个模块化的 Windows 实时视觉控制实验项目，将屏幕采集、YOLO 推理、ByteTrack 跟踪、目标选择、运动预测、控制器和输出后端拆分为可独立测试的模块。

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

发布版默认使用 PyAutoGUI，不需要额外 DLL：

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

然后修改 `MouseConfig`：

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

## 运行方法

先检查环境和模型：

```powershell
python mymainproject.py --check --no-elevate
```

正常运行：

```powershell
python mymainproject.py --no-elevate
```

不显示 OpenCV 预览窗口：

```powershell
python mymainproject.py --no-preview --no-elevate
```

操作方式：

- 按住鼠标右键：启用控制输出
- `F8`：显示或隐藏识别预览窗口
- 预览窗口中按 `Q`：关闭程序
- 无预览运行时按 `Ctrl+C`：停止程序

省略 `--no-elevate` 时，程序会尝试请求管理员权限。

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

