# CNB 云原生开发环境保活与自动重开 —— 部署与使用手册

适用对象：在腾讯 CNB（cnb.cool）的云原生开发环境里长期运行一个项目（如一个 Web 服务），希望它不被平台闲置回收、被回收后能自动重开恢复、并且对外地址固定不变。

生产实证（2026-11-03，仓库 `ypvps/qdmz`，环境内跑 lxdapi :8081）：受控实测中手动停掉环境模拟回收，约 **50 秒**新环境就绪，项目与隧道由启动阶段自动恢复，固定域名全程不变，心跳自动接管，全程零人工。

---

## 一、平台回收规则（先理解，再保活）

来自 CNB 官方文档与实测：

| 规则 | 说明 |
|---|---|
| 心跳回收 | 环境创建后未进入 VS Code 页面，或页面关闭后无操作，超过 `keepAliveTimeout`（默认 **10 分钟**）自动回收。检测的是环境内的 **HTTP/SSH 连接** |
| 最大保持 | 持续心跳最长保持 **18 小时**（实测上一环境存活 65041302ms ≈ 18.06h 被回收） |
| 不过夜 | 使用超过 8 小时且处于凌晨 **04:00–06:00**，强制回收 |
| 代码备份 | 环境销毁时自动备份未提交代码与工作区文件，新环境创建时自动恢复（含未跟踪文件，实测 `/workspace` 下的脚本、子项目、二进制均可漫游） |

推论：保活的目标不是"永不回收"（做不到），而是 **该活着时不因闲置死、死了能自己爬起来、且对外地址不变**。

## 二、系统架构

```
┌─ 常驻机器（沙箱/服务器）──────────────────────────────┐
│  cron 每 10 分钟                                        │
│    └─ bin/check.sh                                     │
│         ├─ bin/hold.sh：维持一条常驻 SSH 连接 ─────────┼──► CNB 环境 sshd（心跳）
│         ├─ SSH 自愈：业务进程/隧道没跑就拉起            │
│         └─ 探活：cnb.run 地址 + 固定域名                │
│    └─ bin/relaunch.sh（check 发现 SSH 已死时）          │
│         ├─ trigger：POST /{repo}/-/build/start          │
│         │            {event: api_trigger} ─────────────┼──► CNB API 创建新环境
│         └─ adopt：GET /workspace/list 取新环境          │
│                  GET /{repo}/-/workspace/detail/{sn}    │
│                    → remoteSsh 字段 = 新 SSH 串          │
│                  改写 target.env，心跳切换到新环境       │
└────────────────────────────────────────────────────────┘
┌─ CNB 环境（每次重建）──────────────────────────────────┐
│  .cnb.yml 启动阶段 auto-restore（平台自动执行）：        │
│    ├─ bash /workspace/start-dev-env.sh   ← 项目自备：    │
│    │     拉起依赖与业务进程（本例：Tailscale + lxdapi）  │
│    └─ bash /workspace/start-cnb-extras.sh ← 本仓库提供： │
│          拉起 cloudflared 隧道 → 固定域名直达业务端口    │
│  漫游文件（随代码备份恢复）：                            │
│    /workspace/.bin/cloudflared、/workspace/.cf-tunnel-token │
└────────────────────────────────────────────────────────┘
```

## 三、组件清单

| 文件 | 作用 |
|---|---|
| `bin/hold.sh` | 幂等维持一条 `ssh -N` 常驻连接（ServerAliveInterval 25s），断线下轮自动重连 |
| `bin/ensure-remote.sh` | 在环境内执行：业务进程（按端口/进程名判断）与 cloudflared 没跑就拉起 |
| `bin/check.sh` | 一轮巡检：hold + SSH 自愈 + 双地址探活 + 写一行日志到 `logs/keepalive.log` |
| `bin/relaunch.sh` | `trigger` 触发新环境（带防重复触发状态文件）；`adopt` 取新 SSH 串并完成接管；`status` 查看武装与运行状态。仅当项目根存在 `ARMED` 文件时 trigger 才生效（防止配置未就绪时误触发） |
| `workspace/start-cnb-extras.sh` | 放在工作区 `/workspace`：拉起 cloudflared（缺二进制自动下载），被 `.cnb.yml` 阶段调用 |
| `examples/.cnb.yml` | 仓库侧配置：`vscode` 与 `api_trigger` 两条流水线都声明 vscode 服务 + auto-restore 阶段，`keepAliveTimeout: 30m` |
| `examples/target.env.example` | 目标参数模板（SSH 串、项目地址、仓库 slug、固定域名） |
| `docs/cron-task-body.md` | 每 10 分钟巡检的任务正文样例（判读与上报口径） |

