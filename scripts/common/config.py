from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PIPELINE_CONFIG = Path("pipeline.toml")
DEFAULT_JOBS_DIR = Path("jobs")
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_SERVER_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 5000
DEFAULT_SECRET_KEY = "karaoke-local-dev"
DEFAULT_MAX_UPLOAD_MB = 512
DEFAULT_STYLE_PRESET_ID = "single-style-kf"
DEFAULT_GENERATE_STYLE_PRESET_ID = DEFAULT_STYLE_PRESET_ID
DEFAULT_GENERATE_RESOLUTION = "1920x1080"
DEFAULT_GENERATE_FADE_IN_MS = 300
DEFAULT_GENERATE_FADE_OUT_MS = 500
DEFAULT_OUTPUT_AUDIO_CODEC = "aac"
DEFAULT_OUTPUT_AUDIO_BITRATE = "192k"
DEFAULT_OUTPUT_VOCALS_VOLUME = 1.0
DEFAULT_OUTPUT_INSTRUMENTAL_VOLUME = 1.0
DEFAULT_OUTPUT_FRAMERATE = "30"
DEFAULT_OUTPUT_FFMPEG_TIMEOUT_S = 600
DEFAULT_S01_FFPROBE_TIMEOUT_S = 30
DEFAULT_S01_FFMPEG_TIMEOUT_S = 300
DEFAULT_INPUT_FFMPEG_TIMEOUT_S = 120
DEFAULT_GENERATE_ASS_TIMEOUT_S = 120
DEFAULT_VALIDATE_TIMEOUT_S = 120
DEFAULT_TRANSCRIBE_MODEL_SIZE = "large-v3"
DEFAULT_TRANSCRIBE_LANGUAGE = "auto"
DEFAULT_TRANSCRIBE_LOW_CONFIDENCE_THRESHOLD = 0.25
DEFAULT_ALIGN_HUBERTFA_DIR = Path("vendor/HubertFA")
DEFAULT_ALIGN_CHECKPOINT = Path("models/hubertfa/model.onnx")
DEFAULT_ALIGN_LANGUAGE = "en"
DEFAULT_ALIGN_HUBERTFA_TIMEOUT_S = 180
DEFAULT_DEMUCS_MODEL = "htdemucs"
DEFAULT_DEMUCS_PYTHON = ""
DEFAULT_DEMUCS_TIMEOUT_S = 1800
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_ANALYZE_LANGUAGE = "en"
DEFAULT_OLLAMA_TEMPERATURE = 0.3
DEFAULT_OLLAMA_TIMEOUT_S = 600
DEFAULT_MAX_CONCURRENT_JOBS = 1
DEFAULT_VALIDATE_OVERLAP_TOLERANCE_S = 0.05
DEFAULT_HARDWARE_PROFILE = "auto"
DEFAULT_HARDWARE_Z13 = {
    "demix_device": "directml",
    "demix_compute": "float16",
    "demix_segment": 4,
    "demix_jobs": 1,
    "transcribe_device": "cpu",
    "transcribe_compute": "int8",
    "transcribe_beam_size": 1,
    "transcribe_vad": False,
    "align_device": "directml",
    "align_batch_size": 16,
    "ollama_model": "gemma4:27b",
    "ollama_num_ctx": 4096,
    "ollama_num_thread": 6,
    "ffmpeg_vcodec": "h264_amf",
    "ffmpeg_quality": 23,
}
DEFAULT_HARDWARE_CPU_ONLY = {
    "demix_device": "cpu",
    "demix_compute": "float32",
    "demix_segment": 8,
    "demix_jobs": 2,
    "transcribe_device": "cpu",
    "transcribe_compute": "int8",
    "transcribe_beam_size": 1,
    "transcribe_vad": False,
    "align_device": "cpu",
    "align_batch_size": 8,
    "ollama_model": "gemma4:27b",
    "ollama_num_ctx": 2048,
    "ollama_num_thread": 8,
    "ffmpeg_vcodec": "libx264",
    "ffmpeg_quality": 23,
}


