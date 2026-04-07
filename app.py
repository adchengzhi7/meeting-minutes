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

ARCHIVE_FOLDER = Path(os.getenv("ARCHIVE_FOLDER", "~/Desktop/MeetingDrop/processed")).expanduser()

# job_id → list of subscriber queues (broadcast to all)
_job_subscribers: dict[str, list[queue.Queue]] = {}
_job_logs: dict[str, list] = {}  # job_id → all log messages (for reconnect replay)
_job_results: dict[str, dict] = {}
_job_meta: dict[str, dict] = {}  # job_id → {filename, started_at}

# 資料夾監控
_watcher_thread = None
_watcher_observer = None

# 監控處理進度
def _load_watch_history() -> list:
    """從檔案載入監控處理記錄"""
    path = PROJECT_DIR / "watch_history.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return []


def _save_watch_history(history: list):
    """儲存監控處理記錄到檔案"""
    path = PROJECT_DIR / "watch_history.json"
    path.write_text(json.dumps(history[-100:], ensure_ascii=False, indent=2))


_watch_progress = {
    "active": False,
    "filename": "",
    "step": "",
    "started_at": None,
    "logs": [],
    "queue": [],  # 排隊中的檔案名稱
    "history": _load_watch_history(),
}
_watch_queue = queue.Queue()  # 檔案處理佇列


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


