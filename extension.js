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
        <method name="SetDualConnection"><arg type="b" name="enabled" direction="in"/></method>
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
    le_mode: false, dual_connect: true,
};

/* ─── Declarative Features Schema ────────────────────────── */
const FEATURES = [
    {
        id: 'noise_control',
        title: 'Noise Control',
        type: 'pill_group',
        get: s => s.anc_mode,
        set: (proxy, val) => proxy.SetAncModeRemote(val),
        items: [
            { icon: 'buds-noise-off', value: 0, title: 'Off' },
            { icon: 'buds-anc', value: 1, title: 'Noise Cancellation' },
            { icon: 'buds-transparency', value: 2, title: 'Transparency' },
        ],
        subControls: [
            {
                id: 'smart_anc',
                type: 'switch',
                label: 'Smart Noise Cancelling',
                condition: s => s.anc_mode === 1,
                get: s => s.anc_depth === 0,
                set: (proxy, st) => proxy.SetAncDepthRemote(st ? 0 : 2),
            },
            {
                id: 'anc_depth_slider',
                type: 'slider',
                label: 'Noise Cancelling Level',
                condition: s => s.anc_mode === 1 && s.anc_depth !== 0,
                get: s => ({ 1: 1.0, 2: 0.5, 3: 0.0 }[s.anc_depth] ?? 0.5),
                set: (proxy, v) => {
                    let d = v < 0.25 ? 3 : v < 0.75 ? 2 : 1;
                    proxy.SetAncDepthRemote(d);
                },
            },
            {
                id: 'transparency_submodes',
                type: 'pill_group',
                label: 'Transparency Level',
                condition: s => s.anc_mode === 2,
                get: s => s.trans_submode,
                set: (proxy, val) => proxy.SetTransparencySubmodeRemote(val),
                items: [
                    { icon: 'buds-transparency', value: 2, title: 'Regular' },
                    { icon: 'buds-voice', value: 0, title: 'Enhanced Voice' },
                    { icon: 'buds-ambience', value: 1, title: 'Enhanced Ambience' },
                ],
            },
        ],
    },
    {
        id: 'commute_mode',
        title: 'Immersive Commute',
        type: 'pill_group',
        get: s => s.commute_mode,
        set: (proxy, val) => proxy.SetImmersiveCommuteRemote(val),
        items: [
            { icon: 'buds-off', value: 0, title: 'Off' },
            { icon: 'buds-train', value: 1, title: 'Train Sound' },
            { icon: 'buds-transit', value: 2, title: 'Public Transit' },
            { icon: 'buds-airplane', value: 3, title: 'Airplane Engine' },
        ],
    },
    {
        id: 'spatial_audio',
        title: 'Spatial Audio',
        type: 'pill_group',
        get: s => s.audio_mode,
        set: (proxy, val) => proxy.SetAudioModeRemote(val),
        items: [
            { icon: 'buds-stereo', value: 0, title: 'Off (Stereo)' },
            { icon: 'buds-dolby', value: 1, title: 'Dolby Audio' },
            { icon: 'buds-xiaomi', value: 2, title: 'Xiaomi Immersive' },
        ],
        subControls: [
            {
                id: 'head_tracking',
                type: 'switch',
                label: 'Head Tracking',
                condition: s => s.audio_mode === 2,
                get: s => s.head_tracking,
                set: (proxy, st) => proxy.SetHeadTrackingRemote(st),
            },
        ],
    },
    {
        id: 'device_settings',
        title: 'Device Settings',
        type: 'switches',
        items: [
            {
                id: 'le_mode',
                label: 'LE Mode (Low Latency)',
                get: s => s.le_mode,
                set: (proxy, st, ctx) => {
                    proxy.SetLeModeRemote(st);
                    let soundFile = st ? 'le_on.wav' : 'le_off.wav';
                    let soundPath = GLib.build_filenamev([ctx._extensionPath, 'sounds', soundFile]);
                    if (GLib.file_test(soundPath, GLib.FileTest.EXISTS)) {
                        GLib.spawn_command_line_async(`paplay "${soundPath}"`);
                    }
                },
            },
            {
                id: 'dual_connect',
                label: 'Dual Connection',
                get: s => s.dual_connect,
                set: (proxy, st) => proxy.SetDualConnectionRemote(st),
            },
            {
                id: 'in_ear_det',
                label: 'In-Ear Detection',
                get: s => s.in_ear_det,
                set: (proxy, st) => proxy.SetInEarDetectionRemote(st),
            },
        ],
    },
];

/* ─── Control Adapter Classes ────────────────────────────── */
class PillGroupControl {
    constructor(actor, buttons, config) {
        this.actor = actor;
        this.buttons = buttons;
        this.config = config;
    }
    isVisible() {
        return this.actor.visible;
    }
    getNavWidgets() {
        return this.buttons;
    }
    sync(state) {
        if (typeof this.config.condition === 'function') {
            this.actor.visible = Boolean(this.config.condition(state));
        }
        if (this.isVisible() && typeof this.config.get === 'function') {
            let activeVal = this.config.get(state);
            this.buttons.forEach(b => {
                if (b._val === activeVal) b.add_style_class_name('active');
                else b.remove_style_class_name('active');
            });
        }
    }
}