## 四、前置条件

### 1. CNB 访问令牌（权限是逐项勾选、且创建后不可修改）

实测过的接口与所需权限（令牌在 cnb.cool 个人设置 → 访问令牌创建，Git 用户名固定为 `cnb`）：

| 接口 | 用途 | 所需权限 |
|---|---|---|
| `POST /{repo}/-/build/start` | 触发 api_trigger 建环境 | `repo-cnb-trigger:rw` |
| `POST /{repo}/-/build/stop/{sn}` | 停掉某个环境（= 停其流水线） | `repo-cnb-trigger:rw` |
| `GET /workspace/list` | 查我的环境列表（状态、business_id） | 账号类默认可读（muse2 实测可） |
| `GET /{repo}/-/build/status/{sn}`、阶段日志 | 看创建进度与阶段结果 | `repo-cnb-history`（只读即可） |
| `GET /{repo}/-/workspace/detail/{sn}` | **取回新环境的 SSH 串（remoteSsh 字段）** | `repo-cnb-detail`（只读即可） |
| `POST /workspace/stop` | 官方停环境接口 | `account-engage:rw`（可用 build/stop 替代，不必开） |
| Git push | 推 `.cnb.yml` 等仓库文件 | `repo-code:rw` |

建议直接建一个令牌把上表全部勾上（生产用的是名为 muse3 的令牌：除平台上限只读的 5 项外全读写、永久有效）。令牌值只存部署机 `secrets/` 下 600 权限文件，不进任何仓库。

### 2. Cloudflare 隧道（固定域名）

- 在 Cloudflare 侧建一条命名隧道，DNS CNAME（开代理）指向 `<tunnel-id>.cfargotunnel.com`，远端 ingress 把你的域名指到环境内的业务端口（如 `http://localhost:8081`）
- 注意：域名用**一级子域名**（如 `cnb.example.com`），免费版 Universal SSL 的通配符只覆盖一级
- 隧道令牌落到环境 `/workspace/.cf-tunnel-token`（600），cloudflared 二进制放 `/workspace/.bin/`，两者随代码备份漫游

### 3. 一台常驻机器

跑心跳连接与 10 分钟巡检（cron 或等价调度）。它需要：能 SSH 出网到 `cnb.space:22`、能访问 `api.cnb.cool` 与项目地址。

### 4. 项目侧的恢复脚本

`/workspace/start-dev-env.sh`（项目自备）：环境起来后把业务拉起来，要求幂等（已运行则跳过）、缺依赖能自补（本例会自装 Go 并重编二进制）。本仓库的 extras 脚本同理。

## 五、部署步骤

1. **备令牌**：按上表建 CNB 令牌，存入部署机 `secrets/cnb-token3.txt`（600）。
2. **放脚本**：把 `bin/` 放到部署机工作目录，复制 `examples/target.env.example` 为 `target.env` 填好（SSH 串从 CNB 环境页"更多操作 → SSH"复制；`business-id` 是 cnb.run 地址里 `-8081` 前面那段，也可从 `/workspace/list` 读）。
3. **建隧道**：按前置条件 2 建好 Cloudflare 隧道与解析；把 cloudflared 与隧道令牌放进当前环境的 `/workspace/.bin/`、`/workspace/.cf-tunnel-token`，并放入 `workspace/start-cnb-extras.sh`。
4. **先手动验通**：运行 `bin/hold.sh`（应显示 holder started）、`bin/check.sh`（应 `ssh_ok=1` 且双地址 200）；浏览器打开固定域名确认是业务页面。
5. **推 .cnb.yml**：把 `examples/.cnb.yml` 的内容合并进目标仓库根目录的 `.cnb.yml` 并推送到默认分支。
   ⚠️ 实测坑：用 git credential.helper 方式推 CNB 曾假报"缺 repo-code:rw"，改用 shell 展开令牌的内嵌 URL 一次成功：`git push "https://cnb:$(cat secrets/cnb-token3.txt)@cnb.cool/<组织>/<仓库>.git" main`（令牌不要以明文出现在命令里）。
