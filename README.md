# 會議記錄

錄音 / 錄影 → Gemini AI → 結構化 Google Doc 會議記錄

## 安裝步驟

### Step 1：打開終端機

按 `Command + 空白鍵`，輸入 `Terminal`，按 Enter 打開。

### Step 2：貼上安裝指令

複製下面這整行，貼到終端機，按 Enter：

```bash
xcode-select --install 2>/dev/null; git clone https://github.com/adchengzhi7/meeting-minutes.git ~/Desktop/會議記錄 && cd ~/Desktop/會議記錄 && bash install.sh
```

> 如果跳出「安裝 Xcode」的視窗，點「安裝」，等它完成後（約 5-10 分鐘），**再貼一次上面的指令**。

> 安裝過程需要輸入**電腦密碼**（輸入時畫面不會顯示，正常的），輸完按 Enter。

### Step 3：放入 credentials.json

安裝完會提示「缺少 credentials.json」，這是正常的。

1. 跟管理員（Alex）索取 `credentials.json` 檔案
2. 把檔案拖到桌面的「會議記錄」資料夾裡
3. 回到終端機，再執行一次：

```bash
cd ~/Desktop/會議記錄 && bash install.sh
```

看到「安裝完成」就 OK 了！桌面會出現「會議記錄.app」。

### Step 4：取得 Gemini API Key

1. 打開 https://aistudio.google.com/apikey
2. 用 Google 帳號登入
3. 點「Create API Key」，複製產生的 Key
4. 等等在 App 設定頁貼上

## 使用方式

1. 雙擊桌面上的「會議記錄.app」
2. 第一次開啟：到「設定」分頁，貼上 Gemini API Key
3. 點「選擇資料夾」，選擇要儲存會議記錄的 Google Drive 資料夾
4. 切到「上傳處理」分頁，拖入錄音/錄影檔案
5. 等待處理完成，點「開啟 Google Doc」查看結果

> 第一次上傳時會跳出 Google 帳號授權視窗，選擇你的帳號並允許權限（一次性）。

## 支援格式

| 類型 | 格式 |
|------|------|
| 影片 | mp4, mkv, mov, avi, webm |
| 音訊 | m4a, mp3, wav, ogg, flac, aac, wma |

## 更新

App 每次啟動時會自動同步最新版本，不需要手動操作。

## 常見問題

**Q：雙擊 .app 沒反應？**
打開終端機執行：
```bash
xattr -cr ~/Desktop/會議記錄.app
```
再雙擊一次。

**Q：出現「無法連上網路」？**
在瀏覽器手動打開 http://127.0.0.1:5566

**Q：Google 授權畫面顯示「這個應用程式未經驗證」？**
點「進階」→「前往（不安全）」，這是正常的（測試模式）。

**Q：處理失敗？**
確認 Gemini API Key 有正確填入，並檢查檔案格式是否支援。
