#!/bin/bash
set -e

echo "=== 會議記錄工具安裝 ==="
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

# 檢查 Homebrew
if ! command -v brew &>/dev/null; then
    echo "正在安裝 Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # 載入 brew 路徑
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
fi

# 檢查 ffmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo "安裝 ffmpeg..."
    brew install ffmpeg
else
    echo "ffmpeg 已安裝"
fi

# 找到 Python 3.13（3.14 有 locale encoding bug）
PYTHON=""
for p in python3.13 python3; do
    if command -v "$p" &>/dev/null; then
        ver=$("$p" --version 2>&1 | awk '{print $2}')
        major=$(echo "$ver" | cut -d. -f1-2)
        # 跳過 3.14+（有已知問題）
        if [ "$(echo "$major < 3.14" | bc)" = "1" ]; then
            PYTHON="$(command -v "$p")"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "安裝 Python 3.13..."
    brew install python@3.13
    PYTHON="$(brew --prefix)/bin/python3.13"
fi

echo "Python：$($PYTHON --version 2>&1)"

# 建立虛擬環境
if [ ! -d "$VENV_DIR" ]; then
    echo "建立虛擬環境..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# 安裝依賴
echo "安裝 Python 依賴..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$PROJECT_DIR/requirements.txt" -q
pip install python-docx -q

# 建立 .env（如果不存在）
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cat > "$PROJECT_DIR/.env" << 'ENV'
GEMINI_API_KEY=
GDRIVE_FOLDER_ID=
WATCH_FOLDER=~/MeetingDrop
ARCHIVE_FOLDER=~/MeetingDrop/processed
ENV
    echo "已建立 .env"
fi

# 建立資料夾
mkdir -p ~/MeetingDrop/processed

# 檢查 credentials.json
if [ ! -f "$PROJECT_DIR/credentials.json" ]; then
    echo ""
    echo "========================================="
    echo "  缺少 credentials.json"
    echo "  請跟管理員（Alex）索取此檔案，"
    echo "  放到這個位置："
    echo "  $PROJECT_DIR/credentials.json"
    echo "========================================="
    echo ""
    echo "放好後，重新執行此安裝腳本即可。"
    exit 1
fi

# 建立桌面 .app
echo "建立桌面 App..."
APP_PATH="$HOME/Desktop/會議記錄.app"
rm -rf "$APP_PATH"

cat > /tmp/meeting_minutes.applescript << APPLESCRIPT
set projectDir to "$(echo "$PROJECT_DIR" | sed 's/"/\\"/g')"
set pidFile to "/tmp/meeting-minutes.pid"
set logFile to "/tmp/meeting-minutes-server.log"
set venvDir to projectDir & "/.venv"

-- 自動同步更新（靜默執行，失敗不影響使用）
try
  do shell script "cd " & quoted form of projectDir & " && git pull origin main --ff-only 2>/dev/null"
end try

-- 檢查伺服器是否正在執行
set isRunning to false
try
  set pid to do shell script "cat " & pidFile
  do shell script "kill -0 " & pid
  set isRunning to true
end try

if isRunning then
  do shell script "open http://127.0.0.1:5566"
else
  do shell script "cd " & quoted form of projectDir & " && nohup " & quoted form of (venvDir & "/bin/python") & " app.py > " & logFile & " 2>&1 & echo \$! > " & pidFile
  repeat 30 times
    try
      do shell script "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5566 | grep -q 200"
      exit repeat
    end try
    delay 0.5
  end repeat
  do shell script "open http://127.0.0.1:5566"
end if
APPLESCRIPT

osacompile -o "$APP_PATH" /tmp/meeting_minutes.applescript
rm /tmp/meeting_minutes.applescript

# 套用圖示
if [ -f "$PROJECT_DIR/AppIcon.icns" ]; then
  cp "$PROJECT_DIR/AppIcon.icns" "$APP_PATH/Contents/Resources/applet.icns"
  rm -f "$APP_PATH/Contents/Resources/Assets.car"
  touch "$APP_PATH"
  /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f "$APP_PATH" 2>/dev/null || true
fi

# 移除 macOS 隔離標記（避免「App 已損毀」警告）
xattr -cr "$APP_PATH" 2>/dev/null || true

echo ""
echo "=== 安裝完成 ==="
echo ""
echo "桌面上已建立「會議記錄.app」，雙擊即可使用。"
