import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Slider from 'resource:///org/gnome/shell/ui/slider.js';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

const DBUS_SERVICE = 'org.redmibuds8.Control';
const DBUS_PATH    = '/org/redmibuds8/Control';

const DBusProxy = Gio.DBusProxy.makeProxyWrapper(`
<node>
    <interface name="org.redmibuds8.Control">
        <method name="SetAncMode"><arg type="i" name="mode" direction="in"/></method>
        <method name="SetAncDepth"><arg type="i" name="depth" direction="in"/></method>
        <method name="SetTransparencySubmode"><arg type="i" name="submode" direction="in"/></method>
        <method name="SetEqMode"><arg type="i" name="mode" direction="in"/></method>
        <method name="SetImmersiveCommute"><arg type="i" name="mode" direction="in"/></method>
        <method name="SetInEarDetection"><arg type="b" name="enabled" direction="in"/></method>
        <method name="SetAudioMode"><arg type="i" name="mode" direction="in"/></method>
        <method name="SetHeadTracking"><arg type="b" name="enabled" direction="in"/></method>
        <method name="SetLeMode"><arg type="b" name="enabled" direction="in"/></method>
        <signal name="StateChanged"><arg type="s" name="state_json"/></signal>
    </interface>
</node>
`);

/* ─── Shared Telemetry State ─────────────────────────────── */
let _s = {
    connected: false, battery_left: -1, battery_right: -1, battery_case: -1,
    charging_left: false, charging_right: false, charging_case: false,
    anc_mode: 0, anc_depth: 0, trans_submode: 2, eq_mode: 1,
    commute_mode: 0, in_ear_det: true, audio_mode: 0, head_tracking: false,
    le_mode: false,
};

