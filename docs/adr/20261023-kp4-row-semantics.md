# KP4 传输逐行语义，预览复用固件绘图

Date: 2026-10-23
Status: Accepted

Context: 固件拥有配色，但整卡 LED hint 无法表达多个额度窗口各自的状态；独立 Python 预览会与 LVGL 彩色绘图漂移。用户已确认联合升级 producer，并委托具体颜色设计。

Decision: KP4 增加六位逐行语义，与文本随整代卡片原子提交。producer 决定 positive/attention/warning/error，固件映射颜色；保留独立整卡 LED hint。拒绝 KP3。预览直接编译固件共享绘图、固定版本 LVGL、旋转和面板编码。

Consequences: 固件和 producer 必须协调升级；旧固件运行时暂停新 sender。主机预览能校验实际软件绘图，但实屏时序及颜色仍需人工升级后确认。代价是预览需要 CMake/Ninja 和固定 LVGL 源码。

延续：[固件拥有配色](20261023-firmware-owns-display-colors.md)。实现：[八色设计](../research/2026-10-23-eight-color-display-design.md)。