@app.route("/drive/create-folder", methods=["POST"])
def drive_create_folder():
    """在 Google Drive 建立新資料夾"""
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "缺少資料夾名稱"}), 400

    try:
        from process_meeting import get_google_creds
        from googleapiclient.discovery import build as gapi_build

        creds = get_google_creds()
        drive = gapi_build("drive", "v3", credentials=creds)

        parent = data.get("parent", "root")
        file_metadata = {
            "name": data["name"],
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent and parent != "root":
            file_metadata["parents"] = [parent]

        folder = drive.files().create(body=file_metadata, fields="id, name").execute()
        return jsonify({"id": folder["id"], "name": folder["name"]})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/upload", methods=["POST"])
def upload():
    """支援多檔批次上傳，回傳所有 job_id"""
    files = request.files.getlist("file")
    if not files or not files[0].filename:
        return jsonify({"error": "沒有檔案"}), 400

    jobs = []
    for file in files:
        if not file.filename:
            continue
        job_id = str(uuid.uuid4())
        save_path = UPLOAD_FOLDER / f"{job_id}_{file.filename}"
        file.save(str(save_path))

        _job_subscribers[job_id] = []
        _job_logs[job_id] = []
        _job_results[job_id] = {"status": "queued", "doc_url": None, "error": None}
        _job_meta[job_id] = {"filename": file.filename, "started_at": None}
        jobs.append({"job_id": job_id, "filename": file.filename, "path": str(save_path)})

    # 依序處理（排隊）
    def _run_batch(batch):
        for item in batch:
            jid = item["job_id"]
            _job_results[jid]["status"] = "processing"
            _job_meta[jid]["started_at"] = datetime.now().isoformat()
            _run_job(jid, item["path"])

    thread = threading.Thread(target=_run_batch, args=(jobs,), daemon=True)
    thread.start()

    # 單檔回傳保持向下相容
    if len(jobs) == 1:
        return jsonify({"job_id": jobs[0]["job_id"]})
    return jsonify({"jobs": [{"job_id": j["job_id"], "filename": j["filename"]} for j in jobs]})


@app.route("/jobs/active")
def active_jobs():
    """回傳目前進行中的 job（讓刷新後可以接回）"""
    active = []
    for job_id, result in _job_results.items():
        if result["status"] == "processing":
            meta = _job_meta.get(job_id, {})
            active.append({
                "job_id": job_id,
                "filename": meta.get("filename", ""),
                "started_at": meta.get("started_at", ""),
            })
    return jsonify(active)


@app.route("/stream/<job_id>")
def stream(job_id):
    """SSE endpoint：即時 log 串流（支援刷新後重新連線）"""
    # 如果 job 已完成，直接回傳結果
    result = _job_results.get(job_id)
    if result and result["status"] != "processing":
        def done_immediately():
            yield f"data: {json.dumps({'type': 'done', **result})}\n\n"
        return Response(
            stream_with_context(done_immediately()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if job_id not in _job_subscribers:
        return jsonify({"error": "找不到 job"}), 404

    def generate():
        # 回放已有的 log（給刷新後重連的客戶端）
        for msg in list(_job_logs.get(job_id, [])):
            yield f"data: {json.dumps({'type': 'log', 'message': msg})}\n\n"

        # 建立新的訂閱者 queue 接收後續訊息
        q = queue.Queue()
        subs = _job_subscribers.get(job_id)
        if subs is not None:
            subs.append(q)
        try:
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
        finally:
            # 斷線時移除訂閱者
            if subs is not None and q in subs:
                subs.remove(q)

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
    allowed = {"GEMINI_API_KEY", "GDRIVE_FOLDER_ID", "WATCH_FOLDER", "ARCHIVE_FOLDER", "MAX_OUTPUT_TOKENS", "OUTPUT_LANGUAGE"}
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


PROMPT_TEMPLATES = {
    "standard": {
        "name": "標準會議記錄",
        "content": """你是一個專業的會議記錄助理，請根據這段會議錄音，產出結構化的會議記錄。

**重要：輸出的第一行必須是會議主題摘要標題（10-20 字），不帶任何 Markdown 標記，獨立一行。**

## 輸出格式（繁體中文）

### 會議概覽

| 項目 | 內容 |
|------|------|
| 日期 | （從對話推測或標記「待確認」） |
| 參與者 | （Speaker 1/2/3 + 推測身份） |
| 時長 | （大約） |

### 重點摘要
用 3-5 個重點條列，每項一句話，用 **粗體** 標示關鍵詞。

### 議題與討論
依照討論順序分成多個議題區塊：

#### 議題 N：[標題]
**背景**：為什麼討論這個議題
**討論要點**：
- **[Speaker X]**：觀點摘要
- **[Speaker Y]**：觀點摘要
**結論**：最終決定或「尚未定案」

---

### 決議事項
| # | 決議內容 | 相關議題 |
|---|---------|---------|

### 待辦事項
| # | 待辦事項 | 負責人 | 期限 | 優先度 |
|---|---------|--------|------|--------|

### 延伸備註
- 未深入討論的話題
- 需要後續追蹤的事項

## 規則
1. 只根據錄音內容記錄，不腦補
2. 沒有結論標註「尚未定案」
3. 負責人不確定標註「待確認」
4. 使用繁體中文
5. 用 **粗體** 強調關鍵決定、數字、人名
6. 議題間用 --- 分隔""",
    },
    "concise": {
        "name": "簡潔摘要",
        "content": """你是會議記錄助理。請根據錄音產出**極簡摘要**。

**第一行：會議主題標題（10-20 字），不帶 Markdown 標記。**

## 輸出格式（繁體中文）

### 關鍵結論
- 用 3-5 個 bullet points 列出最重要的決定和結論
- 每項不超過 2 句話
- 用 **粗體** 標示關鍵詞

### 待辦事項
| 待辦 | 負責人 | 期限 |
|------|--------|------|

### 備註
- 其他值得記錄的重點（1-3 項）

## 規則
1. 越精簡越好，只保留最重要的資訊
2. 繁體中文
3. 不需要逐字稿或詳細討論過程""",
    },
    "detailed": {
        "name": "詳細逐字稿",
        "content": """你是專業的會議逐字稿整理師。請根據錄音產出詳細的會議記錄，盡可能保留原始對話內容。

**第一行：會議主題標題（10-20 字），不帶 Markdown 標記。**

## 輸出格式（繁體中文）

### 會議資訊
| 項目 | 內容 |
|------|------|
| 日期 | （推測或「待確認」） |
| 參與者 | Speaker 1/2/3 + 推測身份 |
| 時長 | 大約 |

### 詳細討論記錄

按照時間順序記錄每位發言者的內容，格式：

**[Speaker X]**：（盡量還原原始發言，保留語氣和用詞）

**[Speaker Y]**：（回應內容）

...

用 --- 分隔不同議題段落。

### 重點摘要
- 3-5 個核心結論

### 待辦事項
| # | 待辦事項 | 負責人 | 期限 |
|---|---------|--------|------|

## 規則
1. 盡量保留原始發言的語氣和措辭
2. 每位 Speaker 的發言都要記錄
3. 繁體中文
4. 如果聽不清楚標註（不清楚）""",
    },
    "english": {
        "name": "English Meeting Notes",
        "content": """You are a professional meeting notes assistant. Based on the recording, produce structured meeting notes in English.

**Important: The first line must be a meeting topic summary (10-20 words), with no Markdown formatting.**

## Output Format

### Meeting Overview
| Item | Details |
|------|---------|
| Date | (inferred or "TBD") |
| Participants | Speaker 1/2/3 + inferred roles |
| Duration | Approximately |

### Key Takeaways
- 3-5 bullet points summarizing the most important outcomes
- Use **bold** for key terms

### Discussion Topics

#### Topic N: [Title]
**Context**: Why this was discussed
**Key Points**:
- **[Speaker X]**: viewpoint summary
- **[Speaker Y]**: viewpoint summary
**Conclusion**: Final decision or "To be determined"

---

### Action Items
| # | Action Item | Owner | Deadline | Priority |
|---|------------|-------|----------|----------|

### Notes
- Topics mentioned but not discussed in depth
- Items requiring follow-up

## Rules
1. Only document what was actually said
2. Mark uncertain items as "TBD"
3. Use bold for key decisions and names""",
    },
    "action": {
        "name": "純待辦事項",
        "content": """你是會議行動清單整理師。只需要從錄音中提取所有待辦事項和決議，不需要其他內容。

**第一行：會議主題標題（10-20 字），不帶 Markdown 標記。**

## 輸出格式（繁體中文）

### 決議事項
| # | 決議內容 | 說明 |
|---|---------|------|

### 待辦事項
| # | 待辦事項 | 負責人 | 期限 | 優先度 | 備註 |
|---|---------|--------|------|--------|------|

### 需追蹤事項
- 尚未定案但需要後續追蹤的項目

## 規則
1. 專注在可執行的行動項目
2. 每個待辦事項要具體、可衡量
3. 優先度分為高/中/低
4. 繁體中文
5. 如果沒有明確的待辦事項，如實標註「本次會議無明確待辦事項」""",
    },
}


@app.route("/prompt/template/<name>")
def get_template(name):
    tmpl = PROMPT_TEMPLATES.get(name)
    if not tmpl:
        return jsonify({"error": "找不到範本"}), 404
    return jsonify(tmpl)


@app.route("/prompt/optimize", methods=["POST"])
def optimize_prompt():
    """用 Gemini 優化使用者的 Prompt"""
    data = request.get_json()
    if not data or not data.get("content"):
        return jsonify({"error": "缺少 Prompt 內容"}), 400

    try:
        from process_meeting import _ensure_gemini
        import google.generativeai as genai

        _ensure_gemini()
        model = genai.GenerativeModel("gemini-2.5-flash")

        optimize_request = f"""你是 Prompt 優化專家。請改進以下用於會議錄音轉會議記錄的 Prompt。

改進方向：
1. 讓輸出結構更清晰、更專業
2. 加強關鍵資訊的提取（決議、待辦、負責人）
3. 改善格式排版的指示
4. 保持原本的語言（中文或英文）
5. 保留「第一行必須是標題」的規則

請直接輸出改進後的 Prompt，不要加任何說明或前言。

原始 Prompt：
---
{data['content']}
---"""

        response = model.generate_content(
            optimize_request,
            generation_config=genai.GenerationConfig(temperature=0.5, max_output_tokens=4096),
        )
        return jsonify({"content": response.text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/watch", methods=["GET"])
def get_watch_status():
    """取得資料夾監控狀態 + 處理進度"""
    elapsed = None
    if _watch_progress["active"] and _watch_progress["started_at"]:
        elapsed = int((datetime.now() - _watch_progress["started_at"]).total_seconds())

    return jsonify({
        "running": _watcher_thread is not None and _watcher_thread.is_alive(),
        "folder": str(Path(os.getenv("WATCH_FOLDER", "~/Desktop/MeetingDrop")).expanduser()),
        "processing": _watch_progress["active"],
        "filename": _watch_progress["filename"],
        "step": _watch_progress["step"],
        "elapsed": elapsed,
        "logs": _watch_progress["logs"][-30:],
        "queue": list(_watch_progress["queue"]),
        "recent": _watch_progress["history"][-20:],
    })


def _wait_file_ready(fp: Path):
    """等待檔案寫入完成（大小連續 3 秒不變）"""
    import time as _time
    prev_size = -1
    stable = 0
    for _ in range(300):
        try:
            sz = fp.stat().st_size
        except FileNotFoundError:
            return False
        if sz == prev_size and sz > 0:
            stable += 1
            if stable >= 3:
                return True
        else:
            stable = 0
        prev_size = sz
        _time.sleep(1)
    return True


def _watch_worker():
    """佇列工作者：依序處理檔案，一次只處理一個"""
    while True:
        fp = _watch_queue.get()
        if fp is None:
            break

        # 從排隊列表移除
        try:
            _watch_progress["queue"].remove(fp.name)
        except ValueError:
            pass

        if not fp.exists():
            continue

        if not _wait_file_ready(fp):
            continue

        _watch_progress["active"] = True
        _watch_progress["filename"] = fp.name
        _watch_progress["step"] = "準備處理..."
        _watch_progress["started_at"] = datetime.now()
        _watch_progress["logs"] = []

        def log(msg):
            _watch_progress["step"] = msg
            _watch_progress["logs"].append(msg)

        try:
            from process_meeting import process_file
            doc_url = process_file(str(fp), auto_open=True, log=log)
            record = {
                "filename": fp.name,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "status": "done" if doc_url else "error",
                "doc_url": doc_url,
                "logs": list(_watch_progress["logs"]),
            }
            _watch_progress["history"].append(record)
            _save_watch_history(_watch_progress["history"])
        except Exception as e:
            record = {
                "filename": fp.name,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "status": "error",
                "error": str(e),
                "logs": list(_watch_progress["logs"]),
            }
            _watch_progress["history"].append(record)
            _save_watch_history(_watch_progress["history"])
        finally:
            _watch_progress["active"] = False
            _watch_progress["filename"] = ""
            _watch_progress["step"] = ""
            _watch_progress["started_at"] = None
            _watch_progress["logs"] = []


def _enqueue_file(fp: Path):
    """將檔案加入處理佇列"""
    _watch_progress["queue"].append(fp.name)
    _watch_queue.put(fp)


def _create_watcher():
    """建立並啟動資料夾監控，回傳 (observer, existing_count)"""
    global _watcher_thread, _watcher_observer
    from watch_folder import WATCH_FOLDER, SUPPORTED_FORMATS
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    WATCH_FOLDER.mkdir(parents=True, exist_ok=True)

    _seen = set()

    class QueueHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            fp = Path(event.src_path)
            if fp.name.startswith(".") or fp.name.startswith("~"):
                return
            if "processed" in fp.parts:
                return
            if fp.suffix.lower() not in SUPPORTED_FORMATS:
                return
            if str(fp) in _seen:
                return
            _seen.add(str(fp))
            _enqueue_file(fp)

    handler = QueueHandler()
    observer = Observer()
    observer.schedule(handler, str(WATCH_FOLDER), recursive=False)
    observer.daemon = True
    observer.start()
    _watcher_observer = observer
    _watcher_thread = observer

    # 啟動佇列工作者
    threading.Thread(target=_watch_worker, daemon=True).start()

    # 掃描已有的檔案
    existing = [f for f in WATCH_FOLDER.iterdir()
                 if f.is_file()
                 and not f.name.startswith(".")
                 and not f.name.startswith("~")
                 and f.suffix.lower() in SUPPORTED_FORMATS]
    for fp in existing:
        _seen.add(str(fp))
        _enqueue_file(fp)

    return WATCH_FOLDER, len(existing)


@app.route("/watch/start", methods=["POST"])
def start_watch():
    """啟動資料夾監控"""
    if _watcher_thread and _watcher_thread.is_alive():
        return jsonify({"ok": True, "message": "已在監控中"})

    try:
        folder, count = _create_watcher()
        count_msg = f"（{count} 個待處理）" if count else ""
        return jsonify({"ok": True, "message": f"開始監控 {folder}{count_msg}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/watch/stop", methods=["POST"])
def stop_watch():
    """停止資料夾監控"""
    global _watcher_thread, _watcher_observer
    if _watcher_observer:
        _watcher_observer.stop()
        _watcher_observer = None
        _watcher_thread = None
    return jsonify({"ok": True})


@app.route("/watch/open", methods=["POST"])
def open_watch_folder():
    """在 Finder 打開監控資料夾"""
    import subprocess
    folder = Path(os.getenv("WATCH_FOLDER", "~/Desktop/MeetingDrop")).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(["open", str(folder)])
    return jsonify({"ok": True})


@app.route("/import/voice-memos", methods=["POST"])
def import_voice_memos():
    """用原生檔案選擇器從 iCloud 匯入語音備忘錄到 MeetingDrop"""
    import subprocess

    watch_folder = Path(os.getenv("WATCH_FOLDER", "~/Desktop/MeetingDrop")).expanduser()
    watch_folder.mkdir(parents=True, exist_ok=True)

    script = f'''
set meetingDrop to "{watch_folder}/"
set iCloudDocs to (POSIX file ((POSIX path of (path to home folder)) & "Library/Mobile Documents/com~apple~CloudDocs/") as alias)

set chosenFiles to choose file with prompt "選擇會議錄音（可多選）" of type {{"public.audio", "public.mpeg-4", "com.apple.quicktime-movie", "public.movie"}} default location iCloudDocs with multiple selections allowed

set fileCount to 0
set fileNames to ""
repeat with f in chosenFiles
    set fPath to POSIX path of f
    set fName to name of (info for f)
    do shell script "cp " & quoted form of fPath & " " & quoted form of (meetingDrop & fName)
    set fileCount to fileCount + 1
    if fileNames is not "" then set fileNames to fileNames & ", "
    set fileNames to fileNames & fName
end repeat

return fileCount & "|" & fileNames
'''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "User canceled" in stderr or "-128" in stderr:
                return jsonify({"ok": True, "count": 0, "message": "已取消"})
            return jsonify({"error": stderr}), 500

        parts = result.stdout.strip().split("|", 1)
        count = int(parts[0])
        names = parts[1] if len(parts) > 1 else ""
        return jsonify({"ok": True, "count": count, "files": names})

    except subprocess.TimeoutExpired:
        return jsonify({"error": "操作逾時"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===== Helpers =====

def _run_job(job_id: str, file_path: str):
    def log(msg: str):
        if job_id in _job_logs:
            _job_logs[job_id].append(msg)
        for q in list(_job_subscribers.get(job_id, [])):
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
        for q in list(_job_subscribers.get(job_id, [])):
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


def _auto_start_watch():
    """伺服器啟動時自動開啟資料夾監控"""
    import time as _time
    _time.sleep(1)  # 等伺服器就緒
    try:
        if _watcher_thread and _watcher_thread.is_alive():
            return
        folder, count = _create_watcher()
        print(f"自動啟動監控：{folder}（{count} 個待處理）")
    except Exception as e:
        print(f"自動監控啟動失敗：{e}")


if __name__ == "__main__":
    print("會議記錄 UI 啟動：http://127.0.0.1:5566")
    threading.Thread(target=_auto_start_watch, daemon=True).start()
    app.run(host="0.0.0.0", port=5566, debug=False, threaded=True)
