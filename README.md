# 會議記錄自動化工具

錄影/錄音 → Gemini 2.5 Flash → 結構化會議記錄 → Google Doc

## 快速開始

```bash
cd ~/projects/meeting-minutes
bash install.sh
```

接著填入 `.env` 的 API keys 並放入 `credentials.json`。

## 使用方式

### 手動處理

```bash
source .venv/bin/activate
python process_meeting.py ~/Downloads/meeting.mp4
```

### 自動監控（丟入即處理）

```bash
# 把檔案丟進 ~/MeetingDrop/
cp meeting.mp4 ~/MeetingDrop/
# 完成後會收到 macOS 通知並自動開啟 Google Doc
```

### 背景服務（開機自啟）

```bash
cp com.meeting-minutes.watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.meeting-minutes.watcher.plist
```

### Shell Alias（推薦）

在 `~/.zshrc` 加入：

```bash
alias meeting="cd ~/projects/meeting-minutes && source .venv/bin/activate && python process_meeting.py"
```

然後：

```bash
meeting ~/Downloads/meeting.mp4
```

## 支援格式

影片：`.mp4` `.mkv` `.mov` `.avi` `.webm`
音訊：`.m4a` `.mp3` `.wav` `.ogg` `.flac` `.aac` `.wma`

## 前置需求

1. **Gemini API Key** — https://aistudio.google.com/apikey
2. **GCP OAuth credentials.json**：
   - GCP Console → APIs & Services → Credentials
   - 建立 OAuth 2.0 Client ID（Desktop Application）
   - 下載 JSON → 存為 `credentials.json`
3. **啟用 GCP APIs**：Generative Language API、Google Docs API、Google Drive API
4. **ffmpeg**：`brew install ffmpeg`
