#!/bin/bash
# 建立 macOS .app — 雙擊即用，首次自動安裝

APP_NAME="會議記錄"
APP_PATH="$HOME/Desktop/${APP_NAME}.app"
PROJECT="$HOME/projects/meeting-minutes"

cat > /tmp/meeting_minutes.applescript << APPLESCRIPT
set projectDir to "$PROJECT"

set pidFile to "/tmp/meeting-minutes.pid"
set logFile to "/tmp/meeting-minutes-server.log"
set venvDir to projectDir & "/.venv"
set installLog to "/tmp/meeting-minutes-install.log"

-- ===== 首次安裝 =====
set needsInstall to false
try
  do shell script "test -d " & quoted form of venvDir
on error
  set needsInstall to true
end try

if needsInstall then
  display dialog "首次使用，需要安裝必要元件（約 2-3 分鐘）。" & return & return & "過程中會自動安裝：" & return & "  • Homebrew（如尚未安裝）" & return & "  • Python" & return & "  • ffmpeg" & return & "  • 相關套件" buttons {"開始安裝"} default button 1 with title "會議記錄" with icon note

  -- 用 Terminal 執行安裝，讓使用者看到進度
  set installScript to quoted form of (projectDir & "/install.sh")
  tell application "Terminal"
    activate
    set installTab to do script "bash " & installScript & " 2>&1 | tee " & installLog & "; echo ''; echo '=== 安裝完成！可以關閉此視窗 ==='; echo '正在啟動會議記錄...'"
  end tell

  -- 等待 venv 建立完成（最多 5 分鐘）
  set maxWait to 300
  set waited to 0
  repeat while waited < maxWait
    try
      do shell script "test -f " & quoted form of (venvDir & "/bin/python")
      -- 再等幾秒讓 pip install 跑完
      delay 5
      try
        do shell script "test -f " & quoted form of (venvDir & "/bin/flask")
        exit repeat
      end try
    end try
    delay 2
    set waited to waited + 2
  end repeat

  if waited ≥ maxWait then
    display dialog "安裝似乎失敗了，請查看 Terminal 視窗中的錯誤訊息。" buttons {"確定"} default button 1 with title "會議記錄" with icon stop
    return
  end if
end if

-- ===== 自動同步更新 + 依賴檢查 =====
try
  do shell script "cd " & quoted form of projectDir & " && git pull origin main --ff-only 2>/dev/null && " & quoted form of (venvDir & "/bin/pip") & " install -q -r requirements.txt 2>/dev/null"
end try

-- ===== 啟動伺服器 =====
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

  -- 等待伺服器就緒（最多 15 秒）
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

# 換圖示
ICON_SRC="$PROJECT/AppIcon.icns"
if [ -f "$ICON_SRC" ]; then
  cp "$ICON_SRC" "$APP_PATH/Contents/Resources/applet.icns"
  rm -f "$APP_PATH/Contents/Resources/Assets.car"
  touch "$APP_PATH"
  /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f "$APP_PATH" 2>/dev/null || true
fi

echo "建立完成：$APP_PATH"
echo "可以拖到 Dock 或保留在桌面"
