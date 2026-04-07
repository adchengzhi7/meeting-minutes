#!/usr/bin/env python3
"""
監控 ~/MeetingDrop 資料夾，有新檔案就自動處理
"""

import os
import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from dotenv import load_dotenv

load_dotenv()

from process_meeting import process_file, SUPPORTED_FORMATS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

WATCH_FOLDER = Path(os.getenv("WATCH_FOLDER", "~/MeetingDrop")).expanduser()


class MeetingFileHandler(FileSystemEventHandler):
    """偵測新增的會議檔案"""

    def __init__(self):
        self.processing = set()

    def on_created(self, event):
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # 忽略隱藏檔、暫存檔
        if file_path.name.startswith(".") or file_path.name.startswith("~"):
            return

        # 忽略 processed 子資料夾
        if "processed" in file_path.parts:
            return

        # 檢查格式
        if file_path.suffix.lower() not in SUPPORTED_FORMATS:
            return

        # 避免重複處理
        if str(file_path) in self.processing:
            return

        self.processing.add(str(file_path))

        # 等待檔案寫入完成
        logger.info(f"偵測到新檔案：{file_path.name}，等待寫入完成...")
        self._wait_for_file_complete(file_path)

        try:
            logger.info(f"開始處理：{file_path.name}")
            process_file(str(file_path))
        except Exception as e:
            logger.error(f"處理失敗：{file_path.name} — {e}")
        finally:
            self.processing.discard(str(file_path))

    def _wait_for_file_complete(self, file_path: Path, timeout: int = 300):
        """等待檔案寫入完成（檔案大小不再變化）"""
        prev_size = -1
        stable_count = 0

        for _ in range(timeout):
            try:
                current_size = file_path.stat().st_size
            except FileNotFoundError:
                return

            if current_size == prev_size and current_size > 0:
                stable_count += 1
                if stable_count >= 3:  # 連續 3 秒大小不變
                    return
            else:
                stable_count = 0

            prev_size = current_size
            time.sleep(1)


def main():
    WATCH_FOLDER.mkdir(parents=True, exist_ok=True)

    logger.info(f"開始監控資料夾：{WATCH_FOLDER}")
    logger.info(f"支援格式：{', '.join(sorted(SUPPORTED_FORMATS))}")
    logger.info(f"丟入檔案即自動處理")

    handler = MeetingFileHandler()
    observer = Observer()
    observer.schedule(handler, str(WATCH_FOLDER), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logger.info("停止監控")

    observer.join()


if __name__ == "__main__":
    main()
