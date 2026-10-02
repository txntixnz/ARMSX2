from pathlib import Path

settings_store = Path("platforms/ios/app/src/main/swift/Models/SettingsStore.swift")
graphics = Path("platforms/ios/app/src/main/swift/Views/Settings/GraphicsSettingsView.swift")
core_config = Path("pcsx2/Pcsx2Config.cpp")
gs_device = Path("pcsx2/GS/Renderers/Common/GSDevice.cpp")

for p in (settings_store, graphics, core_config, gs_device):
    if not p.is_file():
        raise SystemExit(f"GS pass coalescing V9.6.4: expected source file missing: {p}")

core = core_config.read_text()
device = gs_device.read_text()
if "SettingsWrapBitBool(CoalesceRenderPasses);" not in core:
    raise SystemExit("GS pass coalescing V9.6.4: core setting is missing upstream.")
if "GSConfig.CoalesceRenderPasses" not in device:
    raise SystemExit("GS pass coalescing V9.6.4: GSDevice scheduler gate is missing upstream.")

ss = settings_store.read_text()
marker = "// ARMSX2_IOS16_GS_PASS_COALESCING_V964"

if marker not in ss:
    decl_anchor = '    let _hardwareMipmappingConfig = Setting<Bool>(\n'
    if ss.count(decl_anchor) != 1:
        raise SystemExit("GS pass coalescing V9.6.4: hardware mipmapping declaration anchor changed upstream.")

    published = "@Published " if "import Combine" in ss else ""
    decl_block = (
        f"    {marker}\n"
        '    let _coalesceRenderPassesConfig = Setting<Bool>(\n'
        '        section: "EmuCore/GS", key: "CoalesceRenderPasses", default: false,\n'
        '        suppressible: false,\n'
        '        codec: .bool)\n'
        f"    {published}var coalesceRenderPasses: Bool = false "
        "{ didSet { commit(_coalesceRenderPassesConfig, coalesceRenderPasses) } }\n"
    )
    ss = ss.replace(decl_anchor, decl_block + decl_anchor, 1)

    load_anchor = '        hardwareMipmapping = _hardwareMipmappingConfig.load()\n'
    if ss.count(load_anchor) != 1:
        raise SystemExit("GS pass coalescing V9.6.4: graphics load anchor changed upstream.")
    ss = ss.replace(
        load_anchor,
        '        coalesceRenderPasses = _coalesceRenderPassesConfig.load()\n' + load_anchor,
        1,
    )

    # New upstream split resetGraphicsDefaults into SettingsStore+Defaults.swift.
    # Patch the real reset owner, not whichever file happened to own it before.
    reset_anchor = '        hardwareMipmapping = true\n'
    reset_paths = (
        settings_store,
        Path("platforms/ios/app/src/main/swift/Models/SettingsStore+Defaults.swift"),
    )
    reset_owners = [
        p for p in reset_paths if p.is_file() and p.read_text().count(reset_anchor) == 1
    ]
    if len(reset_owners) != 1:
        raise SystemExit(
            "GS pass coalescing V9.6.4: expected one graphics reset owner."
        )
    reset_path = reset_owners[0]
    reset_text = reset_path.read_text()
    if 'coalesceRenderPasses = false\n' not in reset_text:
        reset_text = reset_text.replace(
            reset_anchor,
            '        coalesceRenderPasses = false\n' + reset_anchor,
            1,
        )
        reset_path.write_text(reset_text)

    settings_store.write_text(ss)

gfx = graphics.read_text()
ui_marker = "// ARMSX2_IOS16_GS_PASS_COALESCING_UI_V964"

if ui_marker not in gfx:
    # Upstream replaced the GS Back Thread picker with a GS Multi-threading
    # toggle. Either control may be present depending on the sync revision.
    picker_options = (
        '                Toggle(settings.localized("GS Multi-threading"), isOn: Binding(\n',
        '                intPicker("GS Back Thread", selection: $settings.backThreadMode, options: [\n',
    )
    candidates = [a for a in picker_options if gfx.count(a) == 1]
    if len(candidates) != 1:
        raise SystemExit(
            "GS pass coalescing V9.6.4: expected one recognizable Performance row."
        )

    ui_block = (
        f"                {ui_marker}\n"
        '                Toggle(settings.localized("GS Render-Pass Coalescing"), isOn: $settings.coalesceRenderPasses)\n'
        '                Text(settings.localized("Experimental. Defers compatible GS draws so independent work can be grouped into fewer render passes, reducing GS/driver overhead on tile-based mobile GPUs. It does not change PS2 internal resolution. Fully close and relaunch ARMSX2 after changing it before benchmarking."))\n'
        '                    .font(.caption)\n'
        '                    .foregroundStyle(.secondary)\n\n'
    )
    gfx = gfx.replace(candidates[0], ui_block + candidates[0], 1)
    graphics.write_text(gfx)

print("GS render-pass coalescing V9.6.4 patch applied successfully.")
print("  Existing core scheduler: unchanged")
print("  iOS UI toggle: available")
print("  Default: OFF (golden baseline preserved)")
