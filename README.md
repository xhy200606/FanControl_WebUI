# PVE Fan Control

面向 Proxmox VE 的中文 Web 风扇管理面板。V0.2 采用 **PVE 宿主机 Agent + LXC Web UI** 架构，以 `lm-sensors / fancontrol / hwmon` 为基础，并加入 NVIDIA GPU（包括 Tesla P100）联动温控、多传感器最大值策略、多节点增强曲线、滞回与故障保护。

> 风扇控制属于硬件级操作。首次使用前请先确认主板 PWM 与风扇对应关系，并用 `pwmconfig` 完成基础校准。错误的 PWM 映射可能导致散热不足。

## V0.2 功能

- 中文 Web UI，默认端口 `9487`
- Apple 风格的克制层级、系统字体、半透明材质与即时交互反馈
- PVE 宿主机 Agent 与 LXC Web UI 完全拆分
- Agent 与 Web UI 均使用 Docker 打包
- 自动发现 `hwmon` 温度、风扇 RPM 与 PWM
- 使用宿主机 `nvidia-smi` 读取 NVIDIA GPU 温度
- Tesla P100 可作为原生 `fancontrol` 或增强控制器的温度源
- 多传感器最大值策略：CPU / GPU / NVMe 等可联合控制一个 PWM
- 原生模式：继续由系统 `fancontrol` 执行，最大限度保持 Debian 原生行为
- 增强模式：Agent 接管 PWM，支持 2–10 个节点的分段线性曲线
- 增强模式支持温度滞回、传感器失效 100% 风扇、应急高温 100%、风扇停转保护
- 原生 `/etc/fancontrol` 写入前自动备份
- Web UI 中可启动、停止、重启宿主机 `fancontrol`
- 手动 PWM；进入手动模式前自动停止其它控制器，避免争抢 PWM
- 48 小时默认历史记录（SQLite，可配置）
- Prometheus 指标接口
- Webhook 高温/故障告警
- 通用 IPMI/BMC 传感器读取
- 一键安装、一键更新、一键卸载
- GitHub Actions 自动进行基础测试并构建 Docker 镜像

## 架构

```text
浏览器
  │
  │  :9487
  ▼
LXC（推荐非特权）
┌──────────────────────────────┐
│ pve-fan-web                  │
│ - 中文 Web UI               │
│ - 历史 SQLite               │
│ - Agent API 反向代理        │
└──────────────┬───────────────┘
               │ Bearer Token
               │ :9488
               ▼
PVE 宿主机
┌──────────────────────────────┐
│ pve-fan-agent (Docker)       │
│ - hwmon / PWM                │
│ - fancontrol                 │
│ - nvidia-smi                 │
│ - IPMI 读取                  │
│ - 增强控制循环               │
└───────┬───────────┬──────────┘
        │           │
        ▼           ▼
/sys/class/hwmon   fancontrol
        │
        ▼
      风扇
```

Web UI 容器不需要访问 PVE 的 `/sys`。Agent 为了写宿主机 PWM 和进入宿主机命名空间，需要高权限 Docker 配置，因此只应部署在可信的 PVE 宿主机上，并使用防火墙限制 `9488/tcp` 仅允许 Web LXC/管理网段访问。

## 前置条件

PVE 宿主机：

- Proxmox VE（Debian 基础系统）
- 主板风扇控制器已经被 Linux `hwmon` 驱动识别
- `pwmconfig` 能发现至少一个可写 PWM 通道
- NVIDIA 联动需要宿主机已经能正常执行 `nvidia-smi`
- 安装脚本会安装 Docker、`lm-sensors`、`fancontrol`、Python 3 等基础依赖

Web LXC：

- Debian 12/13 或兼容系统
- 推荐非特权 LXC
- 在 PVE 中为需要运行 Docker 的 LXC 启用 `nesting=1,keyctl=1`
- 不需要映射宿主机 `/sys` 或 GPU

## 1. 在 PVE 宿主机安装 Agent

先确认传感器与 PWM：

```bash
apt update
apt install -y lm-sensors fancontrol
sensors-detect
sensors
pwmconfig
```

从 GitHub 一键安装：

```bash
curl -fsSL https://raw.githubusercontent.com/xhy200606/FanControl_WebUI/main/install.sh | sudo bash -s -- agent
```

安装结束会显示：

```text
Agent 地址: http://PVE-IP:9488
Agent Token: <随机生成的 64 位十六进制令牌>
```

请保存 Agent Token，Web LXC 安装时需要它。Agent 配置保存在：

```text
/etc/pve-fan-control/agent.env
```

## 2. 创建 Web LXC

建议 Debian LXC。假设 CT ID 为 `120`，可在 PVE 宿主机执行：

```bash
pct set 120 -features nesting=1,keyctl=1
```

启动 LXC 后，在容器内执行：

```bash
curl -fsSL https://raw.githubusercontent.com/xhy200606/FanControl_WebUI/main/install.sh | bash -s -- web
```

脚本会询问：

1. Agent 地址，例如 `http://192.168.1.10:9488`
2. Agent Token

也可以完全无交互安装：

