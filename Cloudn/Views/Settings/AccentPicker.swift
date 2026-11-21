// Cloudn · SPDX-License-Identifier: AGPL-3.0-or-later
import SwiftUI

/// 主题色：预设色块 + 系统取色器（色相 / 饱和度 / 明度任选）
struct AccentPicker: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("主题色")
            HStack(spacing: 0) {
                ForEach(AppSettings.accentPresets, id: \.hex) { preset in
                    let selected = app.settings.accentHex == preset.hex
                    Button { app.settings.accentHex = preset.hex } label: {
                        // 色块画实际生效的颜色（浅色下对比度不够的已自动压暗）
                        Circle()
                            .fill(Color(uiColor: AppSettings.accentUIColor(hex: preset.hex) ?? UIColor(named: "AccentColor") ?? .systemOrange))
                            .frame(width: 28, height: 28)
                            .overlay {
                                Circle().strokeBorder(Color.ink, lineWidth: selected ? 2 : 0).padding(-4)
                            }
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(preset.name)
                    .accessibilityAddTraits(selected ? .isSelected : [])
                }
                ColorPicker("自定义", selection: Binding(
                    get: { app.settings.accentColor },
                    set: { app.settings.accentHex = $0.hexString }
                ), supportsOpacity: false)
                .labelsHidden()
                .frame(maxWidth: .infinity, minHeight: 44)
            }
            .padding(.vertical, 2)
            .cnFeedback(.selection, trigger: app.settings.accentHex)
        }
    }
}
