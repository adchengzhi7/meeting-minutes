#!/bin/bash
set -e

# 打包會議記錄工具
# 對方：解壓 → 雙擊 install.command → 自動安裝 + 桌面出現 .app

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PKG_NAME="會議記錄"
PKG_DIR="/tmp/$PKG_NAME"
OUTPUT="$HOME/Desktop/${PKG_NAME}.zip"

echo "=== 打包會議記錄工具 ==="

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR"

# 複製必要檔案
INCLUDE_FILES=(
    app.py
    process_meeting.py
    watch_folder.py
    generate_icon.py
    build_app.sh
    install.sh
    start_ui.sh
    requirements.txt
    prompt.md
    credentials.json
    AppIcon.icns
)

for f in "${INCLUDE_FILES[@]}"; do
    if [ -f "$PROJECT_DIR/$f" ]; then
        cp "$PROJECT_DIR/$f" "$PKG_DIR/"
    else
        echo "警告：$f 不存在，跳過"
    fi
done

cp -r "$PROJECT_DIR/templates" "$PKG_DIR/templates"
mkdir -p "$PKG_DIR/output"

# 建立雙擊即可執行的 .command 檔（替代 Terminal 指令）
cat > "$PKG_DIR/安裝.command" << 'CMD'
#!/bin/bash
cd "$(dirname "$0")"
bash install.sh
CMD
chmod +x "$PKG_DIR/安裝.command"
chmod +x "$PKG_DIR/install.sh"

# 打包
cd /tmp
rm -f "$OUTPUT"
zip -r "$OUTPUT" "$PKG_NAME" -x "*.pyc" "*__pycache__*" "*.DS_Store"
rm -rf "$PKG_DIR"

SIZE=$(du -h "$OUTPUT" | awk '{print $1}')
echo ""
echo "打包完成：$OUTPUT ($SIZE)"
echo ""
echo "對方使用方式："
echo "  1. 解壓 zip"
echo "  2. 雙擊「安裝.command」"
echo "  3. 安裝完成後桌面出現「會議記錄.app」"
echo "  4. 之後每次雙擊 .app 直接開啟"
