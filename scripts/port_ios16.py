#!/usr/bin/env python3
# Cloudn -> iOS 16.4 移植转换器（幂等）
# 用法: python3 port_ios16.py <Cloudn 源码目录>
#
# 做的事：
#   1. 部署目标 17.0 -> 16.4（xcodeproj / Package.swift）
#   2. Observation(@Observable) -> Combine(ObservableObject + @Published)
#   3. iOS 17 才有的 SwiftUI 修饰符 -> Cloudn/Compat/CNCompat.swift 兼容实现
#      (.sensoryFeedback / .onChange(of:){old,new} / .scrollPosition / .scrollTargetLayout
#       / .phaseAnimator / .navigationDestination(item:) / .snappy / .spring(duration:))
#   4. @Bindable / Bindable(_) / @Environment(X.self) / @StateObject 等 Observation 专属写法改写
#   5. MainActor.assumeIsolated(iOS17) -> cnAssumeMain 兼容实现
import os, re, sys, pathlib

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
errors, warnings = [], []

OBSERVABLE_FILES = {
    'Cloudn/Services/TorrentFetchStore.swift': 'TorrentFetchStore',
    'Cloudn/Services/BatchJob.swift': 'BatchJob',
    'Cloudn/Services/AppSettings.swift': 'AppSettings',
    'Cloudn/Services/BookmarkStore.swift': 'BookmarkStore',
    'Cloudn/Services/AccountStore.swift': 'AccountStore',
    'Cloudn/Services/DownloadStore.swift': 'DownloadStore',
    'Cloudn/Services/UploadStore.swift': 'UploadStore',
    'Cloudn/App/AppModel.swift': 'AppModel',
    'Cloudn/Views/Downloads/DownloadsView.swift': 'SpeedSampler',
    'Cloudn/Views/Accounts/WebLoginView.swift': 'WebLoginStore',
    'Cloudn/Views/Resolve/SnifferView.swift': 'SnifferBrowser',
    'Cloudn/Views/Resolve/ShareBrowserModel.swift': 'ShareBrowserModel',
}

def read(rel):
    p = ROOT / rel
    if not p.exists():
        errors.append(f'缺少文件 {rel}')
        return ''
    return p.read_text(encoding='utf-8')

def write(rel, s):
    (ROOT / rel).write_text(s, encoding='utf-8')

def sub_file(rel, old, new, required=True, already_ok=None):
    s = read(rel)
    if not s:
        return
    if old in s:
        write(rel, s.replace(old, new))
        return
    marker = already_ok if already_ok is not None else new
    if marker and marker in s:
        return
    if required:
        errors.append(f'{rel}: 找不到片段 {old[:70]!r}')
    else:
        warnings.append(f'{rel}: 跳过片段 {old[:50]!r}')

def sub_all_swift(old, new, required=False):
    for p in ROOT.joinpath('Cloudn').rglob('*.swift'):
        if 'Cloudn/Compat/' in p.as_posix():
            continue
        s = p.read_text(encoding='utf-8')
        if old in s:
            p.write_text(s.replace(old, new), encoding='utf-8')

def scan_lines(text):
    """返回每行起始的 (括号深度, 是否在字符串内)。支持 // 注释与三引号多行字符串。"""
    depths, instrs = [], []
    depth = 0; i = 0; n = len(text)
    instr = intriple = esc = inline_comment = False
    line_start = True
    while i < n:
        c = text[i]
        if line_start:
            depths.append(depth); instrs.append(instr or intriple)
            line_start = False
        if c == '\n':
            inline_comment = False; line_start = True; i += 1; continue
        if inline_comment:
            i += 1; continue
        if intriple:
            if text.startswith('"""', i):
                intriple = False; i += 3; continue
            i += 1; continue
        if instr:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': instr = False
            i += 1; continue
        if text.startswith('"""', i):
            intriple = True; i += 3; continue
        if c == '"':
            instr = True; i += 1; continue
        if c == '/' and i + 1 < n and text[i + 1] == '/':
            inline_comment = True; i += 2; continue
        if c == '{': depth += 1
        elif c == '}': depth -= 1
        i += 1
    return depths, instrs

