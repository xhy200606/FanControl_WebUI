# 架构与安全边界

## 控制权模型

系统任意时刻只允许一个自动控制器拥有 PWM：

1. 原生模式：宿主机 `fancontrol` 拥有 PWM。
2. 增强模式：Agent 先停止 `fancontrol`，再接管 PWM。
3. 手动模式：Agent 关闭增强模式并停止 `fancontrol`，然后写入手动 PWM。

关闭增强模式时，Agent 先把受控 PWM 写到 100%，再尝试启动宿主机 `fancontrol`。

## 原生多传感器模式

Agent 不重写 fancontrol 算法，而是利用 `FCTEMPS` 的可执行命令温度源：

```text
CPU ─┐
GPU ─┼─> temp_source.py ─> max() ─> millidegree Celsius ─> fancontrol
NVMe ┘
```

所有传感器失效时输出 `failsafe_temp × 1000`。

## 增强模式

增强控制器直接写 `/sys/class/hwmon/.../pwmN`：

```text
多个温度源 -> max -> hysteresis -> piecewise curve -> safety overrides -> PWM
```

安全覆盖顺序：

1. 所有温度源不可用：100%
2. 达到应急温度：100%
3. 已关联 RPM 且目标 ≥30% 时检测到 0 RPM：100%
4. 否则执行曲线目标

## 容器权限

Web UI：普通 Docker 容器，无 `/sys` 和宿主机命名空间权限。

Agent：为了控制宿主机硬件，Docker Compose 使用 `privileged: true`、`pid: host` 和 `/sys:/sys:rw`。因此 Agent 等价于高权限宿主机服务，必须只运行可信镜像与可信代码。
