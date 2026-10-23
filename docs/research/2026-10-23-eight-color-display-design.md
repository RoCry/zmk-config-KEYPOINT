# KEYPOINT 八色显示设计

2026-10-23 · 已确认并实现。用户确认保留布局、固件决定配色、升级图片工具，并委托具体丰富配色设计。依据：[面板调研](2026-10-23-lpm009m360a-color.md)。实屏验收等待用户手动升级。

## 显示边界

- LVGL/Zephyr 接口：RGB565，逻辑 144×72；面板原生 72×144，RGB111 八色（黑、蓝、绿、青、红、品红、黄、白）。RGB565 不代表面板具有 65,536 色。
- 驱动：紧凑 RGB，27 byte/行、3,888 byte framebuffer；原生逐行 dirty 状态。检查矩形、pitch、buf_size；失败保留 dirty 行，允许完整重试。
- SPI：1 MHz、SCS 高有效，6 µs setup/hold/低电平间隔；逐行地址及尾部 dummy clocks 按规格编码。取消未经证实的 VCOM 指令、单色及任意旋转配置。
- LVGL：16 bpp、100% 刷新缓冲。90° 旋转采用原地整数置换，避免临时整帧及条带刷新放大原生行写入。
- 不推断 DISP/EXTCOMIN 接线，不虚构休眠控制。DISP 复位、COM、冷启动及唤醒仍需实物验证。

## UI 颜色

保留左右屏现有布局和图形提示；白底黑字为基础，主题集中于 `widgets/theme.c`。

| 元素 | 配色 |
|---|---|
| CLAUDE / CODEX | 青 / 蓝 |
| 太阳 / 云 / 雨 | 黄 / 青 / 蓝 |
| 温度与时间 / 代码 | 品红 / 绿 |
| 行状态 neutral / positive / attention / warning / error | 卡片强调色 / 绿 / 青 / 黄 / 红 |
| 数据过期 | 品红分段提示，保留内容 |
| 电池 >20% / ≤20% / ≤10% / 充电 | 绿 / 黄 / 红 / 青 |
| USB / 已连接 / 离线 / 配对 | 蓝 / 绿 / 红 / 青 |
| BASE / 其他层 | 蓝 / 品红 |

彩色标题和状态背景保持黑白高对比文字；蓝底使用白字。蓝牙档位保留填充、轮廓和加号等形状线索。移除旧的全局反色选项。

## KP4 与 producer

`KP4|GEN|IDX|TOTAL|ICON|LED|ROLES|L1|L2|L3|L4|L5|L6`，最多 88 bytes。`ROLES` 恰好六位：0 neutral、1 positive、2 attention、3 warning、4 error。行与语义随整代卡片原子提交；不兼容 KP3。

固件只把语义映射到颜色；producer 决定业务状态，不传 RGB。每个额度窗口及 scoped limit 独立判断**已用额度**：<75% positive、75–<90% attention、≥90% warning。原有整卡 LED hint 保持独立，scoped limit 不参与整卡 LED 汇总；不根据倒计时猜测消耗速度。

`Row.role` 默认 neutral，时间戳插入和空行补齐保持角色对齐。旧缓存缺少 role 时为 neutral，下次成功 fetch 才获得新角色。发送端默认 acknowledged GATT write，使固件拒绝可见。

## 图片与预览

- 保留输入 RGB，量化到固定八色；默认 Floyd–Steinberg 抖动。导出 LVGL indexed-4bit，BGRA 调色板、每字节两像素；保留 indexed-1/2bit 解码。
- 阿尔·帕西诺：`al_pacino_origin_1024.jpg`；SHA-256 `cd6b62203a8ee966430ce6ec86a5ca7a89a00628162cec697f6062bea61d2950`。裁剪 72×120，逆时针旋转为 120×72，重新生成 `al_pacino.c`。原图不入仓库。
- `just preview` 编译固件共享绘图 C、LVGL 8.3.7、旋转和面板编码；输出 `tmp/status-preview/`。移除独立 Python UI 仿真，避免两套绘图漂移。
- 图像解码预览与原图/无抖动/抖动对照位于本地 `tmp/eight-color-al-pacino/`。

## 交付与验收

Push → GitHub Actions → 下载左右 UF2 → 用户手动升级。升级前 KEYPOINT 定时 producer 保持暂停；升级后重新 fetch、验证 acknowledged KP4，再恢复定时任务。详见 rcink 的 `producer/docs/keypoint-kp4.md`。

独立字节样本验证八色、旋转、pitch、局部写入、失败重试；共享原生渲染验证 UI 和语义；左右完整构建确认 RAM/FLASH。结果见[验证记录](2026-10-23-eight-color-validation.md)。主机预览不能替代实屏颜色、方向、可读性、冷启动、唤醒与功耗验收。
