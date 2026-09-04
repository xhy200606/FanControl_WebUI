# 更新日志

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
