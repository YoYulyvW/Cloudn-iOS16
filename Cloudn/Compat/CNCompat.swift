// Cloudn · SPDX-License-Identifier: AGPL-3.0-or-later
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
func cnAssumeMain<T>(_ body: @MainActor @escaping () -> T) -> T {
    let raw = unsafeBitCast(body, to: (() -> T).self)
    return raw()
}

// MARK: - 变更转发的取消袋（AppModel 用来把子状态变更转发到自己身上）
final class CNCancelBag {
    var items = Set<AnyCancellable>()
    func add(_ cancellable: AnyCancellable) { items.insert(cancellable) }
}