/* ─── Indicator Button & Menu ────────────────────────────── */
const BudsIndicator = GObject.registerClass(
class BudsIndicator extends PanelMenu.Button {

    constructor(extensionPath) {
        super(0.0, 'Redmi Buds 8 Pro');
        this._extensionPath = extensionPath;
        this._proxy = null;
        this._signalId = 0;
        this._updating = false;

        this._interfaceSettings = new Gio.Settings({ schema_id: 'org.gnome.desktop.interface' });
        this._themeChangedId = this._interfaceSettings.connect('changed::color-scheme', () => {
            this._updateThemeClass();
        });
        this._gtkThemeChangedId = this._interfaceSettings.connect('changed::gtk-theme', () => {
            this._updateThemeClass();
        });

        this._icon = new St.Icon({
            icon_name: 'audio-headphones-symbolic',
            style_class: 'system-status-icon',
        });
        this.add_child(this._icon);

        this._buildMenu();
        this._connectDBus();
    }

    _gicon(name) {
        let file = Gio.File.new_for_path(
            GLib.build_filenamev([this._extensionPath, 'icons', `${name}-symbolic.svg`])
        );
        return new Gio.FileIcon({ file });
    }

    async _connectDBus() {
        try {
            this._proxy = await new Promise((resolve, reject) => {
                new DBusProxy(Gio.DBus.session, DBUS_SERVICE, DBUS_PATH,
                    (p, e) => e ? reject(e) : resolve(p));
            });
            this._signalId = this._proxy.connectSignal('StateChanged',
                (_proxy, _sender, [json]) => {
                    try {
                        Object.assign(_s, JSON.parse(json));
                    } catch (e) {
                        console.error('StateChanged parse error:', e);
                    }
                    this._refreshUI();
                }
            );
            this._refreshUI();
        } catch (e) {
            console.error('Buds D-Bus connection error:', e);
        }
    }

    _isLightMode() {
        try {
            let scheme = this._interfaceSettings ? this._interfaceSettings.get_string('color-scheme') : 'default';
            // In GNOME: 'prefer-dark' is dark mode; 'default' or 'prefer-light' is light mode
            if (scheme === 'prefer-dark')
                return false;
            if (scheme === 'prefer-light' || scheme === 'default')
                return true;

            // Fallback for custom GTK themes
            let gtkTheme = (this._interfaceSettings ? this._interfaceSettings.get_string('gtk-theme') : '').toLowerCase();
            return !gtkTheme.includes('dark');
        } catch (_) {
            return false;
        }
    }

    _updateThemeClass() {
        let isLight = this._isLightMode();
        let addClass = isLight ? 'light-theme' : 'dark-theme';
        let removeClass = isLight ? 'dark-theme' : 'light-theme';

        if (this.menu && this.menu.actor) {
            this.menu.actor.remove_style_class_name(removeClass);
            this.menu.actor.add_style_class_name(addClass);
        }
        if (this.menu && this.menu.box) {
            this.menu.box.remove_style_class_name(removeClass);
            this.menu.box.add_style_class_name(addClass);
        }
    }

    _refreshUI() {
        this._updating = true;
        try {
            this._updateThemeClass();
            const fmt = v => (v >= 0 && v <= 100) ? `${v}%` : '--';
            this._battL.set_text(fmt(_s.battery_left));
            this._battR.set_text(fmt(_s.battery_right));
            this._battC.set_text(fmt(_s.battery_case));

            // Noise Control
            this._setActive(this._ncBtns, _s.anc_mode);
            this._ancSubRow.visible = (_s.anc_mode === 1);
            this._smartToggle.setToggleState(_s.anc_depth === 0);
            this._sliderRow.visible = (_s.anc_mode === 1 && _s.anc_depth !== 0);
            if (_s.anc_depth !== 0 && _s.anc_mode === 1) {
                const map = { 1: 1.0, 2: 0.5, 3: 0.0 };
                this._ancSlider.value = map[_s.anc_depth] ?? 0.5;
            }
            this._transRow.visible = (_s.anc_mode === 2);
            this._setActive(this._transBtns, _s.trans_submode);

            // Commute & Spatial
            this._setActive(this._cmBtns, _s.commute_mode);
            this._setActive(this._saBtns, _s.audio_mode);

            // Head Tracking & Device Settings
            this._htRow.visible = (_s.audio_mode === 2);
            this._headToggle.setToggleState(_s.head_tracking);
            this._leToggle.setToggleState(_s.le_mode);
            this._earToggle.setToggleState(_s.in_ear_det);
        } catch (e) {
            console.error('Refresh error:', e);
        }
        this._updating = false;
    }

    _setActive(btns, activeVal) {
        btns.forEach(b => {
            if (b._val === activeVal) b.add_style_class_name('active');
            else b.remove_style_class_name('active');
        });
    }

    /* ── 2D Keyboard Grid Navigation ──────────────────────── */
    _getVisibleRows() {
        let rows = [this._ncBtns];
        if (this._ancSubRow && this._ancSubRow.visible) rows.push([this._smartToggle]);
        if (this._sliderRow && this._sliderRow.visible) rows.push([this._ancSlider]);
        if (this._transRow && this._transRow.visible) rows.push(this._transBtns);
        rows.push(this._cmBtns);
        rows.push(this._saBtns);
        if (this._htRow && this._htRow.visible) rows.push([this._headToggle]);
        rows.push([this._leToggle]);
        rows.push([this._earToggle]);
        return rows;
    }

    _setupKeyNav(widget) {
        widget.can_focus = true;
        widget.track_hover = true;
        widget.connect('key-press-event', (actor, event) => {
            let symbol = event.get_key_symbol();

            if (widget === this._ancSlider) {
                if (symbol === Clutter.KEY_Left) {
                    this._ancSlider.value = Math.max(0.0, this._ancSlider.value - 0.5);
                    return Clutter.EVENT_STOP;
                } else if (symbol === Clutter.KEY_Right) {
                    this._ancSlider.value = Math.min(1.0, this._ancSlider.value + 0.5);
                    return Clutter.EVENT_STOP;
                }
            }

            if (symbol === Clutter.KEY_Right) {
                this._navigateGrid(actor, 0, 1);
            } else if (symbol === Clutter.KEY_Left) {
                this._navigateGrid(actor, 0, -1);
            } else if (symbol === Clutter.KEY_Down || symbol === Clutter.KEY_Tab) {
                this._navigateGrid(actor, 1, 0);
            } else if (symbol === Clutter.KEY_Up || symbol === Clutter.KEY_ISO_Left_Tab) {
                this._navigateGrid(actor, -1, 0);
            } else if (symbol === Clutter.KEY_Return || symbol === Clutter.KEY_space || symbol === Clutter.KEY_KP_Enter) {
                if (widget instanceof St.Button) {
                    widget.emit('clicked');
                } else if (typeof widget.toggle === 'function') {
                    widget.toggle();
                } else if (widget._switch) {
                    widget.toggle();
                }
            } else if (symbol === Clutter.KEY_Escape) {
                this.menu.close();
            }
            return Clutter.EVENT_STOP;
        });
    }

    _navigateGrid(currentActor, rowDelta, colDelta) {
        let rows = this._getVisibleRows();
        if (rows.length === 0) return;

        let curRowIdx = -1;
        let curColIdx = -1;
        for (let r = 0; r < rows.length; r++) {
            let col = rows[r].indexOf(currentActor);
            if (col !== -1) {
                curRowIdx = r;
                curColIdx = col;
                break;
            }
        }

        if (curRowIdx === -1) {
            this._focusFirstWidget();
            return;
        }

        if (colDelta !== 0) {
            let curRow = rows[curRowIdx];
            let nextCol = (curColIdx + colDelta + curRow.length) % curRow.length;
            curRow[nextCol].grab_key_focus();
        } else if (rowDelta !== 0) {
            let nextRowIdx = (curRowIdx + rowDelta + rows.length) % rows.length;
            let nextRow = rows[nextRowIdx];
            let targetCol = Math.min(curColIdx, nextRow.length - 1);
            nextRow[targetCol].grab_key_focus();
        }
    }

    _focusFirstWidget() {
        let rows = this._getVisibleRows();
        if (rows.length > 0 && rows[0].length > 0) {
            rows[0][0].grab_key_focus();
        }
    }

    /* ── Pill Button Factory ─────────────────────────────── */
    _pill(iconId, value, tooltip, cb) {
        let customPath = GLib.build_filenamev([
            this._extensionPath, 'icons', `${iconId}-symbolic.svg`
        ]);
        let icon = GLib.file_test(customPath, GLib.FileTest.EXISTS)
            ? new St.Icon({ gicon: new Gio.FileIcon({ file: Gio.File.new_for_path(customPath) }), icon_size: 18, style_class: 'buds-pill-icon' })
            : new St.Icon({ icon_name: `${iconId}-symbolic`, icon_size: 18, style_class: 'buds-pill-icon' });

        let btn = new St.Button({
            style_class: 'buds-pill-button',
            child: icon,
            can_focus: true,
            x_expand: true,
            accessible_name: tooltip,
        });
        btn._val = value;
        btn.connect('clicked', () => { if (!this._updating && this._proxy) cb(value); });

        let tipLabel = null;
        btn.connect('notify::hover', () => {
            if (btn.hover) {
                if (!tipLabel) {
                    tipLabel = new St.Label({ text: tooltip, style_class: 'buds-tooltip' });
                    Main.uiGroup.add_child(tipLabel);
                }
                let [x, y] = btn.get_transformed_position();
                let bw = btn.get_width();
                tipLabel.set_position(Math.round(x + bw / 2 - tipLabel.get_width() / 2), Math.round(y - tipLabel.get_height() - 6));
                tipLabel.show();
            } else if (tipLabel) {
                tipLabel.hide();
                Main.uiGroup.remove_child(tipLabel);
                tipLabel = null;
            }
        });

        this._setupKeyNav(btn);
        return btn;
    }

    /* ── Menu Construction ───────────────────────────────── */
    _buildMenu() {
        const P = PopupMenu;
        this.menu.actor.add_style_class_name('buds-menu-box');
        this.menu.box.add_style_class_name('buds-menu-box');
        this._updateThemeClass();

        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open) {
                this._updateThemeClass();
                GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                    this._focusFirstWidget();
                    return GLib.SOURCE_REMOVE;
                });
            }
        });

        /* Battery Telemetry Row */
        let bItem = new P.PopupBaseMenuItem({ reactive: false });
        let bBox  = new St.BoxLayout({ style_class: 'buds-battery-row', x_expand: true });

        bBox.add_child(new St.Icon({ gicon: this._gicon('buds-earbud-left'), icon_size: 14, style_class: 'buds-batt-icon' }));
        this._battL = new St.Label({ text: '--', style_class: 'buds-battery-value', y_align: Clutter.ActorAlign.CENTER });
        bBox.add_child(this._battL);

        bBox.add_child(new St.Icon({ gicon: this._gicon('buds-case'), icon_size: 14, style_class: 'buds-batt-icon buds-batt-sep' }));
        this._battC = new St.Label({ text: '--', style_class: 'buds-battery-value', y_align: Clutter.ActorAlign.CENTER });
        bBox.add_child(this._battC);

        bBox.add_child(new St.Icon({ gicon: this._gicon('buds-earbud-right'), icon_size: 14, style_class: 'buds-batt-icon buds-batt-sep' }));
        this._battR = new St.Label({ text: '--', style_class: 'buds-battery-value', y_align: Clutter.ActorAlign.CENTER });
        bBox.add_child(this._battR);

        bItem.add_child(bBox);
        this.menu.addMenuItem(bItem);
        this.menu.addMenuItem(new P.PopupSeparatorMenuItem());

        /* Noise Control Section */
        this._addSectionTitle('Noise Control');
        let ncItem = new P.PopupBaseMenuItem({ reactive: false });
        let ncBox  = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
        this._ncBtns = [
            ['buds-noise-off', 0, 'Off'],
            ['buds-anc', 1, 'Noise Cancellation'],
            ['buds-transparency', 2, 'Transparency'],
        ].map(([ic, v, t]) => {
            let b = this._pill(ic, v, t, val => this._proxy.SetAncModeRemote(val));
            ncBox.add_child(b);
            return b;
        });
        ncItem.add_child(ncBox);
        this.menu.addMenuItem(ncItem);

        /* Smart ANC Switch */
        this._smartToggle = new P.PopupSwitchMenuItem('Smart Noise Cancelling', true);
        this._smartToggle.connect('toggled', (_, st) => {
            if (this._updating || !this._proxy) return;
            this._proxy.SetAncDepthRemote(st ? 0 : 2);
        });
        this._setupKeyNav(this._smartToggle);
        this._ancSubRow = this._smartToggle;
        this.menu.addMenuItem(this._smartToggle);

        /* ANC Depth Slider */
        let slItem = new P.PopupBaseMenuItem({ reactive: false });
        let slBox  = new St.BoxLayout({ vertical: true, x_expand: true, style_class: 'buds-slider-box' });
        slBox.add_child(new St.Label({ text: 'Noise Cancelling Level', style_class: 'buds-slider-label' }));
        this._ancSlider = new Slider.Slider(0.5);
        this._ancSlider.connect('notify::value', () => {
            if (this._updating || !this._proxy) return;
            let v = this._ancSlider.value;
            let d = v < 0.25 ? 3 : v < 0.75 ? 2 : 1;
            this._proxy.SetAncDepthRemote(d);
        });
        this._setupKeyNav(this._ancSlider);
        slBox.add_child(this._ancSlider);
        slItem.add_child(slBox);
        this._sliderRow = slItem;
        this.menu.addMenuItem(slItem);

        /* Transparency Sub-modes */
        let trItem = new P.PopupBaseMenuItem({ reactive: false });
        let trVBox = new St.BoxLayout({ vertical: true, x_expand: true });
        trVBox.add_child(new St.Label({ text: 'Transparency Level', style_class: 'buds-slider-label' }));
        let trBox = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
        this._transBtns = [
            ['buds-transparency', 2, 'Regular'],
            ['buds-voice', 0, 'Enhanced Voice'],
            ['buds-ambience', 1, 'Enhanced Ambience'],
        ].map(([ic, v, t]) => {
            let b = this._pill(ic, v, t, val => this._proxy.SetTransparencySubmodeRemote(val));
            trBox.add_child(b);
            return b;
        });
        trVBox.add_child(trBox);
        trItem.add_child(trVBox);
        this._transRow = trItem;
        this.menu.addMenuItem(trItem);

        this.menu.addMenuItem(new P.PopupSeparatorMenuItem());

        /* Immersive Commute Section */
        this._addSectionTitle('Immersive Commute');
        let cmItem = new P.PopupBaseMenuItem({ reactive: false });
        let cmBox  = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
        this._cmBtns = [
            ['buds-off', 0, 'Off'],
            ['buds-train', 1, 'Train Sound'],
            ['buds-transit', 2, 'Public Transit'],
            ['buds-airplane', 3, 'Airplane Engine'],
        ].map(([ic, v, t]) => {
            let b = this._pill(ic, v, t, val => this._proxy.SetImmersiveCommuteRemote(val));
            cmBox.add_child(b);
            return b;
        });
        cmItem.add_child(cmBox);
        this.menu.addMenuItem(cmItem);
        this.menu.addMenuItem(new P.PopupSeparatorMenuItem());

        /* Spatial Audio Section */
        this._addSectionTitle('Spatial Audio');
        let saItem = new P.PopupBaseMenuItem({ reactive: false });
        let saBox  = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
        this._saBtns = [
            ['buds-noise-off', 0, 'Off (Stereo)'],
            ['buds-dolby', 1, 'Dolby Audio'],
            ['buds-xiaomi', 2, 'Xiaomi Immersive'],
        ].map(([ic, v, t]) => {
            let b = this._pill(ic, v, t, val => this._proxy.SetAudioModeRemote(val));
            saBox.add_child(b);
            return b;
        });
        saItem.add_child(saBox);
        this.menu.addMenuItem(saItem);

        /* Head Tracking Switch */
        this._headToggle = new P.PopupSwitchMenuItem('Head Tracking', false);
        this._headToggle.connect('toggled', (_, st) => {
            if (this._updating || !this._proxy) return;
            this._proxy.SetHeadTrackingRemote(st);
        });
        this._setupKeyNav(this._headToggle);
        this._htRow = this._headToggle;
        this.menu.addMenuItem(this._headToggle);

        this.menu.addMenuItem(new P.PopupSeparatorMenuItem());

        /* Device Settings Section */
        this._addSectionTitle('Device Settings');

        /* LE Mode Switch */
        this._leToggle = new P.PopupSwitchMenuItem('LE Mode (Low Latency)', false);
        this._leToggle.connect('toggled', (_, st) => {
            if (this._updating || !this._proxy) return;
            this._proxy.SetLeModeRemote(st);
            let soundFile = st ? 'le_on.wav' : 'le_off.wav';
            let soundPath = GLib.build_filenamev([this._extensionPath, 'sounds', soundFile]);
            if (GLib.file_test(soundPath, GLib.FileTest.EXISTS)) {
                GLib.spawn_command_line_async(`paplay "${soundPath}"`);
            }
        });
        this._setupKeyNav(this._leToggle);
        this.menu.addMenuItem(this._leToggle);

        /* In-Ear Detection Switch */
        this._earToggle = new P.PopupSwitchMenuItem('In-Ear Detection', true);
        this._earToggle.connect('toggled', (_, st) => {
            if (this._updating || !this._proxy) return;
            this._proxy.SetInEarDetectionRemote(st);
        });
        this._setupKeyNav(this._earToggle);
        this.menu.addMenuItem(this._earToggle);

        /* Initial Visibility */
        this._ancSubRow.visible = false;
        this._sliderRow.visible = false;
        this._transRow.visible  = false;
        this._htRow.visible     = false;
    }

    _addSectionTitle(text) {
        let item = new PopupMenu.PopupBaseMenuItem({ reactive: false });
        item.add_child(new St.Label({ text, style_class: 'buds-section-title', x_expand: true }));
        this.menu.addMenuItem(item);
    }

    destroy() {
        if (this._interfaceSettings) {
            if (this._themeChangedId) {
                this._interfaceSettings.disconnect(this._themeChangedId);
                this._themeChangedId = 0;
            }
            if (this._gtkThemeChangedId) {
                this._interfaceSettings.disconnect(this._gtkThemeChangedId);
                this._gtkThemeChangedId = 0;
            }
            this._interfaceSettings = null;
        }
        if (this._proxy && this._signalId) {
            this._proxy.disconnectSignal(this._signalId);
            this._signalId = 0;
        }
        super.destroy();
    }
});

/* ─── Main Extension Entry Point ─────────────────────────── */
export default class BudsExtension extends Extension {
    enable() {
        this._indicator = new BudsIndicator(this.path);
        Main.panel.addToStatusArea(this.uuid, this._indicator);

        try {
            this._settings = this.getSettings();
            Main.wm.addKeybinding(
                'toggle-menu',
                this._settings,
                Meta.KeyBindingFlags.NONE,
                Shell.ActionMode.ALL,
                () => { this._indicator?.menu.toggle(); }
            );
        } catch (e) {
            console.error('Keybinding error:', e);
        }
    }

    disable() {
        try { Main.wm.removeKeybinding('toggle-menu'); } catch (_) {}
        this._indicator?.destroy();
        this._indicator = null;
        this._settings = null;
    }
}
