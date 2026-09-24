from pathlib import Path
import re
import textwrap

build_params = Path("platforms/ios/app/src/main/cpp/cmake/BuildParameters.cmake")
graphics = Path("platforms/ios/app/src/main/swift/Views/Settings/GraphicsSettingsView.swift")
ios_main = Path("platforms/ios/app/src/main/cpp/ios_main.mm")

for p in (build_params, graphics, ios_main):
    if not p.is_file():
        raise SystemExit(f"A15/Metal V9.6.1: expected source file missing: {p}")

# ---------------------------------------------------------------------------
# 1) Apple A15 compile target.
# ---------------------------------------------------------------------------
bp = build_params.read_text()

if "ARMSX2_IOS16_A15_TARGET_V961" not in bp:
    a12 = 'add_compile_options("-mcpu=apple-a12")'
    a15 = 'add_compile_options("-mcpu=apple-a15")'

    if bp.count(a12) == 1:
        bp = bp.replace(
            a12,
            '# ARMSX2_IOS16_A15_TARGET_V961\n'
            '\t\tadd_compile_options("-mcpu=apple-a15")',
            1,
        )
    elif bp.count(a15) == 1:
        bp = bp.replace(
            a15,
            '# ARMSX2_IOS16_A15_TARGET_V961\n'
            '\t\tadd_compile_options("-mcpu=apple-a15")',
            1,
        )
    else:
        raise SystemExit(
            "A15/Metal V9.6.1: could not find exactly one iOS Apple CPU compile target."
        )

    build_params.write_text(bp)

# ---------------------------------------------------------------------------
# 2) Graphics UI switches.
#    - 2x presentation surface: validated performance win.
#    - 2-frame drawable queue: next isolated latency/presentation experiment.
# ---------------------------------------------------------------------------
gfx = graphics.read_text()

if "// ARMSX2_IOS16_A15_METAL_UI_V961" not in gfx:
    state_anchor = "    @State private var showShaderCacheResult = false\n"
    if gfx.count(state_anchor) != 1:
        raise SystemExit(
            "A15/Metal V9.6.1: Graphics settings state anchor changed upstream."
        )

    state_block = (
        state_anchor
        + "    // ARMSX2_IOS16_A15_METAL_UI_V961\n"
        + '    @AppStorage("ARMSX2_MetalPresentation2x") '
          "private var metalPresentation2x = true\n"
        + '    @AppStorage("ARMSX2_MetalDrawableQueue2") '
          "private var metalDrawableQueue2 = true\n"
    )
    gfx = gfx.replace(state_anchor, state_block, 1)

    perf_anchor = '''            Section {
                intPicker("GS Back Thread", selection: $settings.backThreadMode, options: [
'''
    if gfx.count(perf_anchor) != 1:
        raise SystemExit(
            "A15/Metal V9.6.1: Graphics Performance section anchor changed upstream."
        )

    perf_block = '''            Section {
                Toggle(settings.localized("2× Metal Presentation Scale"), isOn: $metalPresentation2x)
                Text(settings.localized("Caps only the final iOS Metal presentation surface at 2× instead of the display's native scale. PS2 internal rendering resolution is unchanged. Fully close and relaunch ARMSX2 after changing this option."))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Toggle(settings.localized("2-Frame Metal Drawable Queue"), isOn: $metalDrawableQueue2)
                Text(settings.localized("Uses two CAMetalLayer drawables instead of three to reduce final presentation queue depth and input-to-display latency. If a game becomes less smooth, turn this OFF and relaunch ARMSX2."))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                intPicker("GS Back Thread", selection: $settings.backThreadMode, options: [
'''
    gfx = gfx.replace(perf_anchor, perf_block, 1)
    graphics.write_text(gfx)

# ---------------------------------------------------------------------------
# 3) Final iOS presentation surface + CAMetalLayer queue.
# ---------------------------------------------------------------------------
im = ios_main.read_text()

if "// ARMSX2_IOS16_A15_METAL_NATIVE_V961" not in im:
    scale_re = re.compile(
        r'(?ms)^- \(CGFloat\)armsx2NativeContentScale \{.*?^\}\n'
        r'(?=- \(void\)armsx2ApplyNativeContentScale)'
    )
    matches = list(scale_re.finditer(im))
    if len(matches) != 1:
        raise SystemExit(
            f"A15/Metal V9.6.1: expected one native-scale method, found {len(matches)}."
        )

    scale_method = textwrap.dedent("""\
        // ARMSX2_IOS16_A15_METAL_NATIVE_V961
        - (CGFloat)armsx2NativeContentScale {
            UIScreen* screen = self.window.screen ?: UIScreen.mainScreen;
            CGFloat scale = screen.nativeScale > 0.0 ? screen.nativeScale : screen.scale;
            if (scale <= 0.0)
                scale = 1.0;

            NSUserDefaults* defaults = [NSUserDefaults standardUserDefaults];
            id storedValue = [defaults objectForKey:@"ARMSX2_MetalPresentation2x"];
            const BOOL use2xPresentation = storedValue ? [storedValue boolValue] : YES;
            if (use2xPresentation)
                scale = MIN(scale, (CGFloat)2.0);

            return scale;
        }
    """)
    im = scale_re.sub(scale_method, im, count=1)

    apply_re = re.compile(
        r'(?ms)^- \(void\)armsx2ApplyNativeContentScale \{.*?^\}\n'
        r'(?=- \(void\)layoutSubviews)'
    )
    matches = list(apply_re.finditer(im))
    if len(matches) != 1:
        raise SystemExit(
            f"A15/Metal V9.6.1: expected one apply-scale method, found {len(matches)}."
        )

    apply_method = textwrap.dedent("""\
        - (void)armsx2ApplyNativeContentScale {
            const CGFloat scale = [self armsx2NativeContentScale];
            self.contentScaleFactor = scale;
            self.layer.contentsScale = scale;

            CAMetalLayer* metalLayer = (CAMetalLayer*)self.layer;
            metalLayer.contentsScale = scale;

            NSUserDefaults* defaults = [NSUserDefaults standardUserDefaults];
            id queueStoredValue = [defaults objectForKey:@"ARMSX2_MetalDrawableQueue2"];
            const BOOL use2DrawableQueue =
                queueStoredValue ? [queueStoredValue boolValue] : YES;
            metalLayer.maximumDrawableCount = use2DrawableQueue ? 2 : 3;
        }
    """)
    im = apply_re.sub(apply_method, im, count=1)
    ios_main.write_text(im)

print("A15/Metal V9.6.1 patch applied successfully.")
print("  CPU target: apple-a15")
print("  2x presentation scale: switchable, default ON")
print("  2-frame CAMetalLayer drawable queue: switchable, default ON")
print("  PS2 internal rendering resolution: unchanged")
