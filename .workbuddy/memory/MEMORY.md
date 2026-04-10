# MEMORY.md - 长期记忆

## GitHub Pages 部署信息

- **仓库地址**：https://github.com/silenceyz525/biokb
- **永久网址**：https://silenceyz525.github.io/biokb/
- **PAT 存储位置**：`c:/Users/silen/biopharma-kb/gh_token.txt`（已被 .gitignore 排除）
- **推送脚本**：`c:/Users/silen/biopharma-kb/push-to-github.py`（采集+导出+推送一体化）

## 项目架构

- **本地服务**：`python server.py serve`（端口 8765）
- **数据采集**：`python server.py collect-fast`（增量采集）
- **数据导出**：`python server.py export`（导出到 data/articles.json）
- **前端降级**：index.html 在 API 不通时自动读取 `./data/articles.json`，适合静态托管
- **GitHub 推送**：通过 GitHub REST API（Contents API）上传，绕过 git push 网络问题

## 自动化任务

- 自动化 ID：`biokb`
- 脚本路径：`C:\Users\silen\biopharma-kb\push-to-github.py`
- 计划时间：每日 08:00
- 任务内容：采集最新数据 → 导出 JSON → 推送到 GitHub Pages

## 本地 Git 状态

- 本地有未同步 commit（git push 网络不通，需等网络恢复或依赖 push-to-github.py 推送）

更新于：2026-04-09
