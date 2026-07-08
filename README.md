# 每日科技精选

自动抓取以下数据源，生成暗色 HTML 卡片并推送到 PushPlus：

- **arXiv AI 论文**：抓取 `cs.AI` / `cs.CL` / `cs.LG` / `cs.CV` 最新论文
- **知乎科技热榜**：筛选科技相关话题
- **B站科技热门**：科学科技区 Top10 视频

## 使用

1. Fork 或 clone 本仓库
2. 在 `Settings -> Secrets and variables -> Actions` 中添加：
   - `PUSHPLUS_TOKEN`
   - `AI_API_KEY`
   - `AI_BASE_URL`
   - `AI_MODEL`
3. 工作流每天 UTC 00:00（北京时间 08:00）自动运行