6. **武装并挂巡检**：`touch ARMED`；按 `docs/cron-task-body.md` 建每 10 分钟的巡检任务。
7. **受控实测一次**（强烈建议）：`POST /{repo}/-/build/stop/{当前sn}` 停掉环境 → 等巡检或手动 `bin/relaunch.sh trigger` → `bin/relaunch.sh adopt` → 核对：新地址 200、固定域名 200、新环境内业务与隧道进程的启动时间≈环境创建时间、check.sh 全绿。

## 六、日常使用

- 访问项目只用**固定域名**；cnb.run 地址每次重建都会变（仅作巡检探活与排障参考，adopt 会自动更新 target.env）
- 看状态：`bin/relaunch.sh status`、`tail logs/keepalive.log`
- 停保活：停掉巡检任务并 kill 掉 `ssh -N` 持有进程即可；环境会在保活窗后被平台自然回收
- 令牌/隧道令牌轮换：换部署机 `secrets/` 与环境 `/workspace/.cf-tunnel-token` 里的文件，下一轮巡检自动生效

## 七、自动恢复时序（一次自然回收的完整流程）

1. 平台回收环境（18h 上限或凌晨窗口）→ SSH 连接断、心跳进程退出
2. 巡检 check.sh 连续两轮 `ssh_ok=0` → `relaunch.sh trigger` 调 build/start（api_trigger）
3. CNB 按 `.cnb.yml` 建新环境（实测约 50 秒 running），代码备份自动恢复 `/workspace`
4. 启动阶段 auto-restore 执行：业务进程与 cloudflared 隧道自起，固定域名恢复 200
5. 巡检 `relaunch.sh adopt`：list 拿到新 sn → detail 拿到 `remoteSsh` → 改写 target.env → 心跳重连新环境 → check.sh 全绿 → 记录并上报"恢复成功"

## 八、坑与注意事项（都是实测踩过的）

- **SSH 串不可推导**：连接串形如 `cnb-<sn>-001.<uuid>-<尾标>@cnb.space`，uuid 与尾标每个环境随机生成（旧环境尾标 -ufk、新环境 -569），只能从 detail 接口的 `remoteSsh` 或网页端复制；构建日志里没有。
- **令牌权限不可改**：令牌页的铅笔只能改名，权限只能在创建时定；勾错了就新建一个。
- **两種停环境方式**：`POST /workspace/stop` 需要 `account-engage:rw`；`POST /{repo}/-/build/stop/{sn}` 用 trigger 权限即可，效果相同。
- **触发防抖**：trigger 内置 20 分钟状态守卫且先查"是否已有 running 环境"，不会重复建环境；adopt 未完成前不要手动改 target.env。
- **心跳接不上的风险窗**：若 adopt 失败（例如 detail 权限缺失），新环境没有心跳，会在 `keepAliveTimeout`（本配置 30 分钟）后再次被回收并被巡检再次触发，项目随之周期性闪断 —— 所以 detail 权限是全自动闭环的必要条件，不是可选优化。
- **凌晨窗口预期化**：04:00–06:00 的回收是平台规则不是故障，巡检与告警文案应按"预期事件"处理。
- **凭据卫生**：所有令牌只以 600 权限文件存放；经命令行传输密钥时用 base64 并按长度校验，避免明文进命令串被打码污染。