@dataclass(frozen=True)
class AppConfig:
    jobs_dir: Path
    log_level: str
    server_host: str
    server_port: int
    secret_key: str
    max_upload_bytes: int
    default_style_preset_id: str
    generate_style_preset_id: str
    generate_resolution: str
    generate_fade_in_ms: int
    generate_fade_out_ms: int
    output_audio_codec: str
    output_audio_bitrate: str
    output_vocals_volume: float
    output_instrumental_volume: float
    output_framerate: str
    output_ffmpeg_timeout_s: int
    transcribe_model_size: str
    transcribe_language: str
    transcribe_low_confidence_threshold: float
    align_hubertfa_dir: Path
    align_checkpoint: Path
    align_language: str
    align_hubertfa_timeout_s: int
    demucs_model: str
    demucs_python: str
    demucs_timeout_s: int
    ollama_url: str
    analyze_language: str
    ollama_temperature: float
    ollama_timeout_s: int
    max_concurrent_jobs: int
    validate_overlap_tolerance_s: float
    s01_ffprobe_timeout_s: int
    s01_ffmpeg_timeout_s: int
    input_ffmpeg_timeout_s: int
    generate_ass_timeout_s: int
    validate_timeout_s: int


@dataclass(frozen=True)
class HardwareDefaults:
    demix_device: str
    demix_compute: str
    demix_segment: int
    demix_jobs: int
    transcribe_device: str
    transcribe_compute: str
    transcribe_beam_size: int
    transcribe_vad: bool
    align_device: str
    align_batch_size: int
    ollama_model: str
    ollama_num_ctx: int
    ollama_num_thread: int
    ffmpeg_vcodec: str
    ffmpeg_quality: int


@dataclass(frozen=True)
class HardwareConfig:
    profile: str
    z13: HardwareDefaults
    cpu_only: HardwareDefaults


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return data if isinstance(data, dict) else {}


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def _env_or_value(name: str, value: Any, default: Any) -> Any:
    env_value = os.environ.get(name)
    if env_value not in {None, ""}:
        return env_value
    if value not in {None, ""}:
        return value
    return default


