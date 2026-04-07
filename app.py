#!/usr/bin/env python3
"""
會議記錄 Web UI
"""

import os
import json
import uuid
import threading
import queue
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, Response, render_template, stream_with_context, send_from_directory
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).parent.resolve()
load_dotenv(PROJECT_DIR / ".env", override=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4GB

UPLOAD_FOLDER = Path("/tmp/meeting-minutes-uploads")
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

ARCHIVE_FOLDER = Path(os.getenv("ARCHIVE_FOLDER", "~/MeetingDrop/processed")).expanduser()

# job_id → queue of log messages
_job_queues: dict[str, queue.Queue] = {}
_job_results: dict[str, dict] = {}


# ===== Routes =====

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/download/<filename>")
def download(filename):
    """下載產出的 .docx"""
    output_dir = PROJECT_DIR / "output"
    return send_from_directory(str(output_dir), filename, as_attachment=True)


@app.route("/drive/folders")
def drive_folders():
    """列出 Google Drive 資料夾，支援 parent 參數瀏覽子資料夾"""
    parent = request.args.get("parent", "root")

    try:
        from process_meeting import get_google_creds
        from googleapiclient.discovery import build as gapi_build

        creds = get_google_creds()
        drive = gapi_build("drive", "v3", credentials=creds)

        results = drive.files().list(
            q=f"'{parent}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id, name)",
            orderBy="name",
            pageSize=100,
        ).execute()

        folders = [{"id": f["id"], "name": f["name"]} for f in results.get("files", [])]

        # 如果不是 root，取得目前資料夾名稱供 breadcrumb 用
        current_name = "我的雲端硬碟"
        if parent != "root":
            try:
                f = drive.files().get(fileId=parent, fields="name").execute()
                current_name = f["name"]
            except Exception:
                pass

        return jsonify({"folders": folders, "current": current_name, "parent_id": parent})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "沒有檔案"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "檔案名稱為空"}), 400

    # 儲存上傳檔案
    job_id = str(uuid.uuid4())
    save_path = UPLOAD_FOLDER / f"{job_id}_{file.filename}"
    file.save(str(save_path))

    # 建立 job queue
    q = queue.Queue()
    _job_queues[job_id] = q
    _job_results[job_id] = {"status": "processing", "doc_url": None, "error": None}

    # 背景執行
    thread = threading.Thread(target=_run_job, args=(job_id, str(save_path)), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/stream/<job_id>")
def stream(job_id):
    """SSE endpoint：即時 log 串流"""
    if job_id not in _job_queues:
        return jsonify({"error": "找不到 job"}), 404

    def generate():
        q = _job_queues[job_id]
        while True:
            try:
                msg = q.get(timeout=30)
                if msg is None:  # sentinel：job 結束
                    result = _job_results.get(job_id, {})
                    yield f"data: {json.dumps({'type': 'done', **result})}\n\n"
                    break
                yield f"data: {json.dumps({'type': 'log', 'message': msg})}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/history")
def history():
    """列出已處理的會議記錄（從 history.json 讀取）"""
    history_path = PROJECT_DIR / "history.json"
    if not history_path.exists():
        return jsonify([])

    try:
        records = json.loads(history_path.read_text())
        return jsonify(records[:50])
    except Exception:
        return jsonify([])


@app.route("/status")
def status():
    """確認設定是否完整"""
    env = _read_env_file(PROJECT_DIR / ".env")
    issues = []

    gemini_key = env.get("GEMINI_API_KEY", "")
    if not gemini_key or gemini_key == "your_gemini_api_key_here":
        issues.append("GEMINI_API_KEY 未設定")

    folder_id = env.get("GDRIVE_FOLDER_ID", "")
    if not folder_id or folder_id == "your_google_drive_folder_id_here":
        issues.append("GDRIVE_FOLDER_ID 未設定")

    return jsonify({
        "ready": len(issues) == 0,
        "issues": issues,
    })


@app.route("/settings", methods=["GET"])
def get_settings():
    """讀取目前設定（遮罩敏感值）"""
    env_path = Path(__file__).parent / ".env"
    settings = _read_env_file(env_path)

    # 遮罩 API key（只顯示前 8 碼）
    if settings.get("GEMINI_API_KEY") and settings["GEMINI_API_KEY"] not in ("", "your_gemini_api_key_here"):
        key = settings["GEMINI_API_KEY"]
        settings["GEMINI_API_KEY"] = key[:8] + "..." if len(key) > 8 else "***"
        settings["GEMINI_API_KEY_SET"] = True
    else:
        settings["GEMINI_API_KEY_SET"] = False

    return jsonify(settings)


@app.route("/settings", methods=["POST"])
def save_settings():
    """儲存設定到 .env"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "無效的請求"}), 400

    env_path = Path(__file__).parent / ".env"
    current = _read_env_file(env_path)

    # 允許更新的欄位
    allowed = {"GEMINI_API_KEY", "GDRIVE_FOLDER_ID", "WATCH_FOLDER", "ARCHIVE_FOLDER"}
    for key in allowed:
        if key in data and data[key]:
            current[key] = data[key]

    _write_env_file(env_path, current)

    # 重新載入環境變數
    load_dotenv(override=True)

    return jsonify({"ok": True})




@app.route("/prompt", methods=["GET"])
def get_prompt():
    prompt_path = Path(__file__).parent / "prompt.md"
    content = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    return jsonify({"content": content})


@app.route("/prompt", methods=["POST"])
def save_prompt():
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "無效的請求"}), 400
    prompt_path = Path(__file__).parent / "prompt.md"
    prompt_path.write_text(data["content"], encoding="utf-8")
    return jsonify({"ok": True})


# ===== Helpers =====

def _run_job(job_id: str, file_path: str):
    q = _job_queues[job_id]

    def log(msg: str):
        q.put(msg)

    try:
        # 延遲 import，避免啟動時就需要所有設定
        from process_meeting import process_file
        doc_url = process_file(file_path, auto_open=False, log=log)

        if doc_url:
            _job_results[job_id] = {"status": "done", "doc_url": doc_url, "error": None}
        else:
            _job_results[job_id] = {"status": "error", "doc_url": None, "error": "處理失敗，請查看 log"}

    except Exception as e:
        _job_results[job_id] = {"status": "error", "doc_url": None, "error": str(e)}
        log(f"錯誤：{e}")

    finally:
        # 清理上傳的暫存檔
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception:
            pass
        q.put(None)  # sentinel


def _read_env_file(path: Path) -> dict:
    """讀取 .env 檔案為 dict"""
    result = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _write_env_file(path: Path, data: dict):
    """將 dict 寫回 .env，保留注解"""
    if not path.exists():
        lines = []
    else:
        lines = path.read_text().splitlines()

    updated_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            new_lines.append(line)
            continue
        if "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in data:
                new_lines.append(f"{key}={data[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # 新增未出現在原檔的 key
    for key, val in data.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    path.write_text("\n".join(new_lines) + "\n")


def _format_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


if __name__ == "__main__":
    print("會議記錄 UI 啟動：http://127.0.0.1:5566")
    app.run(host="0.0.0.0", port=5566, debug=False, threaded=True)
