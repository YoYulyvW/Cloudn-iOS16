# Cloudn iOS 16.4（自动跟随上游）

把 [mengangs/Cloudn](https://github.com/mengangs/Cloudn)（原生 SwiftUI，官方要求 iOS 17+）移植到 **iOS 16.4** 可编译、可运行的版本，并用 GitHub Actions 做到：

- **自动同步上游**：每次运行都重新拉取 `mengangs/Cloudn` 的最新代码，再套用移植脚本，上游发新版即自动带上；
- **自动构建未签名 IPA**：macOS runner 上 `xcodebuild` 出未签名 IPA，挂到版本化 Release（供应用内更新读取）并保留 30 天 artifact；
- **自动产出可直接打开的源码分支**：移植后的完整源码被推送到本仓库的 `ios16` 分支，`git clone` 后用 Xcode 打开即可。

> 本仓库只存放「移植层」（脚本 + 工作流 + 补丁），不复制上游代码，因此永远跟上游保持一致。

---

## 工作方式

```
每天 03:00 UTC（或手动触发 / push main）
        │
        ├─ git clone --depth 1 https://github.com/mengangs/Cloudn   （上游最新）
        ├─ python3 scripts/port_ios16.py upstream-src               （套用 iOS 16.4 移植）
        ├─ xcodebuild ... CODE_SIGNING_ALLOWED=NO                   （构建未签名 IPA）
        ├─ push 移植后源码 → 本仓库 ios16 分支
        └─ 上传 artifact + 更新 Release "ios16-latest"
```

## 目录

| 路径 | 作用 |
|---|---|
| `.github/workflows/build.yml` | 同步上游 + 构建 IPA + 发布（定时 / 手动 / push main） |
| `scripts/port_ios16.py` | 移植转换器（幂等、确定性；上游更新后直接重跑） |
| `scripts/build_ipa.sh` | 本机 macOS 一键构建 |
| `patches/ios16-port.patch` | 完整 unified diff，供审阅 / 手动 `git apply` |
| `ios16` 分支 | 每次构建成功后自动更新的「已移植源码」快照 |
| 应用内更新 | `UpdateChecker.repository` 指向本仓库；Release tag `v<版本>-b<构建号>`，CFBundleVersion=1000+run |

## 启用（把本目录变成一个 GitHub 仓库）

```bash
cd Cloudn-iOS16
git init -b main
git add -A && git commit -m "Cloudn iOS 16.4 port + auto-sync build"
gh repo create <你的账号>/Cloudn-iOS16 --public --source=. --push
# 或：git remote add origin git@github.com:<你>/Cloudn-iOS16.git && git push -u origin main
```

推送后到仓库 **Actions** 页确认 workflow 已启用（默认启用），点一次 **Run workflow** 验证：

1. 构建通过 → 生成 `Cloudn-ios16.4-<版本>.ipa`；
2. Releases 出现 `v<版本>-b<构建号>`（正式 Release；应用内「检查更新」读它）；
3. 分支列表出现 `ios16`（已移植源码）。

> 若仓库设置了 "Workflow permissions = Read repository contents"，请在 **Settings → Actions → General** 改成 **Read and write**，否则发布 Release / 推分支会 403。

## 安装 IPA

产物是**未签名 IPA**，需自签或自签工具安装（iOS 16.4）：

- **TrollStore**（16.4 若在支持范围）：直接安装；
- **AltStore / Sidekiq / Sideloadly / ESign**：用你自己的 Apple ID 或证书重签名后安装；
- 或把源码分支 `ios16` clone 下来，用 Xcode 选自己设备运行。

```bash
gh release download -R <你>/Cloudn-iOS16 -p '*.ipa'
```

## iOS 16.4 兼容性改动

| 上游用法（iOS 17+） | 移植后（iOS 16.4） |
|---|---|
| `IPHONEOS_DEPLOYMENT_TARGET = 17.0` | `16.4`（所有 target） |
| `CloudnKit` `.iOS(.v17)` | `.iOS(.v16)` |
| `@Observable` / `import Observation` | `ObservableObject` + 各存储属性 `@Published`；AppModel 手动转发子对象 `objectWillChange` |
| `@Environment(AppModel.self)` / `.environment(model)` | `@EnvironmentObject` / `.environmentObject(model)` |
| `@Bindable` / `Bindable(model)` | `CNBindable` / 手写 `Binding` |
| `.sensoryFeedback(.success, trigger:)` | `.cnFeedback(...)`（UIKit 触感发生器实现） |
| `.onChange(of:){ old, new in … }` | `.cnOnChange(of:)`（内部记录上一次值） |
| `.scrollPosition(id:)` / `.scrollTargetLayout()` | `.cnScrollPosition` / `.cnScrollTargetLayout`（iOS 16 上降级为无操作） |
| `.phaseAnimator([...])` | `.cnPhasePulse()`（循环淡入） |
| `.navigationDestination(item:)` | `.cnNavigationDestination(item:)`（`isPresented` + 绑定桥接） |
| `.snappy` / `.spring(duration:)` | `.cnSnappy` / `.cnSpring(duration:)`（等价曲线） |
| `MainActor.assumeIsolated { … }` | `cnAssumeMain { … }`（同为主线程断言，避开 iOS 17 符号） |
| CloudnKit `ProxyConfiguration` / `proxyConfigurations` | URLSession 用 `connectionProxyDictionary`；WKWebView 代理仅 iOS 17+ 生效 |
| `withThrowingDiscardingTaskGroup` / `withDiscardingTaskGroup` | 普通 `TaskGroup`（结果丢弃） |

兼容层代码集中在 `Cloudn/Compat/CNCompat.swift`（由脚本生成）。

## 已知取舍

- 分享页「回到目录上次停留位置」（`scrollPosition`）在 iOS 16 上不生效，其余滚动、手势、布局正常；
- 触感反馈用 UIKit 发生器近似，iOS 17 的原生 `.sensoryFeedback` 语义（含条件触发）已按调用点还原；
- 未签名 IPA 依赖重签名工具；升级到新版本前建议先导出备份（应用内已支持认证备份）。

## 本机构建

```bash
./scripts/build_ipa.sh            # 需要 macOS + Xcode 15+
# 或指定上游镜像/分支
UPSTREAM=https://github.com/mengangs/Cloudn.git ./scripts/build_ipa.sh
```

## 维护

- 上游大改导致脚本失配时：workflow 会 `failure` 并自动开 issue；按报错更新 `scripts/port_ios16.py` 中对应的字面替换即可。
- 脚本对关键替换点做「找不到就报错退出」，避免上游变动后静默产出坏包。
- 本项目是对 AGPL-3.0 上游的衍生修改，分发时请遵守 AGPL-3.0。