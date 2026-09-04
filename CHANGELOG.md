# 更新日志

## 0.2.2 - 2026-09-04

- 修复 Agent 在部分 Docker/PVE 环境中无法发现宿主机 hwmon 的问题：优先通过 `nsenter` 扫描宿主机 `/sys/class/hwmon`
- 增加 hwmon/PWM 诊断信息，区分“无 hwmon”“无 PWM”“PWM 不可写”
- IPMI/BMC 改为可选能力；没有 `/dev/ipmi0` 时不再返回原始设备错误
- Docker GitHub Actions 改为仅在 `v*` 标签或手动触发时构建镜像
- Test workflow 改为仅在 PR、`v*` 标签或手动触发时运行，普通 main 文件更新不再触发编译

## 0.2.1 - 2026-09-04

- 修复 `curl | bash` 场景下 `BASH_SOURCE[0]` 未定义导致安装失败
- 修复管道安装时 Web 交互输入无法读取终端的问题

## 0.2.0 - 2026-09-04

- 架构拆分为 PVE Host Agent + LXC Web UI
- Agent 与 Web UI Docker 化
- 新增一键安装、更新与卸载脚本
- 新增 NVIDIA / Tesla P100 温度读取
- 新增原生 fancontrol 多传感器最大值 `!command` 温度源
- 新增增强多节点 PWM 曲线
- 新增滞回、应急温度、传感器失效与风扇停转保护
- 新增 48 小时历史记录
- 新增 Prometheus 指标
- 新增 Webhook 告警
- 新增通用 IPMI/BMC 传感器读取
- Web UI 重构为中文 Apple-inspired 管理界面
- 增加双 Token 架构，浏览器不接触 Agent Token

## 0.1.0

- 单体 PVE Web 风扇管理原型
- hwmon、fancontrol、NVIDIA 温度监控
- 原生 fancontrol 参数编辑与手动 PWM
