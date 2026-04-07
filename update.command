#!/bin/bash
cd "$(dirname "$0")"
echo "=== 更新會議記錄工具 ==="
echo ""
git pull origin main 2>&1
echo ""
echo "更新完成！可以關閉此視窗。"