```bash
PVE_FAN_AGENT_URL=http://192.168.1.10:9488 \
PVE_FAN_AGENT_TOKEN='你的-Agent-Token' \
PVE_FAN_WEB_PORT=9487 \
curl -fsSL https://raw.githubusercontent.com/xhy200606/FanControl_WebUI/main/install.sh | bash -s -- web
```

安装结束会显示 Web UI Token。浏览器访问：

```text
http://LXC-IP:9487
```

首次进入输入 Web UI Token。该令牌只保存在浏览器本地存储中。

## 3. P100 / 多传感器原生联动

进入：`原生控制 → 控制源 · 最大值策略`。

例如同时勾选：

- CPU Package
- GPU 0 · Tesla P100-PCIE-16GB
- NVMe Composite

保存后 Agent 会为该 PWM 生成一个宿主机温度适配脚本，并把 `/etc/fancontrol` 中对应的 `FCTEMPS` 改为 `!command`。这个命令返回所有已选传感器中的**最高温度（毫摄氏度）**。若所有传感器均失效，则返回配置的故障保护温度，使原生 `fancontrol` 进入高转速保护状态。

所有自动修改都会先备份原配置到：

```text
/etc/pve-fan-control/backups/
```

## 4. 增强曲线模式

原生 `fancontrol` 使用线性温控。需要更精细的 P100 散热时，可启用增强模式。

默认示例曲线：

| 温度 | PWM |
|---:|---:|
| 40°C | 30% |
| 55°C | 45% |
| 65°C | 65% |
| 72°C | 82% |
| 78°C | 100% |

增强模式支持：

- 2–10 个曲线节点
- 多温度源取最大值
- 默认 3°C 滞回
- 可调应急温度
- 所有控制源失效 → 100%
- 目标转速 ≥30% 且关联 RPM 为 0 → 100% 并告警
- 关闭增强模式 → 先置 100%，再恢复宿主机 `fancontrol`

启用增强模式时，Agent 会停止宿主机 `fancontrol`，避免两个控制器同时写同一个 PWM。

## 5. 更新

Agent（PVE 宿主机）：

```bash
sudo /opt/pve-fan-control/update.sh agent
```

Web UI（LXC）：

```bash
sudo /opt/pve-fan-control/update.sh web
```

更新脚本会：

1. 从 GitHub 获取 `main` 最新代码
2. 将本地安装树重置到 `origin/main`
3. 重新构建对应 Docker 镜像
4. 滚动重建容器
5. 保留 `/etc/pve-fan-control` 配置、Token、备份与 Web 历史数据卷

因此后续只要 GitHub 仓库更新，两端分别执行一条 `update.sh` 即可升级。

## 6. 卸载

Agent：

```bash
sudo /opt/pve-fan-control/scripts/uninstall-agent.sh
```

Web UI：

```bash
sudo /opt/pve-fan-control/scripts/uninstall-web.sh
```

默认不会删除 `/etc/pve-fan-control`、备份文件以及 Web 历史卷，避免误删配置。

## 7. 防火墙建议

Agent 的 `9488/tcp` 不应直接暴露到互联网。推荐：

```text
管理电脑 ──> Web LXC :9487
Web LXC  ──> PVE Agent :9488
其它来源 ──X PVE Agent :9488
```

Agent API 和 Web UI API 均需要独立随机 Token。Web 浏览器不会直接获取 Agent Token，Web 容器负责服务端代理。

## 8. Prometheus

Agent 暴露：

```text
GET /metrics
Authorization: Bearer <Agent Token>
```

包括温度、风扇 RPM、PWM、原生服务状态和增强控制器状态。

## 9. IPMI/BMC

V0.2 提供通用 `ipmitool sensor` 读取，但**不会自动执行未知厂商的 BMC raw 写命令**。Dell、Supermicro、HPE 等厂商的风扇控制协议不同，错误 raw 指令风险高；后续版本应按厂商/主板型号分别实现并显式启用。

## 10. 开发

目录：

```text
FanControl_WebUI/
├── agent/                  # PVE 宿主机硬件 Agent
├── web/                    # LXC Web UI + 历史服务
├── deploy/
│   ├── agent/              # Agent Docker Compose
│   └── web/                # Web Docker Compose
├── scripts/                # 安装、更新、卸载、fancontrol 温度适配器
├── tests/
├── docs/
├── install.sh
└── update.sh
```

UI 设计参考 Emil Kowalski 的 `apple-design` Skill，重点采用即时反馈、空间一致性、系统字体、克制的半透明材质、可中断/低干扰交互以及 reduced-motion / reduced-transparency / increased-contrast 适配，而不是简单仿制 macOS 外观。

## 许可证

MIT License。

## 首次发布到 GitHub（维护者）

如果本地拿到的是源码压缩包，可在已经登录 GitHub CLI 的电脑上直接执行：

```bash
./scripts/publish-github.sh public
```

脚本会创建或复用 `xhy200606/FanControl_WebUI`，提交当前源码、推送 `main` 与 `v0.2.0` 标签。若希望私有仓库，将 `public` 改为 `private`；但私有仓库需要额外处理安装/更新时的 GitHub 鉴权，因此默认的一键 `curl` 安装流程更适合公开仓库。
