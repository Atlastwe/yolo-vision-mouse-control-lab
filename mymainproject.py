"""Compatibility entry point for the modular mymain_app package."""

from __future__ import annotations

import argparse
import atexit
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mymain_app.app import Application, check_dependencies, relaunch_as_admin
from mymain_app.config import AppConfig


try:
    import obspython as obs  # type: ignore
except ImportError:
    obs = None


config = AppConfig()
app = Application(config, obs=obs)
atexit.register(app.stop)


def script_description():
    return "Modular capture, inference, tracking, and recognition-inspector workflow."


def _start_button(props, prop):
    print("[mymain] start requested", flush=True)
    app.start()
    return True


def _stop_button(props, prop):
    print("[mymain] stop requested", flush=True)
    app.stop()
    return True


def script_properties():
    if obs is None:
        return None
    properties = obs.obs_properties_create()
    obs.obs_properties_add_text(
        properties, "obs_source_name", "OBS source name", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_properties_add_bool(properties, "auto_start", "Auto start")
    obs.obs_properties_add_bool(properties, "show_preview", "Enable recognition inspector")
    obs.obs_properties_add_bool(
        properties, "preview_visible_at_start", "Show inspector at startup"
    )
    obs.obs_properties_add_int(
        properties, "preview_window_width", "Inspector window width", 320, 2560, 10
    )
    obs.obs_properties_add_button(properties, "start_now", "Start", _start_button)
    obs.obs_properties_add_button(properties, "stop_now", "Stop", _stop_button)
    return properties


def script_defaults(settings):
    if obs is None:
        return
    obs.obs_data_set_default_bool(settings, "auto_start", False)
    obs.obs_data_set_default_bool(settings, "show_preview", True)
    obs.obs_data_set_default_bool(settings, "preview_visible_at_start", True)
    obs.obs_data_set_default_int(settings, "preview_window_width", 900)


def script_update(settings):
    if obs is None:
        return
    config.obs_source_name = obs.obs_data_get_string(settings, "obs_source_name")
    config.output.show_preview = obs.obs_data_get_bool(settings, "show_preview")
    config.output.preview_visible_at_start = obs.obs_data_get_bool(
        settings, "preview_visible_at_start"
    )
    config.output.preview_window_width = obs.obs_data_get_int(
        settings, "preview_window_width"
    )
    app.sync_preview()
    if obs.obs_data_get_bool(settings, "auto_start"):
        app.start()


def script_load(settings):
    if settings is not None:
        script_update(settings)


def script_unload():
    app.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Modular mymainproject runtime")
    parser.add_argument("--check", action="store_true", help="check dependencies and model loading")
    parser.add_argument("--no-preview", action="store_true", help="run without the OpenCV preview")
    parser.add_argument("--no-elevate", action="store_true", help="do not request administrator privileges")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config.output.show_preview = not args.no_preview
    if args.check:
        errors = check_dependencies(config, load_model=True)
        if errors:
            print("Dependency check failed:")
            for error in errors:
                print(f"- {error}")
            return 1
        print("Dependency check passed, including model loading.")
        return 0
    if not args.no_elevate and relaunch_as_admin():
        return 0
    try:
        app.run_foreground()
        return 0
    finally:
        app.stop()


if __name__ == "__main__" and obs is None:
    raise SystemExit(main())