PROP_RE = re.compile(r'^(?P<indent>\s*)(?P<attrs>(?:@\w+(?:\([^)]*\))?\s+)*)(?P<mods>(?:(?:private|fileprivate|internal|public|open)(?:\(set\))?\s+)*)(?P<kw>var|let)\b')

def convert_observable(rel, cls):
    s = read(rel)
    if not s:
        return
    if '@Observable' not in s and f'final class {cls}: ObservableObject' not in s and f'final class {cls}: ' not in s:
        pass
    lines = s.split('\n')
    depths, instrs = scan_lines(s)
    # 定位 @Observable 行与 class 声明行
    obs_idx = None
    for idx, ln in enumerate(lines):
        if ln.strip() == '@Observable':
            obs_idx = idx; break
    cls_idx = None
    for idx, ln in enumerate(lines):
        if re.search(r'\bfinal class\s+' + re.escape(cls) + r'\b', ln):
            cls_idx = idx; break
    if cls_idx is None:
        errors.append(f'{rel}: 找不到 class {cls}'); return
    # 已转换则跳过
    if 'ObservableObject' in lines[cls_idx]:
        return
    # 1) 删除 @Observable 行
    drop = set()
    if obs_idx is not None:
        drop.add(obs_idx)
    # 2) class 声明加 ObservableObject
    decl = lines[cls_idx]
    brace = decl.index('{')
    head, tail = decl[:brace], decl[brace:]
    if ':' in head:
        head = head.rstrip() + ', ObservableObject '
    else:
        head = head.rstrip() + ': ObservableObject '
    lines[cls_idx] = head + tail
    # 3) import Observation -> import Combine
    has_combine = any(ln.strip() == 'import Combine' for ln in lines)
    # 4) 属性加 @Published / 去 @ObservationIgnored（仅限本类体，且只在其第一层）
    inner = depths[cls_idx] + 1
    class_end = len(lines)
    for i2 in range(cls_idx + 1, len(lines)):
        if i2 < len(depths) and depths[i2] == depths[cls_idx]:
            class_end = i2
            break
    newlines = []
    depth_map = depths  # 原始行
    instrmap = instrs
    for idx, ln in enumerate(lines):
        if idx >= len(depth_map):
            newlines.append(ln); continue
        if idx == obs_idx:
            continue  # 删除 @Observable
        if ln.strip() == 'import Observation':
            newlines.append(re.match(r'^\s*', ln).group(0) + 'import Combine')
            has_combine = True
            continue
        # 去掉 @ObservationIgnored 并保留 rest
        if '@ObservationIgnored' in ln and cls_idx < idx < class_end:
            ln = re.sub(r'@ObservationIgnored\s+', '', ln)
            # 这类属性不发布，直接输出
            newlines.append(ln); continue
        # 只在类体第一层、且不在字符串内处理属性
        if cls_idx < idx < class_end and depth_map[idx] == inner and not instrmap[idx]:
            m = PROP_RE.match(ln)
            if m and m.group('kw') == 'var':
                stripped = ln.strip()
                # 跳过 static / class 属性
                if re.search(r'\b(static|class)\b', m.group('mods') + ' ' + stripped.split('var', 1)[0]):
                    newlines.append(ln); continue
                is_computed = False
                if '{' in stripped:
                    before_brace, after_brace = stripped.split('{', 1)
                    tail = after_brace.strip()
                    if tail.startswith('didSet') or tail.startswith('willSet'):
                        is_computed = False
                    elif tail == '':
                        # 看下一非空行
                        j = idx + 1
                        while j < len(lines) and not lines[j].strip():
                            j += 1
                        nxt = lines[j].strip() if j < len(lines) else ''
                        is_computed = not (nxt.startswith('didSet') or nxt.startswith('willSet'))
                    else:
                        is_computed = True
                if not is_computed:
                    indent = re.match(r'^\s*', ln).group(0)
                    newlines.append(indent + '@Published ' + ln.lstrip())
                    continue
        newlines.append(ln)
    if not has_combine:
        for i2, l2 in enumerate(newlines):
            if l2.strip().startswith('import '):
                newlines.insert(i2 + 1, 'import Combine')
                break
    write(rel, '\n'.join(newlines))

