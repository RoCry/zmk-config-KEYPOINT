# KEYPOINT 八色显示设计

2026-10-23 · 初版已由用户手动升级，照片确认彩色 UI、头像及 KP4 数据。后续用户要求纯黑背景、重新设计 UI、全屏图片与顶部整条黑底图标；旧四张非全屏图片删除，加入三张新原图。黑底版已实现，用户明确选择四张图片全部使用 D（无抖动色块）。依据：[面板调研](2026-10-23-lpm009m360a-color.md)。

## 显示边界

- LVGL/Zephyr 接口：RGB565，逻辑 144×72；面板原生 72×144，RGB111 八色（黑、蓝、绿、青、红、品红、黄、白）。RGB565 不代表面板具有 65,536 色。
- 驱动：紧凑 RGB，27 byte/行、3,888 byte framebuffer；原生逐行 dirty 状态。检查矩形、pitch、buf_size；失败保留 dirty 行，允许完整重试。
- SPI：1 MHz、SCS 高有效，6 µs setup/hold/低电平间隔；逐行地址及尾部 dummy clocks 按规格编码。取消未经证实的 VCOM 指令、单色及任意旋转配置。
- LVGL：16 bpp、100% 刷新缓冲。90° 旋转采用原地整数置换，避免临时整帧及条带刷新放大原生行写入。
- 不推断 DISP/EXTCOMIN 接线，不虚构休眠控制。DISP 复位、COM、冷启动及唤醒仍需实物验证。

## UI 颜色

纯黑底、白色正文；移除标题/状态行色底、进度条边框及蓝牙档位方框。标题用彩色文字，额度使用细进度条＋百分比，分页使用小圆点式像素标记，活动档位使用下划线。主题集中于 `widgets/theme.c`。

| 元素 | 配色 |
|---|---|
| CLAUDE / CODEX | 黄 / 青 |
| 太阳 / 云 / 雨 | 黄 / 青 / 青 |
| 温度与时间 / 代码 | 品红 / 绿 |
| 行状态 neutral / positive / attention / warning / error | 卡片强调色 / 绿 / 青 / 黄 / 红 |
| 数据过期 | 右下角品红分离标记，保留内容 |
| 电池 >20% / ≤20% / ≤10% / 充电 | 绿 / 黄 / 红 / 青 |
| USB / 已连接 / 离线 / 配对 | 青 / 绿 / 红 / 青 |
| BASE / 其他层 | 白 / 品红 |

所有容器显式无边框、无 padding、纯黑不透明；消除 LVGL 默认样式漏白。蓝牙档位保留下划线、连接点及未配对加号等形状线索。移除旧的全局反色选项。

## KP4 与 producer

`KP4|GEN|IDX|TOTAL|ICON|LED|ROLES|L1|L2|L3|L4|L5|L6`，最多 88 bytes。`ROLES` 恰好六位：0 neutral、1 positive、2 attention、3 warning、4 error。行与语义随整代卡片原子提交；不兼容 KP3。

固件只把语义映射到颜色；producer 决定业务状态，不传 RGB。每个额度窗口及 scoped limit 独立判断**已用额度**：<75% positive、75–<90% attention、≥90% warning。原有整卡 LED hint 保持独立，scoped limit 不参与整卡 LED 汇总；不根据倒计时猜测消耗速度。

`Row.role` 默认 neutral，时间戳插入和空行补齐保持角色对齐。旧缓存缺少 role 时为 neutral，下次成功 fetch 才获得新角色。发送端默认 acknowledged GATT write，使固件拒绝可见。

## 图片与预览

- 保留输入 RGB，量化到固定八色；默认无抖动，匹配四张获选 D 预览；`--dither` 可显式启用 Floyd–Steinberg。导出 LVGL indexed-4bit，BGRA 调色板、每字节两像素；保留 indexed-1/2bit 解码。独立预览像素哈希锁定最终素材。
- 所有图库原图重新裁切为 72×144，逆时针旋转为逻辑 144×72；不补边、不拉伸。图库：阿尔·帕西诺、favorite_69b97550、rezaul_karim、minion；来源 basename/hash 与裁切参数写入 C 素材注释，原图不入仓库。每 60 秒按序轮播，由 LVGL timer 保证显示线程内更新。
- 右屏照片覆盖全屏，顶部叠加一条 72×18 纯黑状态栏。图片底部白边原因为旧图片 120px 高、起点 20px，留下末尾 4 行；现以完整图像几何消除。
- `just preview` 编译固件共享绘图、对象布局、图库、LVGL 8.3.7、旋转和面板编码；真实 LVGL flush 输出左右屏 PNG 到 `tmp/status-preview/`。完整对象组合可发现容器漏白与图片边缘问题。
- 图像解码预览与原图/无抖动/抖动对照位于本地 `tmp/eight-color-al-pacino/`。

## 交付与验收

Push → GitHub Actions → 下载左右 UF2 → 用户手动升级。初次 KP4 升级已完成 acknowledged deck 与照片验证，定时 producer 已恢复；本轮 UI 仍使用 KP4，无需再次停推。最终图片已逐像素匹配用户选择的 D 预览。详见 rcink 的 `producer/docs/keypoint-kp4.md`。

独立字节样本验证八色、旋转、pitch、局部写入、失败重试；共享原生渲染验证 UI 和语义；左右完整构建确认 RAM/FLASH。结果见[验证记录](2026-10-23-eight-color-validation.md)。主机预览不能替代实屏颜色、方向、可读性、冷启动、唤醒与功耗验收。
