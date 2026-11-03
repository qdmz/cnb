# 巡检定时任务体（样例）

以下为每 10 分钟运行一次的智能体巡检任务正文（部署时把路径与域名换成自己的）。
它只调用 `bin/check.sh` 与 `bin/relaunch.sh`，按输出决定静默还是上报。

---

任务：CNB 云原生开发环境（仓库 <组织/仓库>）保活巡检与自动恢复。背景：环境靠 SSH/HTTP 心跳存活（10 分钟无心跳回收、心跳最长维持 18 小时、凌晨 4–6 点不过夜强制回收，被回收是预期事件）。沙箱侧常驻 SSH 心跳连接由 bin/hold.sh 维护，目标在 target.env。项目双地址：CNB_PROJECT_URL（每环境变的 cnb.run 地址）与固定域名（环境内 cloudflared 隧道直达业务端口）。

每轮先运行 `bin/check.sh`：它会拉起丢失的心跳连接、SSH 进环境自愈（业务进程/隧道没跑就拉起）、探活两个地址、记一行日志。输出形如 `ssh_ok=1 cnbrun_http=200 fixed_http=200 ensure=[...]`。

判读与动作：
1. ssh_ok=1 且两个 http 为 2xx/3xx：正常，静默结束，只简记一行，不通知用户。
2. ssh_ok=1 但某 http 连续多轮异常（查 logs/keepalive.log 确认连续性）：报告哪个地址异常、持续几轮。
3. ssh_ok=0：再跑一次 check.sh 复核。仍为 0 则运行 `bin/relaunch.sh trigger`：
   - NOT_ARMED：报告「环境已回收但自动重开未就绪，需要人工处理」。
   - TRIGGERED：报告「已自动触发重开，正在恢复」，后续轮次接管。
   - IN_PROGRESS：改跑 `bin/relaunch.sh adopt`：ADOPTED 报告恢复成功（新地址+固定域名状态）；NOT_UP_YET 简记下轮继续；DERIVE_FAILED 报告「新 SSH 串获取失败，需要人工提供」。
   - ALREADY_RUNNING：平台侧环境在运行但 SSH 连不上，报告此矛盾状态，不要触发重开。
   已有重开进行中（logs/relaunch-state.env 存在）且仍 ssh_ok=0 时直接 adopt，不要重复 trigger。重开超 40 分钟未完成只报告一次。
4. 不要改 target.env（adopt 会自己改）、不要动仓库代码、不要杀环境内进程。