def add_compat_file():
    rel = 'Cloudn/Compat/CNCompat.swift'
    p = ROOT / rel
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(COMPAT_SWIFT, encoding='utf-8')

COMPAT_SWIFT = r'''// Cloudn · SPDX-License-Identifier: AGPL-3.0-or-later
// iOS 16.4 兼容层（由 ios16 移植补丁加入；上游更新后由 scripts/port_ios16.py 自动重建）
//
// iOS 17 起 SwiftUI 才有的一批 API 在这里按同名语义给出 16.4 可用的实现，
// 源码里对应用法在移植时统一改成 cn 前缀（见 scripts/port_ios16.py）。
import SwiftUI
import UIKit
import Combine

// MARK: - 触感反馈：替代 .sensoryFeedback(.selection/.success/…)
enum CNHaptic: Equatable { case selection, success, warning, error, impact, increase, decrease }

enum CNHaptics {
    static func play(_ haptic: CNHaptic) {
        switch haptic {
        case .selection, .increase, .decrease:
            UISelectionFeedbackGenerator().selectionChanged()
        case .success:
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        case .warning:
            UINotificationFeedbackGenerator().notificationOccurred(.warning)
        case .error:
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        case .impact:
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
        }
    }
}

extension View {
    func cnFeedback<V: Equatable>(_ haptic: CNHaptic, trigger: V) -> some View {
        modifier(CNFeedbackModifier(haptic: haptic, trigger: trigger, condition: nil, dynamic: nil))
    }
    func cnFeedback<V: Equatable>(_ haptic: CNHaptic, trigger: V, condition: @escaping (V, V) -> Bool) -> some View {
        modifier(CNFeedbackModifier(haptic: haptic, trigger: trigger, condition: condition, dynamic: nil))
    }
    func cnFeedback<V: Equatable>(trigger: V, _ feedback: @escaping (V, V) -> CNHaptic?) -> some View {
        modifier(CNFeedbackModifier(haptic: .selection, trigger: trigger, condition: nil, dynamic: feedback))
    }
}

private struct CNFeedbackModifier<V: Equatable>: ViewModifier {
    let haptic: CNHaptic
    let trigger: V
    let condition: ((V, V) -> Bool)?
    let dynamic: ((V, V) -> CNHaptic?)?
    @State private var previous: V?

    func body(content: Content) -> some View {
        content
            .onChange(of: trigger) { newValue in
                let old = previous ?? newValue
                if condition?(old, newValue) ?? true {
                    CNHaptics.play(dynamic?(old, newValue) ?? haptic)
                }
                previous = newValue
            }
            .onAppear { if previous == nil { previous = trigger } }
    }
}

// MARK: - 两参 onChange：iOS 17 的 .onChange(of:) { old, new in } 在 16 上不存在
extension View {
    func cnOnChange<V: Equatable>(of value: V, _ action: @escaping () -> Void) -> some View {
        onChange(of: value) { _ in action() }
    }
    func cnOnChange<V: Equatable>(of value: V, _ action: @escaping (V) -> Void) -> some View {
        onChange(of: value, perform: action)
    }
    func cnOnChange<V: Equatable>(of value: V, _ action: @escaping (V, V) -> Void) -> some View {
        modifier(CNOnChange2(value: value, action: action))
    }
}

private struct CNOnChange2<V: Equatable>: ViewModifier {
    let value: V
    let action: (V, V) -> Void
    @State private var previous: V?

    func body(content: Content) -> some View {
        content
            .onChange(of: value) { newValue in
                action(previous ?? newValue, newValue)
                previous = newValue
            }
            .onAppear { if previous == nil { previous = value } }
    }
}

// MARK: - 滚动定位：iOS 17 的 scrollPosition / scrollTargetLayout 在 16 上降级为无操作
extension View {
    @ViewBuilder
    func cnScrollTargetLayout() -> some View {
        if #available(iOS 17.0, *) { self.scrollTargetLayout() } else { self }
    }

    @ViewBuilder
    func cnScrollPosition(id: Binding<String?>, anchor: UnitPoint) -> some View {
        if #available(iOS 17.0, *) { self.scrollPosition(id: id, anchor: anchor) } else { self }
    }
}

// MARK: - 循环淡入（替代 .phaseAnimator）
extension View {
    @ViewBuilder
    func cnPhasePulse() -> some View {
        if #available(iOS 17.0, *) {
            self.phaseAnimator([0.55, 1]) { view, phase in view.opacity(phase) }
                animation: { _ in .easeInOut(duration: 0.9) }
        } else {
            self.modifier(CNPulse())
        }
    }
}

private struct CNPulse: ViewModifier {
    @State private var dim = false
    func body(content: Content) -> some View {
        content
            .opacity(dim ? 0.55 : 1)
            .animation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true), value: dim)
            .onAppear { dim = true }
    }
}

// MARK: - 基于值的导航目标（替代 .navigationDestination(item:)）
extension View {
    func cnNavigationDestination<Item: Hashable, Destination: View>(
        item: Binding<Item?>,
        @ViewBuilder destination: @escaping (Item) -> Destination
    ) -> some View {
        modifier(CNNavigationDestination(item: item, destination: destination))
    }
}

private struct CNNavigationDestination<Item: Hashable, Destination: View>: ViewModifier {
    @Binding var item: Item?
    let destination: (Item) -> Destination

    func body(content: Content) -> some View {
        content.navigationDestination(
            isPresented: Binding(get: { item != nil }, set: { if !$0 { item = nil } })
        ) {
            Group { if let item { destination(item) } }
        }
    }
}

// MARK: - @Bindable 的 16.4 替代（对 ObservableObject 取 Binding）
@propertyWrapper
struct CNBindable<T: ObservableObject> {
    var wrappedValue: T
    init(wrappedValue: T) { self.wrappedValue = wrappedValue }
    var projectedValue: Wrapper { Wrapper(base: wrappedValue) }

    @dynamicMemberLookup
    struct Wrapper {
        let base: T
        subscript<V>(dynamicMember keyPath: ReferenceWritableKeyPath<T, V>) -> Binding<V> {
            Binding(get: { base[keyPath: keyPath] }, set: { base[keyPath: keyPath] = $0 })
        }
    }
}

// MARK: - 动画：iOS 17 的 .snappy / .spring(duration:) 在 16 上换成等价曲线
extension Animation {
    static var cnSnappy: Animation { .easeOut(duration: 0.28) }
    static func cnSnappy(duration: Double) -> Animation { .easeOut(duration: duration) }
    static func cnSpring(duration: Double) -> Animation { .spring(response: duration, dampingFraction: 0.85, blendDuration: 0) }
}

// MARK: - MainActor.assumeIsolated(iOS 17) 替代：调用点已保证在主线程
@inline(__always)
func cnAssumeMain<T>(_ body: @MainActor () -> T) -> T {
    let raw = unsafeBitCast(body, to: (() -> T).self)
    return raw()
}

// MARK: - 变更转发的取消袋（AppModel 用来把子状态变更转发到自己身上）
final class CNCancelBag {
    var items = Set<AnyCancellable>()
    func add(_ cancellable: AnyCancellable) { items.insert(cancellable) }
}
'''

