# cnb —— 网页桥 + CNB 云原生开发保活全套

本仓库收录两套在生产中运行的系统（快照日期：2026-11-03）：

## 1. `bridge/` —— 网页桥（chat-bridge）

在 muse.ai 网页端不可用时，用自有域名提供与 Muse 的网页聊天通道，并附带飞书 / 企业微信适配器。

- `bridge.py` —— 桥主服务：网页聊天、审批卡片、文件收发、`/api/delegate` 委托接口（供 nanoMuse 的 ask_muse 工具回调）
- `feishu_adapter.py` / `wecom_adapter.py` / `wecom_crypt.py` —— 飞书、企业微信渠道适配
- `*.service` —— systemd 单元；`deploy.sh`、`run-*.sh` —— 部署与启动脚本
- 运行配置（令牌等）不在仓库内：服务从 `~/.config/chat-bridge/server.env` 读取

部署细节见 `bridge/README.md`。

## 2. `cnb-keepalive/` —— CNB 云原生开发环境保活与自动重开

针对腾讯 CNB（cnb.cool）云原生开发环境的回收规则，实现：

- **SSH 心跳保活**：一条常驻 SSH 连接顶住「10 分钟无心跳回收」
- **固定域名**：环境内 cloudflared 隧道，项目地址不随环境更换而变化
- **自动重开恢复**：环境被平台回收（18 小时上限 / 凌晨不过夜）后，巡检经 API 自动触发新环境，仓库 `.cnb.yml` 的启动阶段自动恢复项目与隧道，最后经官方 detail 接口取回新 SSH 串完成心跳接管 —— 全程无人值守，2026-11-03 已受控实测全程通过

完整的原理、部署步骤与运维手册见 `cnb-keepalive/README.md`。

## 安全说明

仓库内**不含任何真实凭据**：CNB 令牌、Cloudflare 隧道令牌、SSH 连接串、桥令牌都只存在于部署机的 600 权限文件或环境变量中。示例文件中的尖括号占位符需替换为真实值后使用，切勿把填好真实值的文件提交回仓库。
