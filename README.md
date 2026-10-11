# YOLO Vision Mouse Control Lab

A modular Windows project for experimenting with real-time screen capture, YOLO inference, target tracking, motion control, preview, and interchangeable output backends.

The repository contains only the application source, tests, dependency list, and documentation. Model files, datasets, generated output, third-party binaries, and local IDE settings are intentionally excluded.

It is intended for offline experiments and accessibility or camera-control features in software you own. For an actual game project, connect the controller output to the game's native camera API instead of system-wide input.

## Features

- Latest-frame capture pipeline to avoid processing stale frames
- Ultralytics YOLO detection with optional ByteTrack identity tracking
- Target lock and switching hysteresis
- Constant-velocity Kalman prediction
- Distance-aware speed scaling and a configurable stop radius
- DXCam and OBS capture paths
- OpenCV recognition preview
- PyAutoGUI and optional IbInputSimulator output adapters
- Unit tests for the tracking and motion logic

## Setup

Use Python 3.10 or newer on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Place your own trained model at `models/best.engine` or update `DetectionConfig.model_path` in `mymain_app/config.py`. Model weights and TensorRT engines are deliberately not committed.

The portable configuration defaults to PyAutoGUI. IbInputSimulator is optional and its DLL is not redistributed here; install it separately and update `MouseConfig.dll_path` before selecting `mode = "ib"`.

## Run

Check dependencies and model loading:

```powershell
python mymainproject.py --check --no-elevate
```

Run without the preview window:

```powershell
python mymainproject.py --no-preview --no-elevate
```

Runtime parameters live in `mymain_app/config.py`. The startup log reports the active capture and mouse-output backends.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Repository Contents

- `mymain_app/capture.py`: capture backend abstraction
- `mymain_app/detector.py`: YOLO inference and target selection
- `mymain_app/motion.py`: prediction and visual-servo controller
- `mymain_app/mouse_input.py`: interchangeable output adapters
- `mymain_app/pipeline.py`: capture, inference, and control workers
- `mymain_app/preview.py`: recognition inspector
- `mymainproject.py`: command-line and OBS-compatible entry point