def main():
    # 1. 部署目标
    sub_file('Cloudn.xcodeproj/project.pbxproj', 'IPHONEOS_DEPLOYMENT_TARGET = 17.0;', 'IPHONEOS_DEPLOYMENT_TARGET = 16.4;')
    sub_file('CloudnKit/Package.swift', '.iOS(.v17)', '.iOS(.v16)')

    # 2. Observation -> Combine
    for rel, cls in OBSERVABLE_FILES.items():
        convert_observable(rel, cls)

    # 3. 全局 SwiftUI 修饰符改名
    sub_all_swift('.sensoryFeedback(', '.cnFeedback(')
    sub_all_swift('.scrollPosition(id:', '.cnScrollPosition(id:')
    sub_all_swift('.scrollTargetLayout()', '.cnScrollTargetLayout()')
    sub_all_swift('.navigationDestination(item:', '.cnNavigationDestination(item:')
    sub_all_swift('.snappy(duration:', '.cnSnappy(duration:')
    sub_all_swift('.spring(duration:', '.cnSpring(duration:')
    sub_all_swift('.onChange(of:', '.cnOnChange(of:')
    sub_all_swift('Bindable(model).selectedTab', 'Binding(get: { model.selectedTab }, set: { model.selectedTab = $0 })')
    # 裸 .snappy（后面不是括号）
    for p in ROOT.joinpath('Cloudn').rglob('*.swift'):
        if 'Cloudn/Compat/' in p.as_posix():
            continue
        s = p.read_text(encoding='utf-8')
        s2 = re.sub(r'\.snappy\b(?!\()', '.cnSnappy', s)
        if s2 != s:
            p.write_text(s2, encoding='utf-8')

    # 4. 观察环境 / 状态包装
    sub_all_swift('@Environment(AppModel.self) private var app', '@EnvironmentObject private var app: AppModel')
    sub_all_swift('@Environment(AppModel.self) private var model', '@EnvironmentObject private var model: AppModel')
    sub_all_swift('.environment(model)', '.environmentObject(model)')
    sub_all_swift('@State private var model = AppModel.shared', '@StateObject private var model = AppModel.shared')
    sub_all_swift('@State private var store = WebLoginStore()', '@StateObject private var store = WebLoginStore()')
    sub_all_swift('@State private var speed = SpeedSampler()', '@StateObject private var speed = SpeedSampler()')
    sub_all_swift('@State private var browser: SnifferBrowser', '@StateObject private var browser: SnifferBrowser')
    sub_all_swift('_browser = State(initialValue: SnifferBrowser(url: url))', '_browser = StateObject(wrappedValue: SnifferBrowser(url: url))')
    sub_all_swift('_browser = State(initialValue: browser)', '_browser = StateObject(wrappedValue: browser)')
    sub_all_swift('@Bindable var model: ShareBrowserModel', '@ObservedObject var model: ShareBrowserModel')
    sub_all_swift('@Bindable var settings = app.settings', '@CNBindable var settings = app.settings')
    sub_all_swift('@Bindable var model = model', '@CNBindable var model = model')

    # 4b. 循环淡入动画
    sub_file('Cloudn/Views/Resolve/ShareBrowserView.swift',
             '.phaseAnimator([0.55, 1]) { view, phase in view.opacity(phase) } animation: { _ in .easeInOut(duration: 0.9) }',
             '.cnPhasePulse()')

    # 5. 作为普通 let 传入、但需要观察的对象
    sub_file('Cloudn/Views/Downloads/DownloadsView.swift', '    let sampler: SpeedSampler', '    @ObservedObject var sampler: SpeedSampler')
    sub_file('Cloudn/Views/Accounts/WebLoginView.swift', '    let store: WebLoginStore', '    @ObservedObject var store: WebLoginStore')
    sub_file('Cloudn/Views/Resolve/SaveToDriveView.swift', '    let model: ShareBrowserModel', '    @ObservedObject var model: ShareBrowserModel')
    sub_file('Cloudn/Views/Resolve/BatchView.swift', '    let job: BatchJob', '    @ObservedObject var job: BatchJob')
    sub_file('Cloudn/Views/Resolve/ResolveView.swift', '    let job: BatchJob', '    @ObservedObject var job: BatchJob')

    # 6. CloudnApp：把 Scene 上的 .onChange 移到 WindowGroup 内的 View 上
    sub_file('Cloudn/App/CloudnApp.swift',
r'''            .environment(\.accentTint, model.settings.accentUIColor)
        }
        .cnOnChange(of: scenePhase) { _, phase in
            model.scenePhaseChanged(phase)
        }
    }''',
r'''            .environment(\.accentTint, model.settings.accentUIColor)
            .cnOnChange(of: scenePhase) { _, phase in
                model.scenePhaseChanged(phase)
            }
        }
    }''')

    # 7. MainActor.assumeIsolated -> cnAssumeMain
    sub_file('Cloudn/Services/QuickActions.swift',
             'completionHandler(MainActor.assumeIsolated { QuickActions.perform(shortcutItem, model: AppModel.shared) })',
             'completionHandler(cnAssumeMain { QuickActions.perform(shortcutItem, model: AppModel.shared) })')
    sub_file('Cloudn/Services/Notifier.swift',
             'MainActor.assumeIsolated { AppModel.shared.selectedTab = .downloads }',
             'cnAssumeMain { AppModel.shared.selectedTab = .downloads }')
    sub_file('Cloudn/Services/UploadStore.swift',
             'MainActor.assumeIsolated { self?.endBackgroundTask() }',
             'cnAssumeMain { self?.endBackgroundTask() }')
    sub_file('Cloudn/App/AppModel.swift',
             'MainActor.assumeIsolated { self?.endBackgroundTask() }',
             'cnAssumeMain { self?.endBackgroundTask() }')

    # 8. AppModel：子状态变更转发（Observation 下自动，ObservableObject 下需手动）
    sub_file('Cloudn/App/AppModel.swift',
             '    @Published var batchJobs: [BatchJob] = []',
             '    @Published var batchJobs: [BatchJob] = []\n    let forwarders = CNCancelBag()')
    sub_file('Cloudn/App/AppModel.swift',
             '        background.reconcile()',
             '''        background.reconcile()

        // iOS 16：Observation 下子状态变更会自动通知界面；换成 ObservableObject 后手动把这些变更转发到 AppModel
        settings.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &forwarders.items)
        accounts.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &forwarders.items)
        bookmarks.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &forwarders.items)
        downloads.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &forwarders.items)
        uploads.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &forwarders.items)
        torrents.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &forwarders.items)''')
    sub_file('Cloudn/App/AppModel.swift',
             '    /// 下载失败：像是直链过期',
             '''    /// 把一个子对象（如批量任务）的变更转发到 AppModel，让观察 AppModel 的界面跟着刷新
    func forwardChanges<O: ObservableObject>(of object: O) {
        object.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &forwarders.items)
    }

    /// 下载失败：像是直链过期''')
    sub_file('Cloudn/Services/BatchJob.swift',
             '''        let job = BatchJob(title: title, entries: entries)
        batchJobs.append(job)''',
             '''        let job = BatchJob(title: title, entries: entries)
        batchJobs.append(job)
        forwardChanges(of: job)''')
    sub_file('Cloudn/App/ScreenshotMode.swift',
             '            model.batchJobs.append(job)',
             '            model.batchJobs.append(job)\n            model.forwardChanges(of: job)',
             required=False)

    # 9. 兼容层文件
    add_compat_file()

    # 10. README 徽标
    sub_file('README.md', 'iOS-17%2B-1f1e1c', 'iOS-16.4%2B-1f1e1c', required=False)
    sub_file('README.md', 'iOS 17+', 'iOS 16.4+', required=False)

    if warnings:
        print('WARN:'); [print('  -', w) for w in warnings]
    if errors:
        print('ERRORS:'); [print('  -', e) for e in errors]
        sys.exit(1)
    print('OK: iOS 16.4 移植完成 ->', ROOT)

if __name__ == '__main__':
    main()