class SwitchControl {
    constructor(actor, config) {
        this.actor = actor;
        this.config = config;
    }
    isVisible() {
        return this.actor.visible;
    }
    getNavWidgets() {
        return [this.actor];
    }
    sync(state) {
        if (typeof this.config.condition === 'function') {
            this.actor.visible = Boolean(this.config.condition(state));
        }
        if (this.isVisible() && typeof this.config.get === 'function') {
            this.actor.setToggleState(Boolean(this.config.get(state)));
        }
    }
}

class SliderControl {
    constructor(actor, slider, config) {
        this.actor = actor;
        this.slider = slider;
        this.config = config;
    }
    isVisible() {
        return this.actor.visible;
    }
    getNavWidgets() {
        return [this.slider];
    }
    sync(state) {
        if (typeof this.config.condition === 'function') {
            this.actor.visible = Boolean(this.config.condition(state));
        }
        if (this.isVisible() && typeof this.config.get === 'function') {
            this.slider.value = this.config.get(state);
        }
    }
}

/* ─── Main Indicator & Panel Menu ────────────────────────── */
const BudsIndicator = GObject.registerClass(
class BudsIndicator extends PanelMenu.Button {

    constructor(extensionPath) {
        super(0.0, 'Redmi Buds 8 Pro');
        this._extensionPath = extensionPath;
        this._proxy = null;
        this._signalId = 0;
        this._updating = false;
        this._controls = [];

        this._interfaceSettings = new Gio.Settings({ schema_id: 'org.gnome.desktop.interface' });
        this._themeChangedId = this._interfaceSettings.connect('changed::color-scheme', () => {
            this._updateThemeClass();
        });
        this._gtkThemeChangedId = this._interfaceSettings.connect('changed::gtk-theme', () => {
            this._updateThemeClass();
        });

        // Register custom icons directory with St.IconTheme
        let iconTheme = new St.IconTheme();
        let iconDir = GLib.build_filenamev([this._extensionPath, 'icons']);
        if (!iconTheme.get_search_path().includes(iconDir)) {
            iconTheme.prepend_search_path(iconDir);
        }

        this._icon = new St.Icon({
            icon_name: 'audio-headphones-symbolic',
            style_class: 'system-status-icon',
        });
        this.add_child(this._icon);
        this.visible = false;

        this._buildMenu();
        this._connectDBus();
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
            if (scheme === 'prefer-dark') return false;
            if (scheme === 'prefer-light' || scheme === 'default') return true;
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
            this.visible = Boolean(_s.connected);
            this._updateThemeClass();

            const fmt = (v, chg) => {
                if (v >= 0 && v <= 100)
                    return chg ? `⚡ ${v}%` : `${v}%`;
                return '--';
            };
            this._battL.set_text(fmt(_s.battery_left, _s.charging_left));
            this._battC.set_text(fmt(_s.battery_case, _s.charging_case));
            this._battR.set_text(fmt(_s.battery_right, _s.charging_right));

            if (this._badgeL) {
                if (_s.charging_left) this._badgeL.add_style_class_name('charging');
                else this._badgeL.remove_style_class_name('charging');
            }
            if (this._badgeC) {
                if (_s.charging_case) this._badgeC.add_style_class_name('charging');
                else this._badgeC.remove_style_class_name('charging');
            }
            if (this._badgeR) {
                if (_s.charging_right) this._badgeR.add_style_class_name('charging');
                else this._badgeR.remove_style_class_name('charging');
            }

            // Sync all declarative controls
            for (let ctrl of this._controls) {
                ctrl.sync(_s);
            }
        } catch (e) {
            console.error('Refresh error:', e);
        }
        this._updating = false;
    }

    /* ── 2D Keyboard Grid Navigation ──────────────────────── */
    _getVisibleRows() {
        let rows = [];
        for (let ctrl of this._controls) {
            if (ctrl.isVisible()) {
                let widgets = ctrl.getNavWidgets();
                if (widgets && widgets.length > 0) {
                    rows.push(widgets);
                }
            }
        }
        return rows;
    }

    _setupKeyNav(widget) {
        widget.can_focus = true;
        widget.track_hover = true;
        widget.connect('key-press-event', (actor, event) => {
            let symbol = event.get_key_symbol();

            if (widget instanceof Slider.Slider) {
                if (symbol === Clutter.KEY_Left) {
                    widget.value = Math.max(0.0, widget.value - 0.5);
                    return Clutter.EVENT_STOP;
                } else if (symbol === Clutter.KEY_Right) {
                    widget.value = Math.min(1.0, widget.value + 0.5);
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
                    widget.emit('clicked', Clutter.BUTTON_PRIMARY);
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
        let icon = new St.Icon({
            icon_name: `${iconId}-symbolic`,
            icon_size: 18,
            style_class: 'buds-pill-icon',
        });

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

    /* ── Declarative Menu Construction ───────────────────── */
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

        /* Battery Telemetry Hero Badges */
        let bItem = new P.PopupBaseMenuItem({ reactive: false, can_focus: false });
        let bBox  = new St.BoxLayout({ style_class: 'buds-battery-row', x_expand: true });

        const createBattBadge = (iconName) => {
            let badge = new St.BoxLayout({
                style_class: 'buds-batt-badge',
                x_expand: true,
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
            });
            let icon = new St.Icon({
                icon_name: `${iconName}-symbolic`,
                icon_size: 16,
                style_class: 'buds-batt-icon',
                y_align: Clutter.ActorAlign.CENTER,
            });
            let val = new St.Label({
                text: '--',
                style_class: 'buds-battery-value',
                y_align: Clutter.ActorAlign.CENTER,
            });
            badge.add_child(icon);
            badge.add_child(val);
            return [badge, val];
        };

        [this._badgeL, this._battL] = createBattBadge('buds-earbud-left');
        [this._badgeC, this._battC] = createBattBadge('buds-case');
        [this._badgeR, this._battR] = createBattBadge('buds-earbud-right');

        bBox.add_child(this._badgeL);
        bBox.add_child(this._badgeC);
        bBox.add_child(this._badgeR);

        bItem.add_child(bBox);
        this.menu.addMenuItem(bItem);

        /* Build Features from Declarative Schema */
        FEATURES.forEach((feature, idx) => {
            this.menu.addMenuItem(new P.PopupSeparatorMenuItem());
            if (feature.title) {
                this._addSectionTitle(feature.title);
            }

            if (feature.type === 'pill_group') {
                this._buildPillGroup(feature);
            } else if (feature.type === 'switches') {
                feature.items.forEach(sw => this._buildSwitch(sw));
            }

            // Build any conditional sub-controls for this section
            if (Array.isArray(feature.subControls)) {
                feature.subControls.forEach(sub => {
                    if (sub.type === 'switch') {
                        this._buildSwitch(sub);
                    } else if (sub.type === 'slider') {
                        this._buildSlider(sub);
                    } else if (sub.type === 'pill_group') {
                        this._buildPillGroup(sub);
                    }
                });
            }
        });
    }

    _buildPillGroup(config) {
        const P = PopupMenu;
        let item = new P.PopupBaseMenuItem({ reactive: false });
        let container = item;

        if (config.label) {
            let vBox = new St.BoxLayout({ vertical: true, x_expand: true });
            vBox.add_child(new St.Label({ text: config.label, style_class: 'buds-slider-label' }));
            let btnBox = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
            let btns = config.items.map(it => this._pill(it.icon, it.value, it.title, val => config.set(this._proxy, val)));
            btns.forEach(b => btnBox.add_child(b));
            vBox.add_child(btnBox);
            item.add_child(vBox);
            let ctrl = new PillGroupControl(item, btns, config);
            this._controls.push(ctrl);
        } else {
            let box = new St.BoxLayout({ style_class: 'buds-button-group', x_expand: true });
            let btns = config.items.map(it => this._pill(it.icon, it.value, it.title, val => config.set(this._proxy, val)));
            btns.forEach(b => box.add_child(b));
            item.add_child(box);
            let ctrl = new PillGroupControl(item, btns, config);
            this._controls.push(ctrl);
        }

        if (config.condition) item.visible = false;
        this.menu.addMenuItem(item);
    }

    _buildSwitch(config) {
        let swItem = new PopupMenu.PopupSwitchMenuItem(config.label, false);
        swItem.connect('toggled', (_, st) => {
            if (this._updating || !this._proxy) return;
            config.set(this._proxy, st, this);
        });
        this._setupKeyNav(swItem);
        if (config.condition) swItem.visible = false;
        this._controls.push(new SwitchControl(swItem, config));
        this.menu.addMenuItem(swItem);
    }

    _buildSlider(config) {
        let slItem = new PopupMenu.PopupBaseMenuItem({ reactive: false });
        let slBox  = new St.BoxLayout({ vertical: true, x_expand: true, style_class: 'buds-slider-box' });
        slBox.add_child(new St.Label({ text: config.label, style_class: 'buds-slider-label' }));

        let slider = new Slider.Slider(0.5);
        slider.connect('notify::value', () => {
            if (this._updating || !this._proxy) return;
            config.set(this._proxy, slider.value);
        });
        this._setupKeyNav(slider);
        slBox.add_child(slider);
        slItem.add_child(slBox);

        if (config.condition) slItem.visible = false;
        this._controls.push(new SliderControl(slItem, slider, config));
        this.menu.addMenuItem(slItem);
    }

    _addSectionTitle(text) {
        let item = new PopupMenu.PopupBaseMenuItem({ reactive: false, can_focus: false });
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
