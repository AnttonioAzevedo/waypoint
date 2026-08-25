import base64
from dataclasses import dataclass

import mss
import mss.tools


@dataclass
class ScreenshotResult:
    screen_index: int
    media_type: str
    base64_data: str


def capture_all_screens() -> list[ScreenshotResult]:
    """mss.monitors[0] is the "all monitors combined" virtual screen -
    skipped. Enumeration starts at 1, matching CompanionScreenCaptureUtility.swift's
    per-display labeling (spec Component 4)."""
    results: list[ScreenshotResult] = []
    with mss.mss() as sct:
        for index, monitor in enumerate(sct.monitors[1:], start=1):
            shot = sct.grab(monitor)
            png_bytes = mss.tools.to_png(shot.rgb, shot.size)
            results.append(
                ScreenshotResult(
                    screen_index=index,
                    media_type="image/png",
                    base64_data=base64.b64encode(png_bytes).decode("ascii"),
                )
            )
    return results
