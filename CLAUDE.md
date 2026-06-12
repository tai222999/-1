# 專案指引

## Superpowers 技能框架
每次對話開始時，**必須**調用 `superpowers:using-superpowers` 技能，以確保正確使用所有技能工作流程。

- 收到任何任務前，先檢查是否有適用的技能（即使只有 1% 機率也要調用）
- 開始寫程式前先執行 `superpowers:brainstorming`
- 除錯問題時使用 `superpowers:systematic-debugging`
- 新功能開發使用 `superpowers:test-driven-development`
- 技能調用優先於任何回應或行動

## 語言
所有回應一律使用**繁體中文**。

## 自動推送
每次完成程式碼修改後，**自動 commit 並推送到 GitHub（main 分支）**，不需要詢問。
- commit 訊息使用繁體中文描述本次變更內容
- 只 stage 有意義的程式碼檔案，排除 `__pycache__`、`data/`、`.env`、`.claude/`