def _int_env_or_value(name: str, value: Any, default: int) -> int:
    raw = _env_or_value(name, value, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _float_env_or_value(name: str, value: Any, default: float) -> float:
    raw = _env_or_value(name, value, default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _hardware_defaults(section: dict[str, Any], defaults: dict[str, Any]) -> HardwareDefaults:
    return HardwareDefaults(
        demix_device=str(section.get("demix_device", defaults["demix_device"])),
        demix_compute=str(section.get("demix_compute", defaults["demix_compute"])),
        demix_segment=int(section.get("demix_segment", defaults["demix_segment"])),
        demix_jobs=int(section.get("demix_jobs", defaults["demix_jobs"])),
        transcribe_device=str(section.get("transcribe_device", defaults["transcribe_device"])),
        transcribe_compute=str(section.get("transcribe_compute", defaults["transcribe_compute"])),
        transcribe_beam_size=int(section.get("transcribe_beam_size", defaults["transcribe_beam_size"])),
        transcribe_vad=_bool_value(section.get("transcribe_vad"), bool(defaults["transcribe_vad"])),
        align_device=str(section.get("align_device", defaults["align_device"])),
        align_batch_size=int(section.get("align_batch_size", defaults["align_batch_size"])),
        ollama_model=str(section.get("ollama_model", defaults["ollama_model"])),
        ollama_num_ctx=int(section.get("ollama_num_ctx", defaults["ollama_num_ctx"])),
        ollama_num_thread=int(section.get("ollama_num_thread", defaults["ollama_num_thread"])),
        ffmpeg_vcodec=str(section.get("ffmpeg_vcodec", defaults["ffmpeg_vcodec"])),
        ffmpeg_quality=int(section.get("ffmpeg_quality", defaults["ffmpeg_quality"])),
    )


def load_hardware_config(path: Path | str = DEFAULT_PIPELINE_CONFIG) -> HardwareConfig:
    config_path = Path(path)
    data = _read_toml(config_path)
    hardware = _section(data, "hardware")
    profile = str(
        _env_or_value(
            "KARAOKE_HARDWARE_PROFILE",
            hardware.get("profile"),
            DEFAULT_HARDWARE_PROFILE,
        )
    )
    return HardwareConfig(
        profile=profile,
        z13=_hardware_defaults(_section(hardware, "z13"), DEFAULT_HARDWARE_Z13),
        cpu_only=_hardware_defaults(_section(hardware, "cpu_only"), DEFAULT_HARDWARE_CPU_ONLY),
    )


def load_app_config(path: Path | str = DEFAULT_PIPELINE_CONFIG) -> AppConfig:
    config_path = Path(path)
    data = _read_toml(config_path)
    general = _section(data, "general")
    server = _section(data, "server")
    ui = _section(data, "ui")
    generate = _section(data, "generate")
    output = _section(data, "output")
    transcribe = _section(data, "transcribe")
    align = _section(data, "align")
    demix = _section(data, "demix")
    analyze = _section(data, "analyze")
    input_cfg = _section(data, "input")

    max_upload_mb = _int_env_or_value(
        "KARAOKE_MAX_UPLOAD_MB",
        server.get("max_upload_mb"),
        DEFAULT_MAX_UPLOAD_MB,
    )
    return AppConfig(
        jobs_dir=Path(_env_or_value("KARAOKE_JOBS_DIR", general.get("jobs_dir"), DEFAULT_JOBS_DIR)),
        log_level=str(_env_or_value("KARAOKE_LOG_LEVEL", general.get("log_level"), DEFAULT_LOG_LEVEL)),
        server_host=str(_env_or_value("KARAOKE_SERVER_HOST", server.get("host"), DEFAULT_SERVER_HOST)),
        server_port=_int_env_or_value("KARAOKE_SERVER_PORT", server.get("port"), DEFAULT_SERVER_PORT),
        secret_key=str(_env_or_value("KARAOKE_SECRET_KEY", server.get("secret_key"), DEFAULT_SECRET_KEY)),
        max_upload_bytes=max(1, max_upload_mb) * 1024 * 1024,
        default_style_preset_id=str(
            _env_or_value(
                "KARAOKE_DEFAULT_STYLE_PRESET",
                ui.get("default_style_preset"),
                DEFAULT_STYLE_PRESET_ID,
            )
        ),
        generate_style_preset_id=str(
            _env_or_value(
                "KARAOKE_GENERATE_STYLE_PRESET",
                generate.get("style_preset"),
                DEFAULT_GENERATE_STYLE_PRESET_ID,
            )
        ),
        generate_resolution=str(
            _env_or_value(
                "KARAOKE_GENERATE_RESOLUTION",
                generate.get("resolution"),
                DEFAULT_GENERATE_RESOLUTION,
            )
        ),
        generate_fade_in_ms=_int_env_or_value(
            "KARAOKE_GENERATE_FADE_IN_MS",
            generate.get("fade_in_ms"),
            DEFAULT_GENERATE_FADE_IN_MS,
        ),
        generate_fade_out_ms=_int_env_or_value(
            "KARAOKE_GENERATE_FADE_OUT_MS",
            generate.get("fade_out_ms"),
            DEFAULT_GENERATE_FADE_OUT_MS,
        ),
        output_audio_codec=str(
            _env_or_value(
                "KARAOKE_OUTPUT_AUDIO_CODEC",
                output.get("audio_codec"),
                DEFAULT_OUTPUT_AUDIO_CODEC,
            )
        ),
        output_audio_bitrate=str(
            _env_or_value(
                "KARAOKE_OUTPUT_AUDIO_BITRATE",
                output.get("audio_bitrate"),
                DEFAULT_OUTPUT_AUDIO_BITRATE,
            )
        ),
        output_vocals_volume=_float_env_or_value(
            "KARAOKE_OUTPUT_VOCALS_VOLUME",
            output.get("vocals_volume"),
            DEFAULT_OUTPUT_VOCALS_VOLUME,
        ),
        output_instrumental_volume=_float_env_or_value(
            "KARAOKE_OUTPUT_INSTRUMENTAL_VOLUME",
            output.get("instrumental_volume"),
            DEFAULT_OUTPUT_INSTRUMENTAL_VOLUME,
        ),
        output_framerate=str(
            _env_or_value(
                "KARAOKE_OUTPUT_FRAMERATE",
                output.get("framerate"),
                DEFAULT_OUTPUT_FRAMERATE,
            )
        ),
        output_ffmpeg_timeout_s=_int_env_or_value(
            "KARAOKE_OUTPUT_FFMPEG_TIMEOUT_S",
            output.get("ffmpeg_timeout_s"),
            DEFAULT_OUTPUT_FFMPEG_TIMEOUT_S,
        ),
        transcribe_model_size=str(
            _env_or_value(
                "KARAOKE_TRANSCRIBE_MODEL_SIZE",
                transcribe.get("model_size"),
                DEFAULT_TRANSCRIBE_MODEL_SIZE,
            )
        ),
        transcribe_language=str(
            _env_or_value(
                "KARAOKE_TRANSCRIBE_LANGUAGE",
                transcribe.get("language"),
                DEFAULT_TRANSCRIBE_LANGUAGE,
            )
        ),
        transcribe_low_confidence_threshold=_float_env_or_value(
            "KARAOKE_TRANSCRIBE_LOW_CONFIDENCE_THRESHOLD",
            transcribe.get("low_confidence_threshold"),
            DEFAULT_TRANSCRIBE_LOW_CONFIDENCE_THRESHOLD,
        ),
        align_hubertfa_dir=Path(
            _env_or_value(
                "KARAOKE_ALIGN_HUBERTFA_DIR",
                align.get("hubertfa_dir"),
                DEFAULT_ALIGN_HUBERTFA_DIR,
            )
        ),
        align_checkpoint=Path(
            _env_or_value(
                "KARAOKE_ALIGN_CHECKPOINT",
                align.get("checkpoint"),
                DEFAULT_ALIGN_CHECKPOINT,
            )
        ),
        align_language=str(
            _env_or_value(
                "KARAOKE_ALIGN_LANGUAGE",
                align.get("language"),
                DEFAULT_ALIGN_LANGUAGE,
            )
        ),
        align_hubertfa_timeout_s=_int_env_or_value(
            "KARAOKE_ALIGN_HUBERTFA_TIMEOUT_S",
            align.get("hubertfa_timeout_s"),
            DEFAULT_ALIGN_HUBERTFA_TIMEOUT_S,
        ),
        demucs_model=str(_env_or_value("KARAOKE_DEMUCS_MODEL", demix.get("model"), DEFAULT_DEMUCS_MODEL)),
        demucs_python=str(
            _env_or_value(
                "KARAOKE_DEMUCS_PYTHON",
                demix.get("python"),
                DEFAULT_DEMUCS_PYTHON,
            )
        ),
        demucs_timeout_s=_int_env_or_value(
            "KARAOKE_DEMUCS_TIMEOUT_S",
            demix.get("timeout_s"),
            DEFAULT_DEMUCS_TIMEOUT_S,
        ),
        ollama_url=str(_env_or_value("KARAOKE_OLLAMA_URL", analyze.get("ollama_url"), DEFAULT_OLLAMA_URL)),
        analyze_language=str(
            _env_or_value(
                "KARAOKE_ANALYZE_LANGUAGE",
                analyze.get("language"),
                DEFAULT_ANALYZE_LANGUAGE,
            )
        ),
        ollama_temperature=_float_env_or_value(
            "KARAOKE_OLLAMA_TEMPERATURE",
            analyze.get("temperature"),
            DEFAULT_OLLAMA_TEMPERATURE,
        ),
        ollama_timeout_s=_int_env_or_value(
            "KARAOKE_OLLAMA_TIMEOUT_S",
            analyze.get("timeout_s"),
            DEFAULT_OLLAMA_TIMEOUT_S,
        ),
        max_concurrent_jobs=_int_env_or_value(
            "KARAOKE_MAX_CONCURRENT_JOBS",
            server.get("max_concurrent_jobs"),
            DEFAULT_MAX_CONCURRENT_JOBS,
        ),
        validate_overlap_tolerance_s=_float_env_or_value(
            "KARAOKE_VALIDATE_OVERLAP_TOLERANCE_S",
            align.get("overlap_tolerance_s"),
            DEFAULT_VALIDATE_OVERLAP_TOLERANCE_S,
        ),
        s01_ffprobe_timeout_s=_int_env_or_value(
            "KARAOKE_S01_FFPROBE_TIMEOUT_S",
            input_cfg.get("ffprobe_timeout_s"),
            DEFAULT_S01_FFPROBE_TIMEOUT_S,
        ),
        s01_ffmpeg_timeout_s=_int_env_or_value(
            "KARAOKE_S01_FFMPEG_TIMEOUT_S",
            input_cfg.get("ffmpeg_timeout_s"),
            DEFAULT_S01_FFMPEG_TIMEOUT_S,
        ),
        input_ffmpeg_timeout_s=_int_env_or_value(
            "KARAOKE_INPUT_FFMPEG_TIMEOUT_S",
            server.get("input_ffmpeg_timeout_s"),
            DEFAULT_INPUT_FFMPEG_TIMEOUT_S,
        ),
        generate_ass_timeout_s=_int_env_or_value(
            "KARAOKE_GENERATE_ASS_TIMEOUT_S",
            output.get("generate_ass_timeout_s"),
            DEFAULT_GENERATE_ASS_TIMEOUT_S,
        ),
        validate_timeout_s=_int_env_or_value(
            "KARAOKE_VALIDATE_TIMEOUT_S",
            output.get("validate_timeout_s"),
            DEFAULT_VALIDATE_TIMEOUT_S,
        ),
    )
