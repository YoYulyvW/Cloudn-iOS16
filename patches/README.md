# patches/

`ios16-port.patch` 是把上游 `mengangs/Cloudn`（2026-11 的 1.4.1 提交）移植到 iOS 16.4 的完整 unified diff，纯粹用于审阅与手动应用：

```bash
git clone https://github.com/mengangs/Cloudn.git && cd Cloudn
git apply /path/to/ios16-port.patch
```

真正参与自动构建的是 `scripts/port_ios16.py` —— 它对上游源码做同样的确定性改写，上游更新后可直接重跑，不依赖这个补丁的上下文能否对齐。
