# 會議記錄

錄音 / 錄影 → Gemini AI → 結構化 Google Doc 會議記錄

## 安裝（一行指令）

```bash
git clone https://github.com/adchengzhi7/meeting-minutes.git ~/Desktop/會議記錄 && cd ~/Desktop/會議記錄 && bash install.sh
```

安裝過程會自動處理 Homebrew、Python、ffmpeg 等依賴。

> 首次安裝需要 `credentials.json`（Google OAuth 憑證），請跟管理員索取，放到 `~/Desktop/會議記錄/` 資料夾後重跑 `bash install.sh`。

## 使用方式

1. 雙擊桌面上的「會議記錄.app」
2. 首次使用：在設定頁填入 Gemini API Key
3. 選擇 Google Drive 儲存資料夾
4. 上傳錄音/錄影，等待處理完成

首次使用會跳出 Google 帳號授權視窗（一次性），授權後自動續用。

## 取得 Gemini API Key

免費取得：https://aistudio.google.com/apikey

## 支援格式

| 類型 | 格式 |
|------|------|
| 影片 | mp4, mkv, mov, avi, webm |
| 音訊 | m4a, mp3, wav, ogg, flac, aac, wma |

## 更新

App 每次啟動時會自動同步最新版本。也可以手動更新：

```bash
cd ~/Desktop/會議記錄 && git pull
```

## 開發者

如需修改程式碼後推送更新：

```bash
cd ~/Desktop/會議記錄
# 修改程式碼...
git add -A && git commit -m "feat: 說明" && git push
```

所有使用者下次開啟 App 時會自動同步。
