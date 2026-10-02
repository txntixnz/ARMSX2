from pathlib import Path
import re

root = Path("platforms/ios/app/src/main/swift")
helper = root / "Views/IOS16Compatibility.swift"

if not helper.is_file():
    raise SystemExit("V9.6.5: IOS16Compatibility.swift must be generated first")

def exact_replace(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"V9.6.5: {label} expected once, found {n}")
    return text.replace(old, new, 1)

def remove_modifier(text, name):
    """Remove complete chained call, including multiline argument lists."""
    pat = re.compile(r"\." + re.escape(name) + r"\s*\(")
    pos = 0
    n = 0
    while True:
        m = pat.search(text, pos)
        if not m:
            break
        j, depth = m.end(), 1
        quote = False
        escape = False
        while j < len(text) and depth:
            ch = text[j]
            if quote:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    quote = False
            else:
                if ch == '"':
                    quote = True
                elif ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
            j += 1
        if depth:
            raise SystemExit(f"V9.6.5: unbalanced .{name} call")
        text = text[:m.start()] + text[j:]
        pos = m.start()
        n += 1
    return text, n

# The original backport handled the old two-argument syntax, but upstream now
# uses iOS 17's initial: flag and splits many onChange calls across lines.
# Convert the latter to our existing compatibility name, and implement initial:.
h = helper.read_text()
marker = "// ARMSX2_IOS16_INITIAL_ONCHANGE_V965"
if marker not in h:
    h += """
// ARMSX2_IOS16_INITIAL_ONCHANGE_V965
private struct IOS16InitialTwoValueOnChangeModifier<Value: Equatable>: ViewModifier {
    let value: Value
    let initial: Bool
    let action: (Value, Value) -> Void
    @State private var previous: Value?

    func body(content: Content) -> some View {
        content
            .onAppear {
                previous = value
                if initial { action(value, value) }
            }
            .onChange(of: value) { newValue in
                let oldValue = previous ?? newValue
                previous = newValue
                action(oldValue, newValue)
            }
    }
}

extension View {
    func ios16OnChange<Value: Equatable>(
        of value: Value, initial: Bool,
        _ action: @escaping (Value, Value) -> Void
    ) -> some View {
        modifier(IOS16InitialTwoValueOnChangeModifier(
            value: value, initial: initial, action: action
        ))
    }

    func ios16OnChange<Value: Equatable>(
        of value: Value, initial: Bool,
        _ action: @escaping (Value) -> Void
    ) -> some View {
        self
            .onAppear { if initial { action(value) } }
            .onChange(of: value, perform: action)
    }
}
"""
    helper.write_text(h)

# Navigation destination by optional item arrived in iOS 17; on iOS 16 the
# same NavigationStack destination can be presented with an isPresented binding.
h = helper.read_text()
navigation_marker = "// ARMSX2_IOS16_ITEM_NAV_DEST_V965"
if navigation_marker not in h:
    h += """
// ARMSX2_IOS16_ITEM_NAV_DEST_V965
extension View {
    func ios16NavigationDestination<Item: Identifiable, Destination: View>(
        item: Binding<Item?>,
        @ViewBuilder destination: @escaping (Item) -> Destination
    ) -> some View {
        navigationDestination(isPresented: Binding(
            get: { item.wrappedValue != nil },
            set: { if !$0 { item.wrappedValue = nil } }
        )) {
            if let selected = item.wrappedValue {
                destination(selected)
            }
        }
    }
}
"""
    helper.write_text(h)

counts = {}
for path in root.rglob("*.swift"):
    if path == helper:
        continue
    source = path.read_text()
    original = source

    # Existing workflow replaced the single-line form; include a line break
    # between '(' and 'of:' too, as used in recently updated menu views.
    source, count = re.subn(r"\.onChange\s*\(\s*of\s*:", ".ios16OnChange(of:", source)
    if count:
        counts["multiline onChange"] = counts.get("multiline onChange", 0) + count

    # Map navigationDestination(item:) to iOS 16 NavigationStack compatible
    # optional-item navigation. Preserve the actual destination view.
    source, n = re.subn(r"\.navigationDestination\s*\(\s*item\s*:",
                        ".ios16NavigationDestination(item:", source)
    if n:
        counts["item navigation destination"] = counts.get("item navigation destination", 0) + n

    # iOS 17 presentation/focus modifiers are nonessential to gameplay and
    # fail deployment availability checks on iOS 16.
    for name in ("focusEffectDisabled", "focusable", "scrollTargetLayout",
                 "scrollPosition", "buttonRepeatBehavior", "buttonBorderShape"):
        if name == "focusable":
            # Only remove explicit false (iOS 17 API); leave other variants.
            source, n = re.subn(r"\.focusable\s*\(\s*false\s*\)", "", source)
        else:
            source, n = remove_modifier(source, name)
        if n:
            counts[name] = counts.get(name, 0) + n

    if path.name == "SaveStateSlots.swift":
        old = "if let announcement { AccessibilityNotification.Announcement(announcement).post() }"
        if old in source:
            source = source.replace(
                old,
                "if let announcement { UIAccessibility.post(notification: .announcement, argument: announcement) }",
                1
            )

    if path.name == "MenuThemePresetShortcutOverlay.swift":
        source, n = re.subn(
            r"(?s)private struct ThemePresetFocusAnimation: CustomAnimation \{.*?\n\}\n\n",
            "", source, count=1
        )
        if n != 1:
            raise SystemExit("V9.6.5: ThemePresetFocusAnimation layout changed")
        source = exact_replace(
            source,
            """return Animation(ThemePresetFocusAnimation(
            style: settings.controllerNavigationFocusAnimation
        ))""",
            "return .easeInOut(duration: settings.controllerNavigationFocusAnimation.duration)",
            "theme animation")
        counts["iOS17 custom animation"] = 1

    if path.name == "GameListView.swift":
        # This listener grew many onChange overloads in the new upstream.
        # Split its view-builder chain to avoid pathological iOS 16 type
        # inference on one very long generic expression.
        start = (
            "private struct GameLibraryControllerCommandListener: View {"
        )
        if start in source:
            before, listener = source.split(start, 1)
            old_head = (
                "    var body: some View {\n"
                "        Color.clear\n"
            )
            old_tail = (
                "            .ios16OnChange(of: controllerInput?.navigationZone, initial: true)"
            )
            if old_head not in listener or old_tail not in listener:
                raise SystemExit("V9.6.5: GameLibraryControllerCommandListener layout changed")
            listener = listener.replace(
                old_head,
                "    var body: some View {\n        let listenerBase = Color.clear\n", 1
            )
            listener = listener.replace(old_tail, "        return listenerBase\n" + old_tail, 1)
            source = before + start + listener
            counts["split GameList listener chain"] = 1

    if path.name == "MenuControllerInputRouter.swift":
        # Observation backport's line-only property parser sees the opening '{'
        # of this multiline *computed* property too late and wrongly adds Published.
        source, n = re.subn(
            r"@Published\s+(?=private\s+var\s+frontmostNavigationSessionEntry\s*:)",
            "", source, count=1
        )
        if n:
            counts["computed property Published"] = n

    if source != original:
        path.write_text(source)

print("V9.6.5 upstream SwiftUI/iOS16 compatibility patch complete:")
for k, v in sorted(counts.items()):
    print(f"  {k}: {v}")
