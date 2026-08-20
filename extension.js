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
        <signal name="StateChanged"><arg type="s" name="state_json"/></signal>
        <property name="Connected" type="b" access="read"/>
        <property name="BatteryLeft" type="i" access="read"/>
        <property name="BatteryRight" type="i" access="read"/>
        <property name="BatteryCase" type="i" access="read"/>
        <property name="AncMode" type="i" access="read"/>
        <property name="AncDepth" type="i" access="read"/>
        <property name="TransparencySubmode" type="i" access="read"/>
        <property name="EqMode" type="i" access="read"/>
        <property name="ImmersiveCommute" type="i" access="read"/>
        <property name="InEarDetection" type="b" access="read"/>
        <property name="AudioMode" type="i" access="read"/>
        <property name="HeadTracking" type="b" access="read"/>
    </interface>
</node>
`);

/* ─── State ─────────────────────────────────────────────── */
let _s = {
    connected: false, battery_left: -1, battery_right: -1, battery_case: -1,
    charging_left: false, charging_right: false, charging_case: false,
    anc_mode: 0, anc_depth: 0, trans_submode: 2, eq_mode: 1,
    commute_mode: 0, in_ear_det: true, audio_mode: 0, head_tracking: false,
};

/* ─── Indicator ─────────────────────────────────────────── */
const BudsIndicator = GObject.registerClass(
class BudsIndicator extends PanelMenu.Button {

    constructor(extensionPath) {
        super(0.0, 'Redmi Buds 8 Pro');
        this._extensionPath = extensionPath;
        this._proxy = null;
        this._signalId = 0;
        this._updating = false;

        this._icon = new St.Icon({
            icon_name: 'audio-headphones-symbolic',
            style_class: 'system-status-icon',
        });
        this.add_child(this._icon);

        this._buildMenu();
        this._connectDBus();
    }

    /* ── Custom icon helper ──────────────────────────────── */
    _gicon(name) {
        let file = Gio.File.new_for_path(
            GLib.build_filenamev([this._extensionPath, 'icons', `${name}-symbolic.svg`])
        );
        return new Gio.FileIcon({ file });
    }

    /* ── D-Bus connection ────────────────────────────────── */
    async _connectDBus() {
        try {
            this._proxy = await new Promise((resolve, reject) => {
                new DBusProxy(Gio.DBus.session, DBUS_SERVICE, DBUS_PATH,
                    (p, e) => e ? reject(e) : resolve(p));
            });
            this._signalId = this._proxy.connectSignal('StateChanged',
                (_proxy, _sender, [json]) => {
                    try {
                        let parsed = JSON.parse(json);
                        Object.assign(_s, parsed);
                    } catch (e) {
                        console.error('StateChanged parse error:', e);
                    }
                    this._refreshUI();
                }
            );
            this._readFallback();
            this._refreshUI();
        } catch (e) {
            console.error('Buds D-Bus error:', e);
        }
    }

    _readFallback() {
        if (!this._proxy) return;
        try {
            _s.connected     = this._proxy.Connected     ?? false;
            _s.battery_left  = this._proxy.BatteryLeft   ?? -1;
            _s.battery_right = this._proxy.BatteryRight  ?? -1;
            _s.battery_case  = this._proxy.BatteryCase   ?? -1;
            _s.anc_mode      = this._proxy.AncMode       ?? 0;
            _s.anc_depth     = this._proxy.AncDepth      ?? 0;
            _s.trans_submode = this._proxy.TransparencySubmode ?? 2;
            _s.commute_mode  = this._proxy.ImmersiveCommute   ?? 0;
            _s.in_ear_det    = this._proxy.InEarDetection     ?? true;
            _s.audio_mode    = this._proxy.AudioMode     ?? 0;
            _s.head_tracking = this._proxy.HeadTracking  ?? false;
        } catch (_) {}
    }

    /* ── Full UI refresh ─────────────────────────────────── */
    _refreshUI() {
        this._updating = true;
        try {
            const fmt = v => (v >= 0 && v <= 100) ? `${v}%` : '--';
            this._battL.set_text(fmt(_s.battery_left));
            this._battR.set_text(fmt(_s.battery_right));
            this._battC.set_text(fmt(_s.battery_case));
            this._setActive(this._ncBtns, _s.anc_mode);
            // Conditional sub-sections
            this._ancSubRow.visible   = (_s.anc_mode === 1);
            this._smartToggle.setToggleState(_s.anc_depth === 0);
            this._sliderRow.visible   = (_s.anc_mode === 1 && _s.anc_depth !== 0);
            if (_s.anc_depth !== 0 && _s.anc_mode === 1) {
                const map = { 1: 1.0, 2: 0.5, 3: 0.0 };
                this._ancSlider.value = map[_s.anc_depth] ?? 0.5;
            }
            this._transRow.visible    = (_s.anc_mode === 2);
            this._setActive(this._transBtns, _s.trans_submode);

            // Commute
            this._setActive(this._cmBtns, _s.commute_mode);
            // Spatial
            this._setActive(this._saBtns, _s.audio_mode);
            // Head Tracking
            this._htRow.visible = (_s.audio_mode === 2);
            this._headToggle.setToggleState(_s.head_tracking);
            // In-Ear
            this._earToggle.setToggleState(_s.in_ear_det);
        } catch (e) { console.error('Refresh error:', e); }
        this._updating = false;
    }

    _setActive(btns, activeVal) {
        btns.forEach(b => {
            if (b._val === activeVal) b.add_style_class_name('active');
            else b.remove_style_class_name('active');
        });
    }

    /* ── Pill button factory ─────────────────────────────── */
    _pill(iconId, value, tooltip, cb) {
        let icon;
        // Use custom icon if it exists, otherwise fallback to system icon
        let customPath = GLib.build_filenamev([
            this._extensionPath, 'icons', `${iconId}-symbolic.svg`
        ]);
        if (GLib.file_test(customPath, GLib.FileTest.EXISTS)) {
            icon = new St.Icon({
                gicon: new Gio.FileIcon({ file: Gio.File.new_for_path(customPath) }),
                icon_size: 18, style_class: 'buds-pill-icon',
            });
        } else {
            icon = new St.Icon({
                icon_name: `${iconId}-symbolic`,
                icon_size: 18, style_class: 'buds-pill-icon',
            });
        }

        let btn = new St.Button({
            style_class: 'buds-pill-button',
            child: icon,
            can_focus: true,
            x_expand: true,
            accessible_name: tooltip,
        });
        btn._val = value;
        btn.connect('clicked', () => { if (!this._updating && this._proxy) cb(value); });

        // Tooltip on hover
        let tipLabel = null;
        btn.connect('notify::hover', () => {
            if (btn.hover) {
                if (!tipLabel) {
                    tipLabel = new St.Label({
                        text: tooltip,
                        style_class: 'buds-tooltip',
                    });
                    Main.uiGroup.add_child(tipLabel);
                }
                let [x, y] = btn.get_transformed_position();
                let bw = btn.get_width();
                tipLabel.set_position(
                    Math.round(x + bw / 2 - tipLabel.get_width() / 2),
                    Math.round(y - tipLabel.get_height() - 6)
                );
                tipLabel.show();
            } else if (tipLabel) {
                tipLabel.hide();
                Main.uiGroup.remove_child(tipLabel);
                tipLabel = null;
            }
        });

        return btn;
    }

    /* ── Build Menu ──────────────────────────────────────── */
    _buildMenu() {
        const P = PopupMenu;
        this.menu.actor.add_style_class_name('buds-menu-box');

        /* Battery */
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

        /* ── Noise Control ── */
        this._addSectionTitle('Noise Control');
        let ncItem = new P.PopupBaseMenuItem({ reactive: false });
        let ncBox  = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
        this._ncBtns = [];
        [
            ['buds-noise-off', 0, 'Off'],
            ['buds-anc',       1, 'Noise Cancellation'],
            ['buds-transparency', 2, 'Transparency'],
        ].forEach(([ic, v, t]) => {
            let b = this._pill(ic, v, t, val => this._proxy.SetAncModeRemote(val));
            ncBox.add_child(b);
            this._ncBtns.push(b);
        });
        ncItem.add_child(ncBox);
        this.menu.addMenuItem(ncItem);

        /* Smart ANC toggle */
        this._smartToggle = new P.PopupSwitchMenuItem('Smart Noise Cancelling', true);
        this._smartToggle.connect('toggled', (_, st) => {
            if (this._updating || !this._proxy) return;
            this._proxy.SetAncDepthRemote(st ? 0 : 2);
        });
        this._ancSubRow = this._smartToggle;
        this.menu.addMenuItem(this._smartToggle);

        /* ANC depth slider */
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
        slBox.add_child(this._ancSlider);
        slItem.add_child(slBox);
        this._sliderRow = slItem;
        this.menu.addMenuItem(slItem);

        /* Transparency sub-modes */
        let trItem = new P.PopupBaseMenuItem({ reactive: false });
        let trVBox = new St.BoxLayout({ vertical: true, x_expand: true });
        trVBox.add_child(new St.Label({ text: 'Transparency Level', style_class: 'buds-slider-label' }));
        let trBox = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
        this._transBtns = [];
        [
            ['buds-transparency', 2, 'Regular'],
            ['buds-voice',       0, 'Enhanced Voice'],
            ['buds-ambience',    1, 'Enhanced Ambience'],
        ].forEach(([ic, v, t]) => {
            let b = this._pill(ic, v, t, val => this._proxy.SetTransparencySubmodeRemote(val));
            trBox.add_child(b);
            this._transBtns.push(b);
        });
        trVBox.add_child(trBox);
        trItem.add_child(trVBox);
        this._transRow = trItem;
        this.menu.addMenuItem(trItem);

        this.menu.addMenuItem(new P.PopupSeparatorMenuItem());

        /* ── Immersive Commute ── */
        this._addSectionTitle('Immersive Commute');
        let cmItem = new P.PopupBaseMenuItem({ reactive: false });
        let cmBox  = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
        this._cmBtns = [];
        [
            ['buds-off',      0, 'Off'],
            ['buds-train',    1, 'Train Sound'],
            ['buds-transit',  2, 'Public Transit'],
            ['buds-airplane', 3, 'Airplane Engine'],
        ].forEach(([ic, v, t]) => {
            let b = this._pill(ic, v, t, val => this._proxy.SetImmersiveCommuteRemote(val));
            cmBox.add_child(b);
            this._cmBtns.push(b);
        });
        cmItem.add_child(cmBox);
        this.menu.addMenuItem(cmItem);
        this.menu.addMenuItem(new P.PopupSeparatorMenuItem());

        /* ── Spatial Audio ── */
        this._addSectionTitle('Spatial Audio');
        let saItem = new P.PopupBaseMenuItem({ reactive: false });
        let saBox  = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
        this._saBtns = [];
        [
            ['buds-noise-off', 0, 'Off (Stereo)'],
            ['buds-dolby',     1, 'Dolby Audio'],
            ['buds-xiaomi',    2, 'Xiaomi Immersive'],
        ].forEach(([ic, v, t]) => {
            let b = this._pill(ic, v, t, val => this._proxy.SetAudioModeRemote(val));
            saBox.add_child(b);
            this._saBtns.push(b);
        });
        saItem.add_child(saBox);
        this.menu.addMenuItem(saItem);

        /* Head Tracking */
        this._headToggle = new P.PopupSwitchMenuItem('Head Tracking', false);
        this._headToggle.connect('toggled', (_, st) => {
            if (this._updating || !this._proxy) return;
            this._proxy.SetHeadTrackingRemote(st);
        });
        this._htRow = this._headToggle;
        this.menu.addMenuItem(this._headToggle);

        this.menu.addMenuItem(new P.PopupSeparatorMenuItem());

        /* In-Ear Detection */
        this._earToggle = new P.PopupSwitchMenuItem('In-Ear Detection', true);
        this._earToggle.connect('toggled', (_, st) => {
            if (this._updating || !this._proxy) return;
            this._proxy.SetInEarDetectionRemote(st);
        });
        this.menu.addMenuItem(this._earToggle);

        /* Initial visibility */
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
        if (this._proxy && this._signalId)
            this._proxy.disconnectSignal(this._signalId);
        super.destroy();
    }
});

/* ─── Extension ─────────────────────────────────────────── */
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
